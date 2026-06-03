"""Big Money Flow API endpoints — northbound capital and ETF share tracking."""
import threading
from datetime import date, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Query, HTTPException

from app.core.database import SessionLocal
from app.models.big_money import NorthboundFlow, EtfShareRecord, BigMoneySignal

router = APIRouter(prefix="/big-money", tags=["big-money"])

# Known Central Huijin public intervention announcements (for frontend annotation)
HUIJIN_EVENTS = [
    {"date": "2023-10-23", "label": "汇金增持公告"},
    {"date": "2024-02-06", "label": "汇金再次增持"},
]


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
    from app.fetchers.akshare_fetcher import fetch_northbound_today, fetch_etf_shares_for_date
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
        r2 = fetch_etf_shares_for_date()
        after_etf = _latest_dates()["etf_shares"]
        details.append({
            "key": "etf_shares",
            "label": "ETF 份额",
            "status": "success" if after_etf == today_str and r2.get("errors", 0) == 0 else "warning",
            "latest_date": after_etf,
            "result": r2,
            "message": "已更新到今天" if after_etf == today_str else "未更新到今天，上交所 ETF 份额快照可能尚未发布",
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
        details.append({
            "key": "signal",
            "label": "托底信号",
            "status": "success" if after_signal == today_str and signal else "warning",
            "latest_date": after_signal,
            "signal_label": signal.get("signal_label") if signal else None,
            "watch_label": signal.get("watch_label") if signal else None,
            "message": "已更新到今天" if after_signal == today_str else "信号按最新 ETF 份额日期计算，尚未到今天",
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
        message = "刷新成功：数据已更新到今天"

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
