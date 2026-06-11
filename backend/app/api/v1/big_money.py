"""Big Money Flow API endpoints — northbound capital and ETF share tracking."""
import threading
from datetime import date, timedelta
from typing import List, Optional, Dict, Any
from statistics import mean, pstdev

from fastapi import APIRouter, Query, HTTPException

from app.core.database import SessionLocal
from app.models.big_money import NorthboundFlow, EtfShareRecord, BigMoneySignal

router = APIRouter(prefix="/big-money", tags=["big-money"])

# Known Central Huijin public intervention announcements (for frontend annotation)
HUIJIN_EVENTS = [
    {"date": "2023-10-23", "label": "汇金增持公告"},
    {"date": "2024-02-06", "label": "汇金再次增持"},
]


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous * 100


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _risk_preference_signal(
    bei_return_5d: Optional[float],
    relative_return_5d: Optional[float],
    volume_z_score: Optional[float],
    drawdown_20d: Optional[float],
) -> Dict[str, str]:
    volume_expansion = volume_z_score is not None and volume_z_score >= 1.0
    strong_relative = relative_return_5d is not None and relative_return_5d >= 3.0
    weak_relative = relative_return_5d is not None and relative_return_5d <= -3.0
    strong_return = bei_return_5d is not None and bei_return_5d >= 5.0
    weak_return = bei_return_5d is not None and bei_return_5d <= -5.0
    deep_drawdown = drawdown_20d is not None and drawdown_20d <= -8.0

    if strong_return and strong_relative and volume_expansion:
        return {
            "signal": "accumulate_watch",
            "label": "加仓观察",
            "summary": "北证50放量跑赢沪深300，风险偏好扩散",
        }
    if weak_return or (weak_relative and deep_drawdown):
        return {
            "signal": "reduce_watch",
            "label": "减仓观察",
            "summary": "北证50弱于核心大盘，小盘风险偏好退潮",
        }
    if strong_relative and (bei_return_5d or 0) > 0:
        return {
            "signal": "risk_on_watch",
            "label": "风险偏好观察",
            "summary": "北证50相对走强，但量能或绝对涨幅仍需确认",
        }
    return {
        "signal": "neutral",
        "label": "中性",
        "summary": "北交所风险偏好未出现强触发",
    }


@router.get("/northbound")
def get_northbound(days: int = Query(default=0, ge=0, le=3650)):
    """
    Return northbound capital daily net buy amount.
    days=0 (default): return ALL available data.
    days>0: filter to last N calendar days.
    Note: historical data from stock_hsgt_hist_em is valid up to 2024-08-16;
    data after that is accumulated daily from stock_hsgt_fund_flow_summary_em.
    """
    db = SessionLocal()
    try:
        query = db.query(NorthboundFlow).filter(NorthboundFlow.channel == "total")
        if days > 0:
            cutoff = date.today() - timedelta(days=days)
            query = query.filter(NorthboundFlow.date >= cutoff)
        rows = query.order_by(NorthboundFlow.date).all()

        if not rows:
            return {
                "data": [],
                "message": "暂无数据，请先点击「刷新数据」",
                "huijin_events": HUIJIN_EVENTS,
            }

        data = [
            {
                "date": r.date.isoformat(),
                "net_buy_amount": r.net_buy_amount,
                "net_inflow": r.net_inflow,
                "hs300_close": r.hs300_close,
                "hs300_change_pct": r.hs300_change_pct,
            }
            for r in rows
        ]
        return {
            "data": data,
            "latest_date": rows[-1].date.isoformat(),
            "huijin_events": HUIJIN_EVENTS,
        }
    finally:
        db.close()


