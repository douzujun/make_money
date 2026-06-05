"""Sector Fund Flow API endpoints."""
import threading
from datetime import date, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.sector_flow import SectorFundFlow
from app.models.indicator import Indicator, IndicatorValue

router = APIRouter(prefix="/sector-flow", tags=["sector-flow"])

# ---------------------------------------------------------------------------
# Grade → VIX risk score (reuse existing volatility grades)
# ---------------------------------------------------------------------------
_VIX_RISK: Dict[str, float] = {
    "calm": 0.9, "low": 0.8, "normal": 0.6,
    "elevated": 0.4, "fear": 0.2, "panic": 0.1,
}

HORIZON_META = {
    "n1": {"label": "N+1 明日", "forward_days": 1},
    "n2": {"label": "N+2 延续", "forward_days": 2},
    "weekly": {"label": "周级趋势", "forward_days": 5},
}
SIGNAL_LOOKBACK_DAYS = 365
MIN_SIGNAL_ROWS = 6
BACKTEST_RISK_FACTOR = 0.6
FLOW_COVERAGE_MIN_POINTS = {
    "n1": 3,
    "n2": 3,
    "weekly": 10,
}
FLOW_COVERAGE_LOOKBACK = {
    "n1": 5,
    "n2": 5,
    "weekly": 20,
}
ACTION_MIN_SAMPLES = {"n1": 20, "n2": 20, "weekly": 30}
ACTION_MIN_EXCESS_HIT_RATE = 52
ACTION_MIN_FLOW_COVERAGE = 60


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _direction(score: float) -> tuple[str, str]:
    if score >= 65:
        return "bullish", "看多"
    if score <= 35:
        return "bearish", "看空"
    return "neutral", "中性"


def _signal_hint(horizon: str, score: float) -> str:
    direction, _ = _direction(score)
    if horizon == "n1":
        return "明日偏强，需结合次日成交确认" if direction == "bullish" else "明日偏弱，注意短线回撤" if direction == "bearish" else "明日信号较弱，建议观望"
    if horizon == "n2":
        return "短线延续偏强，观察流入是否继续放大" if direction == "bullish" else "短线延续转弱，流入衰减或价格走弱" if direction == "bearish" else "延续性不明确，等待下一交易日确认"
    return "周级趋势偏强，适合加入观察池" if direction == "bullish" else "周级趋势偏弱，降低关注优先级" if direction == "bearish" else "周级趋势中性，缺少持续优势"


def _get_vix_risk_factor() -> float:
    """Return a 0–1 global risk multiplier based on latest VIX grade."""
    db = SessionLocal()
    try:
        ind = db.query(Indicator).filter(
            Indicator.template_id == "VIX", Indicator.asset_id == "^VIX"
        ).first()
        if not ind:
            return 0.6
        iv = (
            db.query(IndicatorValue)
            .filter(IndicatorValue.indicator_id == ind.id)
            .order_by(IndicatorValue.date.desc())
            .first()
        )
        return _VIX_RISK.get(iv.grade, 0.6) if iv and iv.grade else 0.6
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Signal calculation
# ---------------------------------------------------------------------------

