"""AkShare fetcher — A-share sector fund flow, supports East Money + 同花顺."""
import logging
from datetime import date
from typing import Dict, List, Literal, Optional, Any

logger = logging.getLogger("fetcher.akshare")

DataSource = Literal["auto", "eastmoney", "ths"]


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if (f != f) else f
    except (TypeError, ValueError):
        return None


# ── 东方财富 (East Money) ─────────────────────────────────────────────────────

def fetch_industry_flow_em() -> List[Dict[str, Any]]:
    """East Money: today's industry sector fund flow."""
    try:
        import akshare as ak
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        today = date.today()
        results = []
        for _, row in df.iterrows():
            name = str(row.get("名称", "")).strip()
            if not name:
                continue

            def _wan(col):
                v = _safe_float(row.get(col))
                return round(v / 10000, 2) if v is not None else None

            results.append({
                "sector_name": name, "sector_type": "industry", "date": today,
                "change_pct": _safe_float(row.get("今日涨跌幅")),
                "net_inflow_main": _wan("今日主力净流入-净额"),
                "net_inflow_main_ratio": _safe_float(row.get("今日主力净流入-净占比")),
                "net_inflow_super_large": _wan("今日超大单净流入-净额"),
                "net_inflow_large": _wan("今日大单净流入-净额"),
                "net_inflow_medium": _wan("今日中单净流入-净额"),
                "net_inflow_small": _wan("今日小单净流入-净额"),
            })
        logger.info("[EM] Fetched %d industry sectors", len(results))
        return results
    except Exception as e:
        logger.warning("[EM] fetch_industry_flow_em failed: %s", e)
        return []


def fetch_concept_flow_em(top_n: int = 20) -> List[Dict[str, Any]]:
    """East Money: today's top concept sectors by net inflow."""
    try:
        import akshare as ak
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="概念资金流")
        today = date.today()
        col = "今日主力净流入-净额"
        if col in df.columns:
            df[col] = df[col].apply(_safe_float)
            df = df.sort_values(col, ascending=False).head(top_n)
        results = []
        for _, row in df.iterrows():
            name = str(row.get("名称", "")).strip()
            if not name:
                continue

            def _wan(c):
                v = _safe_float(row.get(c))
                return round(v / 10000, 2) if v is not None else None

            results.append({
                "sector_name": name, "sector_type": "concept", "date": today,
                "change_pct": _safe_float(row.get("今日涨跌幅")),
                "net_inflow_main": _wan("今日主力净流入-净额"),
                "net_inflow_main_ratio": _safe_float(row.get("今日主力净流入-净占比")),
                "net_inflow_super_large": _wan("今日超大单净流入-净额"),
                "net_inflow_large": _wan("今日大单净流入-净额"),
                "net_inflow_medium": _wan("今日中单净流入-净额"),
                "net_inflow_small": _wan("今日小单净流入-净额"),
            })
        logger.info("[EM] Fetched %d concept sectors (top %d)", len(results), top_n)
        return results
    except Exception as e:
        logger.warning("[EM] fetch_concept_flow_em failed: %s", e)
        return []


# ── 同花顺 (THS / 10jqka) ────────────────────────────────────────────────────
# 净额单位：亿元 → 存入 DB 时转为万元 (×10000)

def fetch_industry_flow_ths() -> List[Dict[str, Any]]:
    """THS: today's industry sector fund flow (90 sectors)."""
    try:
        import akshare as ak
        df = ak.stock_fund_flow_industry(symbol="即时")
        today = date.today()
        results = []
        for _, row in df.iterrows():
            name = str(row.get("行业", "")).strip()
            if not name:
                continue
            net_yi = _safe_float(row.get("净额"))
            results.append({
                "sector_name": name, "sector_type": "industry", "date": today,
                "change_pct": _safe_float(row.get("行业-涨跌幅")),
                # THS 净额单位为亿元，×10000 转万元
                "net_inflow_main": round(net_yi * 10000, 2) if net_yi is not None else None,
                "net_inflow_main_ratio": None,   # THS 无此字段
                "net_inflow_super_large": None,
                "net_inflow_large": None,
                "net_inflow_medium": None,
                "net_inflow_small": None,
            })
        logger.info("[THS] Fetched %d industry sectors", len(results))
        return results
    except Exception as e:
        logger.warning("[THS] fetch_industry_flow_ths failed: %s", e)
        return []