@router.get("/northbound/channels")
def get_northbound_channels(days: int = Query(default=30, ge=5, le=365)):
    """
    Return per-channel (sh_hk / sz_hk) northbound data for the last `days` days.
    """
    cutoff = date.today() - timedelta(days=days)
    db = SessionLocal()
    try:
        rows = (
            db.query(NorthboundFlow)
            .filter(
                NorthboundFlow.channel.in_(["sh_hk", "sz_hk"]),
                NorthboundFlow.date >= cutoff,
            )
            .order_by(NorthboundFlow.date, NorthboundFlow.channel)
            .all()
        )
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in rows:
            grouped[r.channel].append({
                "date": r.date.isoformat(),
                "net_buy_amount": r.net_buy_amount,
                "hs300_change_pct": r.hs300_change_pct,
            })
        return {
            "sh_hk": grouped["sh_hk"],
            "sz_hk": grouped["sz_hk"],
        }
    finally:
        db.close()


@router.get("/etf-shares")
def get_etf_shares(days: int = Query(default=0, ge=0, le=3650)):
    """
    Return ETF share counts for 510050 / 510300 / 510500.
    days=0: return all available data. days>0: last N calendar days.
    """
    db = SessionLocal()
    try:
        query = db.query(EtfShareRecord)
        if days > 0:
            cutoff = date.today() - timedelta(days=days)
            query = query.filter(EtfShareRecord.date >= cutoff)
        rows = query.order_by(EtfShareRecord.symbol, EtfShareRecord.date).all()
        if not rows:
            return {
                "symbols": [],
                "data": {},
                "message": "暂无 ETF 份额数据，请先点击「刷新数据」",
                "huijin_events": HUIJIN_EVENTS,
            }

        from collections import defaultdict
        grouped = defaultdict(list)
        for r in rows:
            grouped[r.symbol].append({
                "date": r.date.isoformat(),
                "total_share": r.total_share,
                "name": r.name,
            })

        return {
            "symbols": sorted(grouped.keys()),
            "data": dict(grouped),
            "huijin_events": HUIJIN_EVENTS,
        }
    finally:
        db.close()


@router.get("/signals")
def get_big_money_signals(days: int = Query(default=365, ge=5, le=3650)):
    """
    Return daily broad-market support signals inferred from core ETF share changes.
    """
    cutoff = date.today() - timedelta(days=days)
    db = SessionLocal()
    try:
        rows = (
            db.query(BigMoneySignal)
            .filter(BigMoneySignal.date >= cutoff)
            .order_by(BigMoneySignal.date)
            .all()
        )
        if not rows:
            return {
                "data": [],
                "latest": None,
                "message": "暂无托底信号，请先导入 ETF 份额历史或刷新今日数据",
            }
        data = [
            {
                "date": r.date.isoformat(),
                "signal": r.signal,
                "signal_label": r.signal_label,
                "watch_signal": r.watch_signal,
                "watch_label": r.watch_label,
                "confidence": r.confidence,
                "basket_delta_share": r.basket_delta_share,
                "estimated_amount": r.estimated_amount,
                "z_score": r.z_score,
                "rolling_mean_20": r.rolling_mean_20,
                "rolling_std_20": r.rolling_std_20,
                "market_daily_change": r.market_daily_change,
                "market_drawdown_20": r.market_drawdown_20,
                "positive_etf_count": r.positive_etf_count,
                "negative_etf_count": r.negative_etf_count,
                "data_quality": r.data_quality,
                "evidence": r.evidence,
            }
            for r in rows
        ]
        return {
            "data": data,
            "latest": data[-1],
            "method": {
                "core_etfs": ["510050", "510300", "510500"],
                "main_signal": "conservative",
                "watch_signal": "sensitive",
                "rolling_window": 20,
            },
        }
    finally:
        db.close()