def _calc_signal(rows: List[SectorFundFlow], vix_factor: float) -> Dict[str, Any]:
    """
    Compute multi-horizon signals for a single sector given its recent rows (desc order).

    Compatibility fields at the top level keep the original N+1 signal.
    """
    if not rows:
        empty = {"score": 50, "direction": "neutral", "label": "数据不足", "summary": "数据不足", "details": {}}
        return {
            "score": 50,
            "direction": "neutral",
            "label": "数据不足",
            "win_rate_hint": "数据不足",
            "details": {},
            "horizons": {"n1": empty, "n2": empty, "weekly": empty},
        }

    # --- Fund flow momentum (40%) ---
    # Consecutive inflow days
    consecutive = 0
    for r in rows:
        if r.net_inflow_main is not None and r.net_inflow_main > 0:
            consecutive += 1
        else:
            break

    # 5-day cumulative net inflow ratio
    recent5 = [r.net_inflow_main_ratio for r in rows[:5] if r.net_inflow_main_ratio is not None]
    avg_ratio_5d = sum(recent5) / len(recent5) if recent5 else 0

    # Fund flow score: 50 base + consecutive bonus + ratio bonus
    ff_score = 50 + min(consecutive * 5, 25) + max(min(avg_ratio_5d * 10, 25), -25)
    ff_score = _clamp(ff_score)

    # --- Price momentum (40%) ---
    recent_changes = [r.change_pct for r in rows[:5] if r.change_pct is not None]
    sum_change = sum(recent_changes) if recent_changes else 0
    # Map -10% to +10% cumulative return → 0–100
    pm_score = 50 + sum_change * 3
    pm_score = _clamp(pm_score)

    # --- Global risk adjustment (20%) ---
    # vix_factor is 0.1 (panic) to 0.9 (calm); map to 0–100
    risk_score = vix_factor * 100

    # --- Composite ---
    n1_score = round(_clamp(ff_score * 0.40 + pm_score * 0.40 + risk_score * 0.20))

    recent3_flow = sum(r.net_inflow_main or 0 for r in rows[:3])
    prev3_flow = sum(r.net_inflow_main or 0 for r in rows[3:6])
    if abs(prev3_flow) > 1e-9 and recent3_flow < prev3_flow:
        flow_decay_penalty = min((prev3_flow - recent3_flow) / abs(prev3_flow) * 25, 25)
    else:
        flow_decay_penalty = 0
    recent3_change = sum(r.change_pct or 0 for r in rows[:3])
    n2_score = round(_clamp(n1_score - flow_decay_penalty + max(min(recent3_change * 2, 8), -12)))

    rows20 = rows[:20]
    ratio_values_20 = [r.net_inflow_main_ratio for r in rows20 if r.net_inflow_main_ratio is not None]
    avg_ratio_20 = sum(ratio_values_20) / len(ratio_values_20) if ratio_values_20 else 0
    inflow_days_20 = sum(1 for r in rows20 if r.net_inflow_main is not None and r.net_inflow_main > 0)
    inflow_day_ratio = inflow_days_20 / len(rows20) if rows20 else 0
    recent5_flow = sum(r.net_inflow_main or 0 for r in rows[:5])
    prev5_flow = sum(r.net_inflow_main or 0 for r in rows[5:10])
    flow_improving_bonus = 8 if recent5_flow > prev5_flow else -8 if recent5_flow < prev5_flow else 0
    weekly_flow_score = _clamp(50 + avg_ratio_20 * 8 + (inflow_day_ratio - 0.5) * 40 + flow_improving_bonus)
    change_values_20 = [r.change_pct for r in rows20 if r.change_pct is not None]
    sum_change_20 = sum(change_values_20)
    recent5_change = sum(r.change_pct or 0 for r in rows[:5])
    weekly_price_score = _clamp(50 + sum_change_20 * 1.2 + recent5_change * 1.5)
    weekly_score = round(_clamp(weekly_flow_score * 0.50 + weekly_price_score * 0.40 + risk_score * 0.10))

    def _pack(horizon: str, score: int, details: Dict[str, Any]) -> Dict[str, Any]:
        direction, label = _direction(score)
        return {
            "score": score,
            "direction": direction,
            "label": label,
            "summary": _signal_hint(horizon, score),
            "details": details,
        }

    horizons = {
        "n1": _pack("n1", n1_score, {
            "fund_flow_score": round(ff_score),
            "price_momentum_score": round(pm_score),
            "global_risk_score": round(risk_score),
            "consecutive_inflow_days": consecutive,
            "avg_5d_ratio": round(avg_ratio_5d, 2),
        }),
        "n2": _pack("n2", n2_score, {
            "base_n1_score": n1_score,
            "flow_decay_penalty": round(flow_decay_penalty, 2),
            "recent_3d_change": round(recent3_change, 2),
            "recent_3d_flow": round(recent3_flow, 2),
            "previous_3d_flow": round(prev3_flow, 2),
        }),
        "weekly": _pack("weekly", weekly_score, {
            "fund_flow_score": round(weekly_flow_score),
            "price_momentum_score": round(weekly_price_score),
            "global_risk_score": round(risk_score),
            "avg_20d_ratio": round(avg_ratio_20, 2),
            "inflow_day_ratio": round(inflow_day_ratio, 2),
            "sum_20d_change": round(sum_change_20, 2),
        }),
    }

    direction, label = _direction(n1_score)

    return {
        "score": n1_score,
        "direction": direction,
        "label": label,
        "win_rate_hint": _signal_hint("n1", n1_score),
        "details": horizons["n1"]["details"],
        "horizons": horizons,
    }


