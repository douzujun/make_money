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
    Compute next-day signal for a single sector given its recent rows (desc order).

    Score = fund_flow_momentum (40%) + price_momentum (40%) + global_risk (20%)
    Returns: score (0–100), direction, win_rate_hint
    """
    if not rows:
        return {"score": 50, "direction": "neutral", "label": "数据不足"}

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
    ff_score = max(0, min(100, ff_score))

    # --- Price momentum (40%) ---
    recent_changes = [r.change_pct for r in rows[:5] if r.change_pct is not None]
    sum_change = sum(recent_changes) if recent_changes else 0
    # Map -10% to +10% cumulative return → 0–100
    pm_score = 50 + sum_change * 3
    pm_score = max(0, min(100, pm_score))

    # --- Global risk adjustment (20%) ---
    # vix_factor is 0.1 (panic) to 0.9 (calm); map to 0–100
    risk_score = vix_factor * 100

    # --- Composite ---
    composite = ff_score * 0.40 + pm_score * 0.40 + risk_score * 0.20
    composite = round(max(0, min(100, composite)))

    # Direction + win rate hint
    if composite >= 65:
        direction = "bullish"
        label = "看多"
        win_hint = f"历史参考：近期类似条件下次日上涨概率约 {min(55 + (composite - 65), 72):.0f}%"
    elif composite <= 35:
        direction = "bearish"
        label = "看空"
        win_hint = f"历史参考：近期类似条件下次日下跌概率约 {min(55 + (35 - composite), 70):.0f}%"
    else:
        direction = "neutral"
        label = "中性"
        win_hint = "信号较弱，建议观望"

    return {
        "score": composite,
        "direction": direction,
        "label": label,
        "win_rate_hint": win_hint,
        "details": {
            "fund_flow_score": round(ff_score),
            "price_momentum_score": round(pm_score),
            "global_risk_score": round(risk_score),
            "consecutive_inflow_days": consecutive,
            "avg_5d_ratio": round(avg_ratio_5d, 2),
        },
    }


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
    Compute next-day prediction signals for all industry sectors.
    Uses last 20 trading days of fund flow + price data + global VIX.
    """
    cutoff = date.today() - timedelta(days=60)
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
            return {"signals": [], "vix_factor": vix_factor, "message": "暂无数据"}

        # Group by sector
        from collections import defaultdict
        grouped: Dict[str, list] = defaultdict(list)
        for r in all_rows:
            grouped[r.sector_name].append(r)

        signals = []
        for name, rows in grouped.items():
            sig = _calc_signal(rows, vix_factor)
            latest = rows[0]
            signals.append({
                "sector_name": name,
                "latest_date": latest.date.isoformat(),
                "latest_change_pct": latest.change_pct,
                "latest_net_inflow_main": latest.net_inflow_main,
                **sig,
            })

        # Sort by score descending
        signals.sort(key=lambda x: x["score"], reverse=True)

        return {
            "signals": signals,
            "vix_factor": round(vix_factor, 2),
            "computed_at": date.today().isoformat(),
        }
    finally:
        db.close()


@router.post("/backfill")
def backfill_history(days: int = Query(default=30, ge=5, le=90)):
    """
    Backfill historical daily price-change data for all THS industry sectors.
    Runs in background; takes ~20–40 seconds for 90 sectors.
    """
    from app.fetchers.akshare_fetcher import backfill_sector_history_ths

    def _run():
        result = backfill_sector_history_ths(days=days)
        import logging
        logging.getLogger("sector-flow").info("Backfill done: %s", result)

    thread = threading.Thread(target=_run, daemon=True, name="sector-flow-backfill")
    thread.start()
    return {"message": f"历史数据回填已启动（近{days}个交易日），约 30 秒后刷新页面可见历史走势"}


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