@router.get("/bei50-risk")
def get_bei50_risk(days: int = Query(default=180, ge=30, le=1000)):
    """
    Return 北证50 risk-preference evidence.

    This is an auxiliary small-cap sentiment signal, not part of the
    state-support core ETF basket.
    """
    try:
        import akshare as ak
        import pandas as pd

        bei_df = ak.stock_zh_index_daily(symbol="bj899050")
        hs_df = ak.stock_zh_index_daily(symbol="sh000300")
        if bei_df.empty or hs_df.empty:
            return {
                "data": [],
                "latest": None,
                "message": "暂无北证50或沪深300指数数据",
            }

        def _prep(df):
            out = df.copy()
            out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
            out["close"] = pd.to_numeric(out["close"], errors="coerce")
            out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
            return out.dropna(subset=["date", "close"]).sort_values("date")

        bei = _prep(bei_df).rename(columns={"close": "bei50_close", "volume": "bei50_volume"})
        hs = _prep(hs_df).rename(columns={"close": "hs300_close", "volume": "hs300_volume"})
        merged = pd.merge(
            bei[["date", "bei50_close", "bei50_volume"]],
            hs[["date", "hs300_close"]],
            on="date",
            how="inner",
        ).sort_values("date")

        rows: List[Dict[str, Any]] = []
        records = merged.to_dict("records")
        for idx, row in enumerate(records):
            bei_close = float(row["bei50_close"])
            hs_close = float(row["hs300_close"])
            prev = records[idx - 1] if idx >= 1 else None
            prev5 = records[idx - 5] if idx >= 5 else None
            recent20 = records[max(0, idx - 19): idx + 1]
            previous20 = records[max(0, idx - 20): idx]

            bei_return_1d = _pct_change(bei_close, float(prev["bei50_close"])) if prev else None
            hs_return_1d = _pct_change(hs_close, float(prev["hs300_close"])) if prev else None
            bei_return_5d = _pct_change(bei_close, float(prev5["bei50_close"])) if prev5 else None
            hs_return_5d = _pct_change(hs_close, float(prev5["hs300_close"])) if prev5 else None
            relative_return_5d = (
                bei_return_5d - hs_return_5d
                if bei_return_5d is not None and hs_return_5d is not None
                else None
            )
            volume_values = [float(x["bei50_volume"]) for x in previous20 if x.get("bei50_volume") is not None]
            volume_mean = mean(volume_values) if volume_values else None
            volume_std = pstdev(volume_values) if len(volume_values) >= 2 else None
            volume_z_score = None
            if volume_mean is not None and volume_std and volume_std > 1e-9 and row.get("bei50_volume") is not None:
                volume_z_score = (float(row["bei50_volume"]) - volume_mean) / volume_std
            high_20 = max(float(x["bei50_close"]) for x in recent20) if recent20 else None
            drawdown_20d = _pct_change(bei_close, high_20) if high_20 else None

            signal = _risk_preference_signal(
                bei_return_5d=bei_return_5d,
                relative_return_5d=relative_return_5d,
                volume_z_score=volume_z_score,
                drawdown_20d=drawdown_20d,
            )
            rows.append({
                "date": row["date"].isoformat(),
                "bei50_close": _round(bei_close, 3),
                "hs300_close": _round(hs_close, 3),
                "bei50_return_1d": _round(bei_return_1d),
                "hs300_return_1d": _round(hs_return_1d),
                "bei50_return_5d": _round(bei_return_5d),
                "hs300_return_5d": _round(hs_return_5d),
                "relative_return_5d": _round(relative_return_5d),
                "volume_z_score": _round(volume_z_score),
                "drawdown_20d": _round(drawdown_20d),
                "signal": signal["signal"],
                "label": signal["label"],
                "summary": signal["summary"],
            })

        trimmed = rows[-days:]
        return {
            "data": trimmed,
            "latest": trimmed[-1] if trimmed else None,
            "method": {
                "index": "北证50成份指数 899050",
                "benchmark": "沪深300 sh000300",
                "main_signal": "辅助风险偏好，不纳入国家队托底主信号",
                "rules": [
                    "5日涨幅 >= 5% 且相对沪深300 >= 3% 且成交量 >= +1σ：加仓观察",
                    "5日跌幅 <= -5% 或相对沪深300 <= -3% 且20日回撤 <= -8%：减仓观察",
                ],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"北证50风险偏好数据获取失败: {e}")


@router.get("/today")
def get_today_snapshot():
    """
    Return today's snapshot: latest northbound channels + latest ETF shares.
    """
    db = SessionLocal()
    try:
        latest_nb_date = (
            db.query(NorthboundFlow.date)
            .order_by(NorthboundFlow.date.desc())
            .first()
        )
        nb_rows = []
        if latest_nb_date:
            nb_rows = (
                db.query(NorthboundFlow)
                .filter(NorthboundFlow.date == latest_nb_date[0])
                .all()
            )

        latest_etf_date = (
            db.query(EtfShareRecord.date)
            .order_by(EtfShareRecord.date.desc())
            .first()
        )
        etf_rows = []
        if latest_etf_date:
            etf_rows = (
                db.query(EtfShareRecord)
                .filter(EtfShareRecord.date == latest_etf_date[0])
                .all()
            )

        return {
            "northbound": {
                "date": latest_nb_date[0].isoformat() if latest_nb_date else None,
                "channels": [
                    {
                        "channel": r.channel,
                        "net_buy_amount": r.net_buy_amount,
                        "net_inflow": r.net_inflow,
                        "hs300_change_pct": r.hs300_change_pct,
                    }
                    for r in nb_rows
                ],
            },
            "etf_shares": {
                "date": latest_etf_date[0].isoformat() if latest_etf_date else None,
                "items": [
                    {
                        "symbol": r.symbol,
                        "name": r.name,
                        "total_share": r.total_share,
                    }
                    for r in etf_rows
                ],
            },
        }
    finally:
        db.close()


@router.get("/northbound/intraday")
def get_northbound_intraday():
    """
    Return minute-level northbound capital flow for the current (or last) trading day.
    NOTE: stock_hsgt_fund_min_em has returned all-zero values since East Money changed
    their API structure in Aug 2024. AkShare has not adapted. Data source is broken.
    """
    try:
        import akshare as ak
        df = ak.stock_hsgt_fund_min_em(symbol="北向资金")
        if df.empty:
            return {"date": None, "data": [], "source_broken": True,
                    "message": "北向资金分钟数据接口已停更（东方财富 2024 年 8 月更改接口，AkShare 暂未适配）"}

        trade_date = str(df["日期"].iloc[-1])
        data = [
            {
                "time": str(row["时间"]),
                "sh_hk": float(row["沪股通"]) if row["沪股通"] is not None else None,
                "sz_hk": float(row["深股通"]) if row["深股通"] is not None else None,
                "total": float(row["北向资金"]) if row["北向资金"] is not None else None,
            }
            for _, row in df.iterrows()
        ]

        # Detect broken API: all values are 0 on a date that should have trading data
        all_zero = all(r["total"] == 0.0 or r["total"] is None for r in data)
        if all_zero:
            return {
                "date": trade_date,
                "data": [],
                "source_broken": True,
                "message": "北向资金分钟数据接口已停更（东方财富 2024 年 8 月更改接口，AkShare 暂未适配，返回全零）",
            }

        return {"date": trade_date, "data": data, "source_broken": False}
    except Exception as e:
        import logging
        logging.getLogger("big-money").error("intraday fetch failed: %s", e)
        return {"date": None, "data": [], "source_broken": True, "message": f"数据获取失败: {e}"}


@router.post("/refresh")
def refresh_big_money():
    """
    Manually trigger today's northbound capital + ETF share fetch.

    Returns a concrete success/partial/error result so the UI can show whether
    the refresh actually produced current data.
    """
    from app.fetchers.akshare_fetcher import fetch_northbound_today, refresh_recent_etf_shares
    from app.services.big_money_signal import calculate_latest_signal

    def _latest_dates() -> Dict[str, Optional[str]]:
        db = SessionLocal()
        try:
            latest_nb = db.query(NorthboundFlow.date).order_by(NorthboundFlow.date.desc()).first()
            latest_etf = db.query(EtfShareRecord.date).order_by(EtfShareRecord.date.desc()).first()
            latest_signal = db.query(BigMoneySignal.date).order_by(BigMoneySignal.date.desc()).first()
            return {
                "northbound": latest_nb[0].isoformat() if latest_nb else None,
                "etf_shares": latest_etf[0].isoformat() if latest_etf else None,
                "signal": latest_signal[0].isoformat() if latest_signal else None,
            }
        finally:
            db.close()

    today_str = date.today().isoformat()
    before = _latest_dates()
    details: List[Dict[str, Any]] = []

    try:
        r1 = fetch_northbound_today()
        after_nb = _latest_dates()["northbound"]
        details.append({
            "key": "northbound",
            "label": "北向资金",
            "status": "success" if after_nb == today_str and r1.get("errors", 0) == 0 else "warning",
            "latest_date": after_nb,
            "result": r1,
            "message": "已更新到今天" if after_nb == today_str else "未更新到今天，可能是数据源未返回当日数据",
        })
    except Exception as e:
        details.append({
            "key": "northbound",
            "label": "北向资金",
            "status": "error",
            "latest_date": before["northbound"],
            "message": f"刷新失败: {e}",
        })

    try:
        r2 = refresh_recent_etf_shares(days=5)
        after_etf = _latest_dates()["etf_shares"]
        details.append({
            "key": "etf_shares",
            "label": "ETF 份额",
            "status": "success" if after_etf and (r2.get("inserted", 0) > 0 or r2.get("updated", 0) > 0) else "warning",
            "latest_date": after_etf,
            "result": r2,
            "message": "已更新到最新可用交易日" if after_etf else "未获得 ETF 份额，上交所 ETF 份额快照可能尚未发布",
        })
    except Exception as e:
        details.append({
            "key": "etf_shares",
            "label": "ETF 份额",
            "status": "error",
            "latest_date": before["etf_shares"],
            "message": f"刷新失败: {e}",
        })

    try:
        signal = calculate_latest_signal()
        after_signal = _latest_dates()["signal"]
        after_etf = _latest_dates()["etf_shares"]
        details.append({
            "key": "signal",
            "label": "托底信号",
            "status": "success" if after_signal and after_signal == after_etf and signal else "warning",
            "latest_date": after_signal,
            "signal_label": signal.get("signal_label") if signal else None,
            "watch_label": signal.get("watch_label") if signal else None,
            "message": "已按最新 ETF 份额日期计算" if after_signal and after_signal == after_etf else "信号按最新 ETF 份额日期计算，尚未到今天",
        })
    except Exception as e:
        details.append({
            "key": "signal",
            "label": "托底信号",
            "status": "error",
            "latest_date": before["signal"],
            "message": f"计算失败: {e}",
        })

    if any(item["status"] == "error" for item in details):
        status = "error"
        message = "刷新失败，部分数据源或信号计算出错"
    elif any(item["status"] == "warning" for item in details):
        status = "partial"
        message = "刷新部分成功：部分数据未更新到今天"
    else:
        status = "success"
        message = "刷新成功：数据已更新到最新可用日期"

    return {
        "status": status,
        "message": message,
        "target_date": today_str,
        "latest_dates": _latest_dates(),
        "details": details,
    }


@router.post("/backfill")
def backfill_big_money(
    northbound_history: bool = Query(default=True),
    etf_days: int = Query(default=730, ge=5, le=730),
):
    """
    Backfill historical data (background):
    - northbound_history=true: import pre-Aug-2024 northbound history from stock_hsgt_hist_em
    - etf_days: backfill ETF shares for last N calendar days
    """
    from app.fetchers.akshare_fetcher import fetch_northbound_history, backfill_etf_shares
    from app.services.big_money_signal import backfill_signals

    def _run():
        import logging
        log = logging.getLogger("big-money")
        if northbound_history:
            r = fetch_northbound_history()
            log.info("northbound history backfill: %s", r)
        r2 = backfill_etf_shares(days=etf_days)
        log.info("etf share backfill (%d days): %s", etf_days, r2)
        r3 = backfill_signals(days=etf_days)
        log.info("big money signal backfill (%d days): %s", etf_days, r3)

    threading.Thread(target=_run, daemon=True, name="big-money-backfill").start()
    return {
        "message": f"历史数据回填已启动（北向资金历史 + ETF份额/托底信号近{etf_days}天），约数分钟后刷新可见数据"
    }