def _calc_backtest_for_horizon(
    grouped: Dict[str, List[SectorFundFlow]],
    horizon: str,
    risk_factor: float,
) -> Dict[str, Any]:
    forward_days = HORIZON_META[horizon]["forward_days"]
    thresholds = [60, 65, 70, 75]
    threshold_stats = {
        threshold: {"threshold": threshold, "samples": 0, "hit_rate": None, "avg_return": None}
        for threshold in thresholds
    }
    benchmark_returns: Dict[date, List[float]] = {}
    sample_rows: List[Dict[str, Any]] = []
    bullish_samples: List[Dict[str, Any]] = []
    bearish_samples: List[Dict[str, Any]] = []
    sector_perf: Dict[str, Dict[str, Any]] = {}

    for name, rows_desc in grouped.items():
        rows = sorted(rows_desc, key=lambda r: r.date)
        if len(rows) < forward_days + 6:
            continue
        for idx in range(5, len(rows) - forward_days):
            future_changes = [r.change_pct for r in rows[idx + 1: idx + forward_days + 1]]
            if any(v is None for v in future_changes):
                continue
            forward_return = sum(future_changes)
            benchmark_returns.setdefault(rows[idx].date, []).append(forward_return)

    benchmark_by_date = {
        d: sum(values) / len(values)
        for d, values in benchmark_returns.items()
        if values
    }

    def _has_flow_coverage(history: List[SectorFundFlow]) -> bool:
        lookback = FLOW_COVERAGE_LOOKBACK[horizon]
        min_points = FLOW_COVERAGE_MIN_POINTS[horizon]
        recent = history[:lookback]
        covered_points = sum(1 for r in recent if r.net_inflow_main is not None)
        return covered_points >= min_points

    for name, rows_desc in grouped.items():
        rows = sorted(rows_desc, key=lambda r: r.date)
        if len(rows) < forward_days + 6:
            continue
        sector_samples = []
        for idx in range(5, len(rows) - forward_days):
            history = list(reversed(rows[: idx + 1]))
            current_date = rows[idx].date
            if current_date not in benchmark_by_date:
                continue
            signal = _calc_signal(history, risk_factor).get("horizons", {}).get(horizon)
            if not signal:
                continue
            future_changes = [r.change_pct for r in rows[idx + 1: idx + forward_days + 1]]
            if any(v is None for v in future_changes):
                continue
            forward_return = sum(future_changes)
            benchmark_return = benchmark_by_date[current_date]
            sample = {
                "sector_name": name,
                "date": current_date,
                "score": signal["score"],
                "return": forward_return,
                "benchmark": benchmark_return,
                "excess": forward_return - benchmark_return,
                "flow_covered": _has_flow_coverage(history),
            }
            sample_rows.append(sample)
            score = signal["score"]
            if score >= 65:
                bullish_samples.append(sample)
                sector_samples.append(sample)
            if score <= 35:
                bearish_samples.append(sample)
            for threshold in thresholds:
                if score >= threshold:
                    stat = threshold_stats[threshold]
                    stat["samples"] += 1
                    stat.setdefault("_samples", []).append(sample)

        if sector_samples:
            wins = sum(1 for s in sector_samples if s["excess"] > 0)
            sector_perf[name] = {
                "samples": len(sector_samples),
                "hit_rate": round(wins / len(sector_samples) * 100, 1),
                "avg_return": round(sum(s["return"] for s in sector_samples) / len(sector_samples), 2),
                "excess_avg_return": round(sum(s["excess"] for s in sector_samples) / len(sector_samples), 2),
            }

    for stat in threshold_stats.values():
        samples = stat.pop("_samples", [])
        if samples:
            stat["hit_rate"] = round(sum(1 for s in samples if s["return"] > 0) / len(samples) * 100, 1)
            stat["excess_hit_rate"] = round(sum(1 for s in samples if s["excess"] > 0) / len(samples) * 100, 1)
            stat["avg_return"] = round(sum(s["return"] for s in samples) / len(samples), 2)
            stat["benchmark_avg_return"] = round(sum(s["benchmark"] for s in samples) / len(samples), 2)
            stat["excess_avg_return"] = round(sum(s["excess"] for s in samples) / len(samples), 2)
            flow_coverage_samples = sum(1 for s in samples if s["flow_covered"])
            stat["flow_coverage_samples"] = flow_coverage_samples
            stat["flow_coverage_rate"] = round(flow_coverage_samples / len(samples) * 100, 1)

    def _summary(samples: List[Dict[str, Any]], bullish: bool) -> Dict[str, Any]:
        if not samples:
            return {
                "samples": 0,
                "hit_rate": None,
                "excess_hit_rate": None,
                "avg_return": None,
                "benchmark_avg_return": None,
                "excess_avg_return": None,
                "flow_coverage_samples": 0,
                "flow_coverage_rate": None,
            }
        if bullish:
            hits = sum(1 for s in samples if s["return"] > 0)
            excess_hits = sum(1 for s in samples if s["excess"] > 0)
        else:
            hits = sum(1 for s in samples if s["return"] < 0)
            excess_hits = sum(1 for s in samples if s["excess"] < 0)
        flow_coverage_samples = sum(1 for s in samples if s["flow_covered"])
        return {
            "samples": len(samples),
            "hit_rate": round(hits / len(samples) * 100, 1),
            "excess_hit_rate": round(excess_hits / len(samples) * 100, 1),
            "avg_return": round(sum(s["return"] for s in samples) / len(samples), 2),
            "benchmark_avg_return": round(sum(s["benchmark"] for s in samples) / len(samples), 2),
            "excess_avg_return": round(sum(s["excess"] for s in samples) / len(samples), 2),
            "flow_coverage_samples": flow_coverage_samples,
            "flow_coverage_rate": round(flow_coverage_samples / len(samples) * 100, 1),
        }

    best_threshold = max(
        threshold_stats.values(),
        key=lambda x: ((x.get("excess_hit_rate") or 0), x["samples"], x.get("excess_avg_return") or 0),
    )
    top_sectors = sorted(
        [{"sector_name": k, **v} for k, v in sector_perf.items()],
        key=lambda x: (x["hit_rate"], x["samples"]),
        reverse=True,
    )[:5]

    return {
        "horizon": horizon,
        "label": HORIZON_META[horizon]["label"],
        "forward_days": forward_days,
        "total_samples": len(sample_rows),
        "bullish": _summary(bullish_samples, True),
        "bearish": _summary(bearish_samples, False),
        "thresholds": list(threshold_stats.values()),
        "best_threshold": best_threshold,
        "top_sectors": top_sectors,
    }