def fetch_concept_flow_ths(top_n: int = 20) -> List[Dict[str, Any]]:
    """THS: today's concept sector fund flow (sorted by net inflow)."""
    try:
        import akshare as ak
        df = ak.stock_fund_flow_concept(symbol="即时")
        today = date.today()
        col = "净额"
        if col in df.columns:
            df[col] = df[col].apply(_safe_float)
            df = df.sort_values(col, ascending=False).head(top_n)
        results = []
        for _, row in df.iterrows():
            name = str(row.get("行业", "")).strip()
            if not name:
                continue
            net_yi = _safe_float(row.get("净额"))
            results.append({
                "sector_name": name, "sector_type": "concept", "date": today,
                "change_pct": _safe_float(row.get("行业-涨跌幅")),
                "net_inflow_main": round(net_yi * 10000, 2) if net_yi is not None else None,
                "net_inflow_main_ratio": None,
                "net_inflow_super_large": None,
                "net_inflow_large": None,
                "net_inflow_medium": None,
                "net_inflow_small": None,
            })
        logger.info("[THS] Fetched %d concept sectors (top %d)", len(results), top_n)
        return results
    except Exception as e:
        logger.warning("[THS] fetch_concept_flow_ths failed: %s", e)
        return []


# ── DB upsert ────────────────────────────────────────────────────────────────

