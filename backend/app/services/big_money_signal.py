"""Big Money support-signal calculation.

Infers broad-market support traces from daily ETF share changes. This module
does not claim to observe actual 国家队 holdings.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from app.models.backtest import EtfPriceCache
from app.models.big_money import BigMoneySignal, EtfShareRecord, NorthboundFlow

CORE_ETFS = {
    "510050": "上证50ETF",
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
}

ROLLING_WINDOW = 20
BACKFILL_DAYS = 730


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _get_latest_nav(db, symbol: str, target: date) -> Optional[float]:
    row = (
        db.query(EtfPriceCache)
        .filter(EtfPriceCache.symbol == symbol, EtfPriceCache.date <= target)
        .order_by(EtfPriceCache.date.desc())
        .first()
    )
    return float(row.nav) if row else None


def _get_market_context(db, target: date) -> Dict[str, Optional[float]]:
    rows = (
        db.query(EtfPriceCache)
        .filter(
            EtfPriceCache.symbol == "510300",
            EtfPriceCache.date <= target,
            EtfPriceCache.date >= target - timedelta(days=45),
        )
        .order_by(EtfPriceCache.date)
        .all()
    )
    if not rows:
        nb = (
            db.query(NorthboundFlow)
            .filter(NorthboundFlow.channel == "total", NorthboundFlow.date == target)
            .first()
        )
        return {
            "market_daily_change": nb.hs300_change_pct if nb else None,
            "market_drawdown_20": None,
        }

    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else None
    daily_change = None
    if previous and previous.nav:
        daily_change = (latest.nav - previous.nav) / previous.nav * 100

    recent = rows[-20:]
    high_20 = max(r.nav for r in recent if r.nav is not None) if recent else None
    drawdown = _safe_ratio(latest.nav - high_20, high_20) if high_20 else None

    return {
        "market_daily_change": _round(daily_change, 2),
        "market_drawdown_20": _round(drawdown * 100, 2) if drawdown is not None else None,
    }


def _classify_signal(
    basket_delta: float,
    z_score: Optional[float],
    positive_count: int,
    negative_count: int,
    previous_signals: List[BigMoneySignal],
    market_drawdown_20: Optional[float],
    baseline_count: int,
) -> Dict[str, str]:
    """Return conservative main signal plus sensitive observation hint."""
    signal = "neutral"
    signal_label = "中性"
    watch_signal = "none"
    watch_label = "无观察信号"
    confidence = "low"

    z = z_score or 0.0
    baseline_ready = baseline_count >= ROLLING_WINDOW
    market_under_pressure = market_drawdown_20 is not None and market_drawdown_20 <= -3.0

    if z >= 1.5 or (basket_delta > 0 and positive_count >= 2):
        watch_signal = "watch_accumulate"
        watch_label = "加仓观察中"
        confidence = "low"
    elif z <= -1.5 or (basket_delta < 0 and negative_count >= 2):
        watch_signal = "watch_reduce"
        watch_label = "减仓观察中"
        confidence = "low"

    if baseline_ready and z >= 2.5 and positive_count >= 2:
        signal = "accumulate"
        signal_label = "疑似加仓"
        watch_signal = "none"
        watch_label = "无观察信号"
        confidence = "high" if market_under_pressure else "medium"
    else:
        recent_negative = [
            s for s in previous_signals[:2]
            if (
                (s.basket_delta_share or 0) < 0
                and (s.z_score or 0) <= -1.5
                and s.data_quality == "complete"
            )
        ]
        consecutive_negative = baseline_ready and len(recent_negative) >= 1 and z <= -1.5
        strong_negative = baseline_ready and z <= -3.0 and negative_count >= 2
        support_fading = (
            basket_delta < 0
            and negative_count >= 2
            and market_under_pressure
            and any((s.signal == "accumulate" or s.watch_signal == "watch_accumulate") for s in previous_signals[:5])
        )

        if strong_negative or consecutive_negative:
            signal = "reduce"
            signal_label = "疑似减仓"
            watch_signal = "none"
            watch_label = "无观察信号"
            confidence = "medium" if strong_negative else "low"
        elif baseline_ready and support_fading:
            signal = "support_fading"
            signal_label = "托底减弱"
            watch_signal = "none"
            watch_label = "无观察信号"
            confidence = "medium"

    return {
        "signal": signal,
        "signal_label": signal_label,
        "watch_signal": watch_signal,
        "watch_label": watch_label,
        "confidence": confidence,
    }


def _build_explanation(
    signal_label: str,
    watch_label: str,
    confidence: str,
    basket_delta: float,
    estimated_amount: Optional[float],
    z_score: Optional[float],
    etfs: List[Dict[str, Any]],
    data_quality: str,
) -> str:
    strongest = sorted(
        [e for e in etfs if e.get("delta_share") is not None],
        key=lambda e: abs(e.get("delta_share") or 0),
        reverse=True,
    )[:2]
    parts = [
        f"核心篮子合计份额变化 {basket_delta:+.2f} 亿份",
    ]
    if estimated_amount is not None:
        parts.append(f"估算资金 {estimated_amount:+.2f} 亿元")
    if z_score is not None:
        parts.append(f"20日异常度 {z_score:+.2f}σ")
    if strongest:
        parts.append(
            "主要变化来自 "
            + "、".join(f"{x['symbol']} {x['delta_share']:+.2f}亿份" for x in strongest)
        )
    if data_quality != "complete":
        parts.append(f"数据质量：{data_quality}")
    conclusion = signal_label if signal_label != "中性" else watch_label
    return f"{conclusion}（{confidence}置信）：{'；'.join(parts)}。"


def calculate_signal_for_date(target: date, persist: bool = True) -> Optional[Dict[str, Any]]:
    """Calculate one daily support signal from existing ETF share records."""
    db = SessionLocal()
    try:
        rows = (
            db.query(EtfShareRecord)
            .filter(
                EtfShareRecord.symbol.in_(list(CORE_ETFS.keys())),
                EtfShareRecord.date <= target,
                EtfShareRecord.date >= target - timedelta(days=90),
            )
            .order_by(EtfShareRecord.symbol, EtfShareRecord.date)
            .all()
        )
        by_symbol: Dict[str, List[EtfShareRecord]] = {symbol: [] for symbol in CORE_ETFS}
        for row in rows:
            by_symbol.setdefault(row.symbol, []).append(row)

        etf_evidence: List[Dict[str, Any]] = []
        basket_delta = 0.0
        estimated_amount = 0.0
        amount_available = False
        positive_count = 0
        negative_count = 0
        missing_symbols = []

        for symbol, name in CORE_ETFS.items():
            records = by_symbol.get(symbol, [])
            current_idx = next((i for i, r in enumerate(records) if r.date == target), None)
            if current_idx is None:
                missing_symbols.append(symbol)
                etf_evidence.append({
                    "symbol": symbol,
                    "name": name,
                    "date": target.isoformat(),
                    "total_share": None,
                    "delta_share": None,
                    "estimated_amount": None,
                    "nav": None,
                    "status": "missing",
                })
                continue
            if current_idx == 0:
                previous = None
            else:
                previous = records[current_idx - 1]
            current = records[current_idx]
            delta = None
            if previous and current.total_share is not None and previous.total_share is not None:
                delta = current.total_share - previous.total_share
                basket_delta += delta
                if delta > 0:
                    positive_count += 1
                elif delta < 0:
                    negative_count += 1

            nav = _get_latest_nav(db, symbol, target)
            est = delta * nav if delta is not None and nav is not None else None
            if est is not None:
                estimated_amount += est
                amount_available = True

            etf_evidence.append({
                "symbol": symbol,
                "name": current.name or name,
                "date": current.date.isoformat(),
                "total_share": _round(current.total_share, 4),
                "previous_share": _round(previous.total_share, 4) if previous else None,
                "delta_share": _round(delta, 4),
                "nav": _round(nav, 4),
                "estimated_amount": _round(est, 4),
                "status": "complete" if delta is not None else "insufficient_history",
            })

        complete_delta_count = sum(1 for e in etf_evidence if e.get("delta_share") is not None)
        if complete_delta_count == 0:
            return None

        historical_deltas: List[float] = []
        share_dates = sorted({
            r.date
            for records in by_symbol.values()
            for r in records
            if r.date < target
        })
        for d in share_dates:
            total_delta = 0.0
            ok = True
            for symbol in CORE_ETFS:
                records = by_symbol.get(symbol, [])
                idx = next((i for i, r in enumerate(records) if r.date == d), None)
                if idx is None or idx == 0:
                    ok = False
                    break
                cur = records[idx]
                prev = records[idx - 1]
                if cur.total_share is None or prev.total_share is None:
                    ok = False
                    break
                total_delta += cur.total_share - prev.total_share
            if ok:
                historical_deltas.append(total_delta)

        recent = historical_deltas[-ROLLING_WINDOW:]
        rolling_mean = mean(recent) if recent else None
        rolling_std = pstdev(recent) if len(recent) >= 2 else None
        z_score = None
        if rolling_mean is not None and rolling_std and rolling_std > 1e-9:
            z_score = (basket_delta - rolling_mean) / rolling_std

        previous_signals = (
            db.query(BigMoneySignal)
            .filter(BigMoneySignal.date < target)
            .order_by(BigMoneySignal.date.desc())
            .limit(5)
            .all()
        )
        market = _get_market_context(db, target)
        classification = _classify_signal(
            basket_delta=basket_delta,
            z_score=z_score,
            positive_count=positive_count,
            negative_count=negative_count,
            previous_signals=previous_signals,
            market_drawdown_20=market["market_drawdown_20"],
            baseline_count=len(recent),
        )

        data_quality = "complete"
        if missing_symbols:
            data_quality = "partial"
        if len(recent) < ROLLING_WINDOW:
            data_quality = "insufficient_baseline" if data_quality == "complete" else "partial_insufficient_baseline"

        explanation = _build_explanation(
            signal_label=classification["signal_label"],
            watch_label=classification["watch_label"],
            confidence=classification["confidence"],
            basket_delta=basket_delta,
            estimated_amount=estimated_amount if amount_available else None,
            z_score=z_score,
            etfs=etf_evidence,
            data_quality=data_quality,
        )

        payload = {
            "date": target.isoformat(),
            **classification,
            "basket_delta_share": _round(basket_delta, 4),
            "estimated_amount": _round(estimated_amount, 4) if amount_available else None,
            "z_score": _round(z_score, 4),
            "rolling_mean_20": _round(rolling_mean, 4),
            "rolling_std_20": _round(rolling_std, 4),
            "market_daily_change": market["market_daily_change"],
            "market_drawdown_20": market["market_drawdown_20"],
            "positive_etf_count": positive_count,
            "negative_etf_count": negative_count,
            "data_quality": data_quality,
            "evidence": {
                "core_etfs": etf_evidence,
                "explanation": explanation,
                "rolling_window": ROLLING_WINDOW,
                "baseline_count": len(recent),
            },
        }

        if persist:
            existing = db.query(BigMoneySignal).filter(BigMoneySignal.date == target).first()
            if existing:
                for key, value in payload.items():
                    if key == "date":
                        continue
                    setattr(existing, key, value)
            else:
                db.add(BigMoneySignal(
                    date=target,
                    signal=payload["signal"],
                    signal_label=payload["signal_label"],
                    watch_signal=payload["watch_signal"],
                    watch_label=payload["watch_label"],
                    confidence=payload["confidence"],
                    basket_delta_share=payload["basket_delta_share"],
                    estimated_amount=payload["estimated_amount"],
                    z_score=payload["z_score"],
                    rolling_mean_20=payload["rolling_mean_20"],
                    rolling_std_20=payload["rolling_std_20"],
                    market_daily_change=payload["market_daily_change"],
                    market_drawdown_20=payload["market_drawdown_20"],
                    positive_etf_count=payload["positive_etf_count"],
                    negative_etf_count=payload["negative_etf_count"],
                    evidence=payload["evidence"],
                    data_quality=payload["data_quality"],
                ))
            db.commit()

        return payload
    finally:
        db.close()


def calculate_latest_signal(persist: bool = True) -> Optional[Dict[str, Any]]:
    """Calculate signal for the latest date with ETF share records."""
    db = SessionLocal()
    try:
        latest = (
            db.query(EtfShareRecord.date)
            .filter(EtfShareRecord.symbol.in_(list(CORE_ETFS.keys())))
            .order_by(EtfShareRecord.date.desc())
            .first()
        )
        if not latest:
            return None
        target = latest[0]
    finally:
        db.close()
    return calculate_signal_for_date(target, persist=persist)


def backfill_signals(days: int = BACKFILL_DAYS) -> Dict[str, Any]:
    """Recalculate and persist signals for dates with ETF share records."""
    db = SessionLocal()
    try:
        cutoff = date.today() - timedelta(days=days)
        dates = [
            row[0]
            for row in (
                db.query(EtfShareRecord.date)
                .filter(
                    EtfShareRecord.symbol.in_(list(CORE_ETFS.keys())),
                    EtfShareRecord.date >= cutoff,
                )
                .distinct()
                .order_by(EtfShareRecord.date)
                .all()
            )
        ]
    finally:
        db.close()

    calculated = skipped = errors = 0
    latest_signal = None
    for d in dates:
        try:
            result = calculate_signal_for_date(d, persist=True)
            if result:
                calculated += 1
                latest_signal = result
            else:
                skipped += 1
        except Exception:
            errors += 1

    return {
        "calculated": calculated,
        "skipped": skipped,
        "errors": errors,
        "latest_signal": latest_signal,
    }