def _current_flow_coverage(rows: List[SectorFundFlow], horizon: str) -> Dict[str, Any]:
    lookback = FLOW_COVERAGE_LOOKBACK[horizon]
    recent = rows[:lookback]
    covered = sum(1 for r in recent if r.net_inflow_main is not None)
    total = len(recent)
    return {
        "covered": covered,
        "total": total,
        "rate": round(covered / total * 100, 1) if total else None,
    }


def _calc_signal_action(
    sig: Dict[str, Any],
    rows: List[SectorFundFlow],
    backtests: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    n1 = sig["horizons"]["n1"]
    n2 = sig["horizons"]["n2"]
    n1_bt = backtests.get("n1", {}).get("bullish", {})
    n2_bt = backtests.get("n2", {}).get("bullish", {})
    n1_flow = _current_flow_coverage(rows, "n1")
    n2_flow = _current_flow_coverage(rows, "n2")
    best_horizon = "n1" if n1["score"] >= n2["score"] else "n2"
    best_score = max(n1["score"], n2["score"])
    best_bt = n1_bt if best_horizon == "n1" else n2_bt
    best_flow = n1_flow if best_horizon == "n1" else n2_flow

    flow_decay_penalty = n2["details"].get("flow_decay_penalty", 0) or 0
    if n1["score"] <= 35 or n2["score"] <= 35:
        trigger_horizon = "n1" if n1["score"] <= n2["score"] else "n2"
        trigger_signal = n1 if trigger_horizon == "n1" else n2
        trigger_flow = n1_flow if trigger_horizon == "n1" else n2_flow
        return {
            "action": "reduce",
            "label": "减仓",
            "strength": "watch",
            "reason": "短线低分",
            "horizon": trigger_horizon,
            "score": trigger_signal["score"],
            "flow_coverage_rate": trigger_flow["rate"],
        }
    if flow_decay_penalty >= 12:
        return {
            "action": "reduce_watch",
            "label": "减仓观察",
            "strength": "watch",
            "reason": "资金流衰减",
            "horizon": "n2",
            "score": n2["score"],
            "flow_coverage_rate": n2_flow["rate"],
        }

    if best_score >= 65:
        if (best_flow["rate"] or 0) < ACTION_MIN_FLOW_COVERAGE:
            return {
                "action": "observe",
                "label": "观察",
                "strength": "watch",
                "reason": "资金流覆盖不足",
                "horizon": best_horizon,
                "score": best_score,
                "flow_coverage_rate": best_flow["rate"],
            }
        if (
            best_bt.get("samples", 0) >= ACTION_MIN_SAMPLES[best_horizon]
            and (best_bt.get("excess_avg_return") or 0) > 0
            and (best_bt.get("excess_hit_rate") or 0) >= ACTION_MIN_EXCESS_HIT_RATE
        ):
            label = "谨慎加仓" if (best_flow["rate"] or 0) < 80 else "加仓"
            return {
                "action": "accumulate",
                "label": label,
                "strength": "cautious" if label == "谨慎加仓" else "normal",
                "reason": "短线强且回测超额为正",
                "horizon": best_horizon,
                "score": best_score,
                "flow_coverage_rate": best_flow["rate"],
            }
        return {
            "action": "observe",
            "label": "观察",
            "strength": "watch",
            "reason": "回测证据不足",
            "horizon": best_horizon,
            "score": best_score,
            "flow_coverage_rate": best_flow["rate"],
        }

    weekly = sig["horizons"]["weekly"]
    if weekly["score"] >= 65:
        return {
            "action": "observe",
            "label": "观察",
            "strength": "watch",
            "reason": "周级转强",
            "horizon": "weekly",
            "score": weekly["score"],
            "flow_coverage_rate": _current_flow_coverage(rows, "weekly")["rate"],
        }

    return {
        "action": "hold",
        "label": "持有",
        "strength": "neutral",
        "reason": "暂无强触发",
        "horizon": best_horizon,
        "score": best_score,
        "flow_coverage_rate": best_flow["rate"],
    }


def _display_signal(sig: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    if action["action"] in {"reduce", "reduce_watch"}:
        horizon_label = HORIZON_META[action["horizon"]]["label"]
        return {
            "score": action["score"],
            "direction": action["action"],
            "label": action["label"],
            "summary": f"{horizon_label}触发{action['reason']}，优先按风控处理",
        }
    if action["action"] == "accumulate":
        horizon_label = HORIZON_META[action["horizon"]]["label"]
        return {
            "score": action["score"],
            "direction": "bullish",
            "label": action["label"],
            "summary": f"{horizon_label}短线强且回测证据通过",
        }
    if action["action"] == "observe":
        horizon_label = HORIZON_META[action["horizon"]]["label"]
        return {
            "score": action["score"],
            "direction": "observe",
            "label": action["label"],
            "summary": f"{horizon_label}{action['reason']}，不直接加仓",
        }
    return sig["horizons"]["n1"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/industry")
def get_industry_flow(days: int = Query(default=20, ge=5, le=120)):
    """
    Return last `days` trading days of fund flow for all industry sectors.

    Response shape:
      {
        "sectors": ["电子", ...],
        "dates": ["2026-05-23", ...],
        "data": {
          "电子": [{"date": ..., "net_inflow_main": ..., "change_pct": ...}, ...]
        }
      }
    """
    cutoff = date.today() - timedelta(days=days * 2)  # extra buffer for weekends
    db = SessionLocal()
    try:
        rows = (
            db.query(SectorFundFlow)
            .filter(
                SectorFundFlow.sector_type == "industry",
                SectorFundFlow.date >= cutoff,
            )
            .order_by(SectorFundFlow.sector_name, SectorFundFlow.date)
            .all()
        )

        if not rows:
            return {"sectors": [], "dates": [], "data": {}, "message": "暂无数据，请先点击「刷新数据」"}

        # Group by sector
        from collections import defaultdict
        grouped: Dict[str, list] = defaultdict(list)
        all_dates = set()
        for r in rows:
            grouped[r.sector_name].append({
                "date": r.date.isoformat(),
                "net_inflow_main": r.net_inflow_main,
                "net_inflow_main_ratio": r.net_inflow_main_ratio,
                "change_pct": r.change_pct,
                "net_inflow_super_large": r.net_inflow_super_large,
                "net_inflow_large": r.net_inflow_large,
            })
            all_dates.add(r.date.isoformat())

        # Keep only the last `days` trading dates
        sorted_dates = sorted(all_dates)[-days:]
        date_set = set(sorted_dates)

        # Filter each sector to only these dates
        filtered: Dict[str, list] = {}
        for name, records in grouped.items():
            filtered[name] = [r for r in records if r["date"] in date_set]

        # Remove sectors that only appear on 1 date — these are sub-category artifacts
        # from a different data source (THS vs East Money) mixed in the same window.
        min_dates_required = min(2, len(sorted_dates))
        filtered = {
            name: recs
            for name, recs in filtered.items()
            if len(recs) >= min_dates_required
        }

        return {
            "sectors": sorted(filtered.keys()),
            "dates": sorted_dates,
            "data": filtered,
        }
    finally:
        db.close()


@router.get("/concept")
def get_concept_flow(date_str: Optional[str] = Query(default=None, alias="date")):
    """
    Return latest concept sector hot board (top entries by net inflow).
    If `date` param provided, returns data for that specific date.
    """
    db = SessionLocal()
    try:
        query = db.query(SectorFundFlow).filter(SectorFundFlow.sector_type == "concept")

        if date_str:
            try:
                target_date = date.fromisoformat(date_str)
                query = query.filter(SectorFundFlow.date == target_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format")
        else:
            # Latest available date
            latest = (
                db.query(func.max(SectorFundFlow.date))
                .filter(SectorFundFlow.sector_type == "concept")
                .scalar()
            )
            if not latest:
                return {"date": None, "sectors": [], "message": "暂无概念数据，请先点击「刷新数据」"}
            query = query.filter(SectorFundFlow.date == latest)

        rows = query.order_by(SectorFundFlow.net_inflow_main.desc()).all()

        if not rows:
            return {"date": date_str, "sectors": [], "message": "该日期暂无数据"}

        return {
            "date": rows[0].date.isoformat(),
            "sectors": [
                {
                    "name": r.sector_name,
                    "change_pct": r.change_pct,
                    "net_inflow_main": r.net_inflow_main,
                    "net_inflow_main_ratio": r.net_inflow_main_ratio,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@router.get("/signals")
def get_sector_signals():
    """
    Compute multi-horizon signals and historical validation for industry sectors.
    """
    cutoff = date.today() - timedelta(days=SIGNAL_LOOKBACK_DAYS)
    vix_factor = _get_vix_risk_factor()

    db = SessionLocal()
    try:
        all_rows = (
            db.query(SectorFundFlow)
            .filter(
                SectorFundFlow.sector_type == "industry",
                SectorFundFlow.date >= cutoff,
            )
            .order_by(SectorFundFlow.sector_name, SectorFundFlow.date.desc())
            .all()
        )

        if not all_rows:
            return {
                "signals": [],
                "backtests": {},
                "horizons": HORIZON_META,
                "vix_factor": vix_factor,
                "message": "暂无数据",
            }

        # Group by sector
        from collections import defaultdict
        grouped: Dict[str, list] = defaultdict(list)
        for r in all_rows:
            grouped[r.sector_name].append(r)

        signal_grouped = {
            name: rows
            for name, rows in grouped.items()
            if len(rows) >= MIN_SIGNAL_ROWS
        }

        backtests = {
            horizon: _calc_backtest_for_horizon(signal_grouped, horizon, BACKTEST_RISK_FACTOR)
            for horizon in HORIZON_META
        }

        signals = []
        for name, rows in signal_grouped.items():
            sig = _calc_signal(rows, vix_factor)
            action = _calc_signal_action(sig, rows, backtests)
            latest = rows[0]
            signals.append({
                "sector_name": name,
                "latest_date": latest.date.isoformat(),
                "latest_change_pct": latest.change_pct,
                "latest_net_inflow_main": latest.net_inflow_main,
                "history_days": len(rows),
                "signal_action": action,
                "display_signal": _display_signal(sig, action),
                **sig,
            })

        signals.sort(key=lambda x: x["score"], reverse=True)

        all_dates = [r.date for r in all_rows]

        return {
            "signals": signals,
            "backtests": backtests,
            "horizons": HORIZON_META,
            "vix_factor": round(vix_factor, 2),
            "computed_at": date.today().isoformat(),
            "data_window": {
                "start": min(all_dates).isoformat() if all_dates else None,
                "end": max(all_dates).isoformat() if all_dates else None,
                "lookback_days": SIGNAL_LOOKBACK_DAYS,
            },
            "excluded_sector_count": len(grouped) - len(signal_grouped),
            "backtest_note": "回测按历史每日信号与未来收益验证；风险项使用中性值，避免用当前VIX回看历史。",
        }
    finally:
        db.close()


@router.post("/backfill")
def backfill_history(days: int = Query(default=30, ge=5, le=365)):
    """
    Backfill historical daily price-change data for all THS industry sectors.
    Runs in background; a one-year window can take a few minutes for 90 sectors.
    """
    from app.fetchers.akshare_fetcher import backfill_sector_history_ths

    def _run():
        result = backfill_sector_history_ths(days=days)
        import logging
        logging.getLogger("sector-flow").info("Backfill done: %s", result)

    thread = threading.Thread(target=_run, daemon=True, name="sector-flow-backfill")
    thread.start()
    return {"message": f"历史数据回填已启动（近{days}天价格历史），完成后刷新页面可见历史走势"}


@router.post("/refresh")
def refresh_sector_flow(source: str = Query(default="auto")):
    """
    Manually trigger today's sector fund flow fetch (runs in background).

    source: 'auto' | 'eastmoney' | 'ths'
      auto       — try East Money first, fall back to THS
      eastmoney  — East Money (东方财富) only
      ths        — 同花顺 only
    """
    if source not in ("auto", "eastmoney", "ths"):
        raise HTTPException(status_code=400, detail="source must be auto / eastmoney / ths")

    from app.fetchers.akshare_fetcher import run_daily_sector_flow_job

    def _run():
        result = run_daily_sector_flow_job(source=source)
        import logging
        logging.getLogger("sector-flow").info("Manual refresh done (source=%s): %s", source, result)

    thread = threading.Thread(target=_run, daemon=True, name=f"manual-sector-flow-{source}")
    thread.start()

    source_label = {"auto": "自动（东财优先/同花顺降级）", "eastmoney": "东方财富", "ths": "同花顺"}.get(source, source)
    return {"message": f"数据抓取已在后台启动（{source_label}），约 15–30 秒后刷新页面可见新数据", "source": source}