def save_sector_flow(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Upsert sector fund flow records into the database."""
    if not records:
        return {"inserted": 0, "updated": 0, "errors": 0}

    from app.core.database import SessionLocal
    from app.models.sector_flow import SectorFundFlow

    db = SessionLocal()
    inserted = updated = errors = 0
    try:
        for rec in records:
            try:
                existing = (
                    db.query(SectorFundFlow)
                    .filter(
                        SectorFundFlow.date == rec["date"],
                        SectorFundFlow.sector_name == rec["sector_name"],
                        SectorFundFlow.sector_type == rec["sector_type"],
                    )
                    .first()
                )
                if existing:
                    for k, v in rec.items():
                        if k not in ("date", "sector_name", "sector_type"):
                            setattr(existing, k, v)
                    updated += 1
                else:
                    db.add(SectorFundFlow(**rec))
                    inserted += 1
            except Exception as e:
                logger.warning("Failed to upsert %s: %s", rec.get("sector_name"), e)
                errors += 1
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("save_sector_flow commit failed: %s", e)
    finally:
        db.close()

    return {"inserted": inserted, "updated": updated, "errors": errors}


# ── Main job ─────────────────────────────────────────────────────────────────

def run_daily_sector_flow_job(source: DataSource = "auto") -> Dict[str, Any]:
    """
    Fetch industry + concept fund flow and persist to DB.

    source:
      'auto'       — try East Money first, fall back to THS automatically
      'eastmoney'  — East Money only
      'ths'        — 同花顺 only
    """
    logger.info("Starting sector flow job (source=%s)", source)
    results: Dict[str, Any] = {"requested_source": source}

    def _fetch_industry(src: str):
        if src == "ths":
            return fetch_industry_flow_ths(), "ths"
        return fetch_industry_flow_em(), "eastmoney"

    def _fetch_concept(src: str):
        if src == "ths":
            return fetch_concept_flow_ths(), "ths"
        return fetch_concept_flow_em(), "eastmoney"

    # ── Industry ──
    if source == "auto":
        industry_data, actual = fetch_industry_flow_em(), "eastmoney"
        if not industry_data:
            logger.info("East Money failed → falling back to THS")
            industry_data, actual = fetch_industry_flow_ths(), "ths"
    else:
        industry_data, actual = _fetch_industry(source)

    if industry_data:
        stats = save_sector_flow(industry_data)
        results["industry"] = {"source": actual, "fetched": len(industry_data), **stats}
    else:
        results["industry"] = {"source": "none", "fetched": 0, "error": "all sources failed"}
        actual = "none"

    # ── Concept (use same source that succeeded for industry) ──
    if actual == "none":
        results["concept"] = {"source": "none", "fetched": 0, "error": "all sources failed"}
    else:
        concept_data, _ = _fetch_concept(actual)
        if concept_data:
            stats = save_sector_flow(concept_data)
            results["concept"] = {"source": actual, "fetched": len(concept_data), **stats}
        else:
            results["concept"] = {"source": actual, "fetched": 0, "error": "fetch failed"}

    results["actual_source"] = actual
    logger.info("Sector flow job done: %s", results)
    return results


# ── 历史回填（同花顺板块指数 → 涨跌幅历史）────────────────────────────────────

def backfill_sector_history_ths(days: int = 30) -> Dict[str, Any]:
    """
    Backfill historical daily price-change data for all THS industry sectors.

    Uses stock_board_industry_index_ths (OHLCV) to compute daily change_pct.
    net_inflow_main is left None for back-filled days (fund flow data accumulates
    from today onwards via the daily job).

    Returns summary of inserted/updated records.
    """
    import akshare as ak
    from datetime import timedelta

    end_date = date.today()
    start_date = end_date - timedelta(days=days * 2)   # buffer for weekends/holidays

    try:
        sectors_df = ak.stock_board_industry_name_ths()
        sector_names = sectors_df["name"].tolist()
    except Exception as e:
        logger.error("backfill: failed to get sector list: %s", e)
        return {"error": str(e)}

    logger.info("Backfilling %d sectors from %s to %s", len(sector_names), start_date, end_date)

    all_records: List[Dict[str, Any]] = []

    for name in sector_names:
        try:
            df = ak.stock_board_industry_index_ths(
                symbol=name,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            if df.empty:
                continue

            df = df.sort_values("日期").reset_index(drop=True)
            df["日期"] = df["日期"].apply(
                lambda x: x.date() if hasattr(x, "date") else date.fromisoformat(str(x)[:10])
            )

            # Compute daily change_pct from successive close prices
            for i, row in df.iterrows():
                if i == 0:
                    continue  # skip first row (no previous close)
                prev_close = _safe_float(df.at[i - 1, "收盘价"])
                curr_close = _safe_float(row["收盘价"])
                if prev_close and prev_close != 0 and curr_close is not None:
                    chg = round((curr_close - prev_close) / prev_close * 100, 2)
                else:
                    chg = None

                row_date = row["日期"]
                # Only include dates within requested window
                if row_date < (end_date - timedelta(days=days)):
                    continue

                all_records.append({
                    "sector_name": name,
                    "sector_type": "industry",
                    "date": row_date,
                    "change_pct": chg,
                    # Fund flow fields left None — filled by daily job going forward
                    "net_inflow_main": None,
                    "net_inflow_main_ratio": None,
                    "net_inflow_super_large": None,
                    "net_inflow_large": None,
                    "net_inflow_medium": None,
                    "net_inflow_small": None,
                })
        except Exception as e:
            logger.warning("backfill: sector %s failed: %s", name, e)
            continue

    logger.info("Backfill: prepared %d records for %d sectors", len(all_records), len(sector_names))

    if not all_records:
        return {"inserted": 0, "updated": 0, "errors": 0, "sectors": 0}

    stats = save_sector_flow(all_records)
    stats["sectors"] = len(sector_names)
    return stats
def fetch_industry_flow_today():
    return fetch_industry_flow_em()


def fetch_concept_flow_today(top_n: int = 20):
    return fetch_concept_flow_em(top_n=top_n)


# ── Big Money: northbound capital ─────────────────────────────────────────────

def _save_northbound(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Upsert NorthboundFlow records."""
    if not records:
        return {"inserted": 0, "updated": 0, "errors": 0}
    from app.core.database import SessionLocal
    from app.models.big_money import NorthboundFlow
    db = SessionLocal()
    inserted = updated = errors = 0
    try:
        for rec in records:
            try:
                existing = db.query(NorthboundFlow).filter(
                    NorthboundFlow.date == rec["date"],
                    NorthboundFlow.channel == rec["channel"],
                ).first()
                if existing:
                    for k, v in rec.items():
                        setattr(existing, k, v)
                    updated += 1
                else:
                    db.add(NorthboundFlow(**rec))
                    inserted += 1
            except Exception as e:
                logger.warning("northbound upsert error: %s", e)
                errors += 1
        db.commit()
    finally:
        db.close()
    logger.info("Northbound upsert: inserted=%d updated=%d errors=%d", inserted, updated, errors)
    return {"inserted": inserted, "updated": updated, "errors": errors}


def fetch_northbound_history() -> Dict[str, int]:
    """
    Import historical northbound capital from stock_hsgt_hist_em.
    Data is valid up to ~2024-08-16; later rows have NaN financial fields.
    """
    try:
        import akshare as ak
        import pandas as pd
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        df = df[df["当日成交净买额"].notna()].copy()
        df["日期"] = pd.to_datetime(df["日期"]).dt.date
        records = []
        for _, row in df.iterrows():
            records.append({
                "date": row["日期"],
                "channel": "total",
                "net_buy_amount": _safe_float(row.get("当日成交净买额")),
                "net_inflow": _safe_float(row.get("当日资金流入")),
                "balance": _safe_float(row.get("当日余额")),
                "hs300_close": _safe_float(row.get("沪深300")),
                "hs300_change_pct": _safe_float(row.get("沪深300-涨跌幅")),
            })
        logger.info("[Northbound] History: %d valid rows", len(records))
        return _save_northbound(records)
    except Exception as e:
        logger.error("[Northbound] fetch_northbound_history failed: %s", e)
        return {"inserted": 0, "updated": 0, "errors": 1}


def fetch_northbound_today() -> Dict[str, int]:
    """
    Fetch today's northbound capital from stock_hsgt_fund_flow_summary_em.
    Saves 'sh_hk', 'sz_hk', and aggregated 'total' rows.
    """
    try:
        import akshare as ak
        from datetime import date as _date
        df = ak.stock_hsgt_fund_flow_summary_em()
        today = _date.today()
        # Filter northbound only (北向 rows)
        north = df[df["资金方向"] == "北向"].copy()
        if north.empty:
            logger.warning("[Northbound] No 北向 rows in summary today")
            return {"inserted": 0, "updated": 0, "errors": 0}

        channel_map = {"沪股通": "sh_hk", "深股通": "sz_hk"}
        records = []
        total_net_buy = 0.0
        total_inflow = 0.0
        for _, row in north.iterrows():
            board = str(row.get("板块", "")).strip()
            channel = channel_map.get(board, board)
            net_buy = _safe_float(row.get("成交净买额")) or 0.0
            inflow = _safe_float(row.get("资金净流入")) or 0.0
            total_net_buy += net_buy
            total_inflow += inflow
            records.append({
                "date": today,
                "channel": channel,
                "net_buy_amount": _safe_float(row.get("成交净买额")),
                "net_inflow": _safe_float(row.get("资金净流入")),
                "balance": _safe_float(row.get("当日资金余额")),
                "hs300_close": None,
                "hs300_change_pct": _safe_float(row.get("指数涨跌幅")),
            })
        # Aggregate total
        records.append({
            "date": today,
            "channel": "total",
            "net_buy_amount": round(total_net_buy, 4),
            "net_inflow": round(total_inflow, 4),
            "balance": None,
            "hs300_close": None,
            "hs300_change_pct": None,
        })
        logger.info("[Northbound] Today: %d channel rows", len(records))
        return _save_northbound(records)
    except Exception as e:
        logger.error("[Northbound] fetch_northbound_today failed: %s", e)
        return {"inserted": 0, "updated": 0, "errors": 1}


# ── Big Money: ETF share tracking ────────────────────────────────────────────

ETF_TARGETS = {
    "510050": "上证50ETF",
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
}

_SSE_DATE_FORMAT = "%Y%m%d"


def _save_etf_shares(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Upsert EtfShareRecord rows."""
    if not records:
        return {"inserted": 0, "updated": 0, "errors": 0}
    from app.core.database import SessionLocal
    from app.models.big_money import EtfShareRecord
    db = SessionLocal()
    inserted = updated = errors = 0
    try:
        for rec in records:
            try:
                existing = db.query(EtfShareRecord).filter(
                    EtfShareRecord.date == rec["date"],
                    EtfShareRecord.symbol == rec["symbol"],
                ).first()
                if existing:
                    for k, v in rec.items():
                        setattr(existing, k, v)
                    updated += 1
                else:
                    db.add(EtfShareRecord(**rec))
                    inserted += 1
            except Exception as e:
                logger.warning("etf_share upsert error: %s", e)
                errors += 1
        db.commit()
    finally:
        db.close()
    logger.info("ETF share upsert: inserted=%d updated=%d errors=%d", inserted, updated, errors)
    return {"inserted": inserted, "updated": updated, "errors": errors}


def fetch_etf_shares_for_date(date_str: Optional[str] = None) -> Dict[str, int]:
    """
    Fetch ETF share counts for a single date via fund_etf_scale_sse.
    date_str: 'YYYY-MM-DD' or None (defaults to today).
    """
    try:
        import akshare as ak
        from datetime import date as _date
        if date_str:
            target = _date.fromisoformat(date_str)
        else:
            target = _date.today()
        api_date = target.strftime(_SSE_DATE_FORMAT)
        df = ak.fund_etf_scale_sse(date=api_date)
        records = []
        for symbol, name in ETF_TARGETS.items():
            row = df[df["基金代码"].astype(str) == symbol]
            if row.empty:
                logger.warning("[ETFShare] %s not found for %s", symbol, api_date)
                continue
            share_raw = _safe_float(row.iloc[0]["基金份额"])
            # 原始单位为份，转亿份
            share_yi = round(share_raw / 1e8, 4) if share_raw is not None else None
            records.append({
                "date": target,
                "symbol": symbol,
                "name": str(row.iloc[0].get("基金简称", name)).strip() or name,
                "total_share": share_yi,
            })
        logger.info("[ETFShare] %s: %d records", api_date, len(records))
        return _save_etf_shares(records)
    except Exception as e:
        logger.error("[ETFShare] fetch_etf_shares_for_date(%s) failed: %s", date_str, e)
        return {"inserted": 0, "updated": 0, "errors": 1}


def backfill_etf_shares(days: int = 30) -> Dict[str, int]:
    """
    Backfill ETF share records for the last `days` calendar days.
    Skips weekends automatically (fund_etf_scale_sse returns empty for non-trading days).
    """
    from datetime import date as _date, timedelta
    total = {"inserted": 0, "updated": 0, "errors": 0}
    end = _date.today()
    for i in range(days):
        d = end - timedelta(days=i)
        if d.weekday() >= 5:  # skip weekends
            continue
        r = fetch_etf_shares_for_date(d.isoformat())
        for k in total:
            total[k] += r.get(k, 0)
    logger.info("[ETFShare] Backfill %d days done: %s", days, total)
    return total


# ── Backtest ETF price cache ──────────────────────────────────────────────────

BACKTEST_ETFS = {
    "510300": "沪深300ETF",
    "510050": "上证50ETF",
    "510500": "中证500ETF",
    "159915": "创业板ETF",
    "511010": "国债ETF",
    "518880": "黄金ETF华安",
}


def fetch_etf_price_history(symbol: str) -> dict:
    """Fetch full price history for one backtest ETF and upsert into etf_price_cache."""
    import akshare as ak
    import pandas as pd
    from app.core.database import SessionLocal
    from app.models.backtest import EtfPriceCache

    df = ak.fund_etf_fund_info_em(fund=symbol, start_date="20040101", end_date="20500101")
    if df.empty:
        return {"symbol": symbol, "upserted": 0, "total": 0}

    df = df.rename(columns={"净值日期": "date", "单位净值": "nav"})[["date", "nav"]]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date", "nav"])
    df = df[df["nav"] > 0]

    db = SessionLocal()
    try:
        upserted = 0
        for _, row in df.iterrows():
            existing = (
                db.query(EtfPriceCache)
                .filter_by(date=row["date"], symbol=symbol)
                .first()
            )
            if existing:
                existing.nav = float(row["nav"])
            else:
                db.add(EtfPriceCache(date=row["date"], symbol=symbol, nav=float(row["nav"])))
                upserted += 1
        db.commit()
        logger.info("[Backtest] %s: upserted=%d total=%d", symbol, upserted, len(df))
        return {"symbol": symbol, "upserted": upserted, "total": len(df)}
    except Exception as e:
        db.rollback()
        logger.error("[Backtest] %s fetch failed: %s", symbol, e)
        raise
    finally:
        db.close()


def fetch_all_backtest_etfs() -> list:
    """Fetch price history for all 5 backtest ETFs sequentially."""
    results = []
    for symbol in BACKTEST_ETFS:
        try:
            r = fetch_etf_price_history(symbol)
            results.append(r)
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})
    return results
