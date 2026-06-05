"""Portfolio backtest API endpoints."""
import threading
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/backtest", tags=["backtest"])

BACKTEST_ASSETS = [
    {"symbol": "510300", "name": "沪深300ETF", "category": "A股大盘", "since": "2012"},
    {"symbol": "510050", "name": "上证50ETF",  "category": "A股蓝筹", "since": "2004"},
    {"symbol": "510500", "name": "中证500ETF",  "category": "A股中盘", "since": "2013"},
    {"symbol": "159915", "name": "创业板ETF",  "category": "A股成长", "since": "2010"},
    {"symbol": "513100", "name": "纳指ETF",    "category": "海外宽基", "since": "2013"},
    {"symbol": "511010", "name": "国债ETF",    "category": "中债",    "since": "2013"},
    {"symbol": "518880", "name": "黄金ETF华安", "category": "黄金",    "since": "2013"},
    {"symbol": "CASH",   "name": "现金/货币基金", "category": "现金",  "since": "synthetic"},
]

PRESET_SCENARIOS = [
    {
        "id": "balanced",
        "name": "股债平衡",
        "description": "经典 60/40：60% 大盘股 + 40% 国债。最广为人知的长期配置策略，股债负相关对冲波动。",
        "weights": {"510300": 0.60, "511010": 0.40},
    },
    {
        "id": "all_weather",
        "name": "全天候（中国版）",
        "description": "桥水全天候思路：四类资产均衡分散，覆盖繁荣/衰退/通胀/通缩四种经济环境，黄金应对股债双杀极端场景。",
        "weights": {"510300": 0.30, "511010": 0.40, "518880": 0.15, "159915": 0.15},
    },
    {
        "id": "permanent",
        "name": "永久组合",
        "description": "哈里·布朗 1981 年提出：四类资产各 25%，机械再平衡。历史上最大回撤从未超过 20%，极度稳健。",
        "weights": {"510300": 0.25, "510050": 0.25, "511010": 0.25, "518880": 0.25},
    },
    {
        "id": "growth",
        "name": "科技成长",
        "description": "重仓创业板（中国科技/成长股集中地），高风险高回报。债券仅作安全垫，押注中国科技长期增长。",
        "weights": {"159915": 0.60, "510300": 0.20, "511010": 0.20},
    },
    {
        "id": "dividend",
        "name": "红利稳健",
        "description": "上证50蓝筹（工农中建+茅台）为核心，历史分红稳定，配合债券和黄金，五个预设中波动率最低。",
        "weights": {"510050": 0.50, "511010": 0.30, "518880": 0.20},
    },
    {
        "id": "user_target",
        "name": "你的目标框架",
        "description": "基金核心仓 60% + 黄金防守仓 25% + 现金机动仓 15%。A股宽基为核心，海外宽基辅助，行业主题严格限额。",
        "weights": {"510300": 0.25, "510500": 0.10, "513100": 0.15, "159915": 0.10, "518880": 0.25, "CASH": 0.15},
    },
    {
        "id": "user_snapshot_proxy",
        "name": "当前截图代理",
        "description": "按支付宝截图与现金信息粗略映射：黄金、现金偏高，A股宽基偏低，主题/商品用中证500与创业板代理。仅用于方向性回测。",
        "weights": {"510300": 0.01, "510500": 0.10, "159915": 0.11, "513100": 0.07, "518880": 0.26, "CASH": 0.45},
    },
]


class PortfolioConfig(BaseModel):
    weights: Dict[str, float]
    label: Optional[str] = None


class BacktestRequest(BaseModel):
    portfolio_a: PortfolioConfig
    portfolio_b: Optional[PortfolioConfig] = None
    rebalance: str = "1Q"
    start_date: str = "2013-01-01"
    end_date: str = "2026-12-31"


@router.get("/assets")
def get_assets():
    return {"assets": BACKTEST_ASSETS}


@router.get("/presets")
def get_presets():
    return {"presets": PRESET_SCENARIOS}


@router.get("/price-status")
def get_price_status():
    """Return count of cached price rows per ETF."""
    from app.core.database import SessionLocal
    from app.models.backtest import EtfPriceCache

    db = SessionLocal()
    try:
        result = {}
        for asset in BACKTEST_ASSETS:
            if asset["symbol"] == "CASH":
                result[asset["symbol"]] = {"name": asset["name"], "cached_rows": 9999}
                continue
            count = (
                db.query(EtfPriceCache)
                .filter(EtfPriceCache.symbol == asset["symbol"])
                .count()
            )
            result[asset["symbol"]] = {"name": asset["name"], "cached_rows": count}
        return result
    finally:
        db.close()


@router.post("/fetch-prices")
def fetch_prices():
    """Trigger background fetch of ETF price histories used by backtest and signals."""
    from app.fetchers.akshare_fetcher import fetch_all_backtest_etfs

    def _run():
        import logging
        log = logging.getLogger("backtest")
        results = fetch_all_backtest_etfs()
        log.info("backtest price fetch done: %s", results)

    threading.Thread(target=_run, daemon=True, name="backtest-fetch").start()
    return {"message": "ETF 历史净值抓取已在后台启动，首次约需 3–5 分钟，完成后刷新即可运行回测"}


@router.post("/run")
def run_backtest(req: BacktestRequest):
    from app.services.backtest_engine import run_backtest as _run, get_bear_periods

    if req.rebalance not in ("1M", "1Q"):
        raise HTTPException(400, "rebalance 必须是 '1M' 或 '1Q'")

    def _validate(weights: Dict[str, float], name: str):
        total = sum(weights.values())
        if abs(total - 1.0) > 0.05:
            raise HTTPException(400, f"{name} 权重之和为 {total:.2f}，应约为 1.0")

    _validate(req.portfolio_a.weights, "组合A")

    result_a = _run(
        weights=req.portfolio_a.weights,
        rebalance_freq=req.rebalance,
        start_date=req.start_date,
        end_date=req.end_date,
    )

    result_b = None
    if req.portfolio_b:
        _validate(req.portfolio_b.weights, "组合B")
        result_b = _run(
            weights=req.portfolio_b.weights,
            rebalance_freq=req.rebalance,
            start_date=req.start_date,
            end_date=req.end_date,
        )

    bear_periods = get_bear_periods("510300", req.start_date, req.end_date)

    return {
        "portfolio_a": result_a,
        "portfolio_b": result_b,
        "bear_periods": bear_periods,
        "rebalance": req.rebalance,
        "start_date": req.start_date,
        "end_date": req.end_date,
    }
