"""Portfolio snapshot and conservative rebalance recommendation API."""
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.asset import Asset
from app.models.big_money import BigMoneySignal
from app.models.portfolio import PortfolioHolding, PortfolioSnapshot
from app.models.price_data import PriceData
from app.models.sector_flow import SectorFundFlow

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

DUCC_BIN = "/Users/douzujun/.comate/baidu-cc/bin/ducc"
INTRADAY_MAX_ACTION = 3000.0
INTRADAY_TIMEOUT = 4
ESTIMATE_CACHE_TTL = 180
_estimate_cache: Dict[str, Dict] = {}

GOLD_ASSET_ID = "GC=F"
DOLLAR_INDEX_ASSET_ID = "DTWEXBGS"
DOLLAR_CONFIRMATION_ASSETS = [
    {"asset_id": "DTWEXBGS", "label": "FRED广义美元指数", "quality": "official_macro"},
    {"asset_id": "DX-Y.NYB", "label": "美元指数现货", "quality": "fallback"},
    {"asset_id": "DX=F", "label": "美元指数期货", "quality": "fallback"},
    {"asset_id": "UUP", "label": "美元指数ETF代理", "quality": "proxy"},
]
GOLD_LOW_WATCH_PCT = 0.18
GOLD_TARGET_LOW_PCT = 0.20
GOLD_TARGET_HIGH_PCT = 0.25
GOLD_WARNING_PCT = 0.28
GOLD_HARD_CAP_PCT = 0.30


TARGET_BUCKETS = {
    "a_share_core": {"name": "A股宽基核心仓", "target": 0.35},
    "overseas_core": {"name": "海外宽基/全球成长", "target": 0.15},
    "gold": {"name": "黄金防守仓", "target": 0.25},
    "cash": {"name": "现金/货币基金", "target": 0.15},
    "commodities": {"name": "商品/资源链", "target": 0.04},
    "themes": {"name": "行业主题仓", "target": 0.06},
    "fragments": {"name": "碎片/待合并仓", "target": 0.0},
}

BUCKET_ALIASES = {
    "a_share_core": "宽基",
    "overseas_core": "海外",
    "gold": "黄金",
    "cash": "现金",
    "commodities": "资源",
    "themes": "主题",
    "fragments": "碎片",
}

FUND_SECTOR_KEYWORDS = [
    {"keywords": ["煤炭"], "sector": "煤炭开采加工"},
    {"keywords": ["软件"], "sector": "软件开发"},
    {"keywords": ["半导体"], "sector": "半导体"},
    {"keywords": ["机器人"], "sector": "机器人"},
    {"keywords": ["新能源", "电池"], "sector": "电池"},
    {"keywords": ["绿色电力", "电力"], "sector": "电力"},
    {"keywords": ["电网"], "sector": "电网设备"},
    {"keywords": ["稀土", "小金属"], "sector": "小金属"},
    {"keywords": ["有色金属", "矿业"], "sector": "工业金属"},
    {"keywords": ["大宗商品", "资源"], "sector": "工业金属"},
    {"keywords": ["消费"], "sector": "消费电子"},
    {"keywords": ["高端装备", "先进制造", "装备制造"], "sector": "专用设备"},
    {"keywords": ["北证50"], "sector": "北证50"},
]

KNOWN_FUND_CODES = {
    "易方达全球成长精选混合(QDII)A": "012920",
    "国泰黄金ETF联接A": "000218",
    "广发纳斯达克100ETF联接(QDII)A": "270042",
    "华安纳斯达克100ETF联接(QDII)A": "040046",
    "国投瑞银白银期货(LOF)C": "019005",
    "鹏华创新未来混合(LOF)C": "501205",
    "方正富邦核心优势混合C": "018816",
    "方正富邦远见成长混合C": "017994",
    "富国全球科技互联网股票(QDII)C": "022184",
    "创金合信兴选产业趋势混合A": "014408",
    "易方达机器人ETF联接A": "020972",
    "富国全球科技互联网股票(QDII)A": "100055",
    "易方达全球成长精选混合(QDII)C": "012922",
    "广发远见智选混合C": "016874",
    "天弘全球高端制造混合(QDII)C": "016665",
    "华夏全球科技先锋混合(QDII)A": "005698",
    "德邦鑫星价值灵活配置混合C": "002112",
    "国富全球科技互联混合(QDII)人民币A": "006373",
    "前海开源沪港深乐享生活灵活配置混合": "004320",
    "广发全球精选股票(QDII)C": "021277",
    "大成纳斯达克100ETF联接(QDII)A": "000834",
    "易方达沪深300ETF联接C": "007339",
    "嘉实中证稀土产业ETF联接C": "011036",
    "国泰中证煤炭ETF联接E": "022501",
    "德邦稳盈增长灵活配置混合C": "018463",
    "华宝中证沪港深新消费指数C": "017435",
    "嘉实新能源新材料股票A": "003984",
    "嘉实北证50成份指数C": "017528",
    "泰信发展主题混合": "290008",
}

KNOWN_PROFITS = {
    "易方达全球成长精选混合(QDII)A": {"profit_amount": 3724.03, "profit_rate": 76.07},
    "国泰黄金ETF联接A": {"profit_amount": 1947.14, "profit_rate": 2.23},
    "广发纳斯达克100ETF联接(QDII)A": {"profit_amount": 1383.09, "profit_rate": 25.35},
    "华安纳斯达克100ETF联接(QDII)A": {"profit_amount": 1213.11, "profit_rate": 19.75},
    "国投瑞银白银期货(LOF)C": {"profit_amount": 784.10, "profit_rate": 49.51},
    "永赢半导体产业智选混合C": {"profit_amount": 416.48, "profit_rate": 26.87},
    "鹏华创新未来混合(LOF)C": {"profit_amount": 201.25, "profit_rate": 4.02},
    "方正富邦核心优势混合C": {"profit_amount": 188.74, "profit_rate": 11.18},
    "方正富邦远见成长混合C": {"profit_amount": 138.31, "profit_rate": 6.92},
    "富国全球科技互联网股票(QDII)C": {"profit_amount": 129.98, "profit_rate": 13.00},
    "上银先进制造混合C": {"profit_amount": 98.06, "profit_rate": 14.01},
    "创金合信兴选产业趋势混合A": {"profit_amount": 49.55, "profit_rate": 1.46},
    "易方达机器人ETF联接A": {"profit_amount": 25.72, "profit_rate": 1.03},
    "富国全球科技互联网股票(QDII)A": {"profit_amount": 17.12, "profit_rate": 3.36},
    "易方达全球成长精选混合(QDII)C": {"profit_amount": 15.56, "profit_rate": 31.13},
    "前海开源高端装备制造灵活配置混合C": {"profit_amount": 10.50, "profit_rate": 21.01},
    "广发远见智选混合C": {"profit_amount": 1.92, "profit_rate": 1.03},
    "天弘全球高端制造混合(QDII)C": {"profit_amount": 1.68, "profit_rate": 16.77},
    "华夏全球科技先锋混合(QDII)A": {"profit_amount": 1.43, "profit_rate": 14.29},
    "德邦鑫星价值灵活配置混合C": {"profit_amount": 1.38, "profit_rate": 13.76},
    "国富全球科技互联混合(QDII)人民币A": {"profit_amount": 1.04, "profit_rate": 10.40},
    "前海开源沪港深乐享生活灵活配置混合": {"profit_amount": 0.89, "profit_rate": 8.95},
    "广发全球精选股票(QDII)C": {"profit_amount": 0.65, "profit_rate": 6.51},
    "大成纳斯达克100ETF联接(QDII)A": {"profit_amount": 0.32, "profit_rate": 3.17},
    "易方达沪深300ETF联接C": {"profit_amount": 0.00, "profit_rate": 0.00},
    "上银资源精选混合C": {"profit_amount": -2.19, "profit_rate": -1.10},
    "永赢高端装备智选混合C": {"profit_amount": -2.60, "profit_rate": -9.90},
    "英大策略优选混合C": {"profit_amount": -13.86, "profit_rate": -2.77},
    "嘉实中证稀土产业ETF联接C": {"profit_amount": -21.64, "profit_rate": -0.42},
    "国泰中证煤炭ETF联接E": {"profit_amount": -29.86, "profit_rate": -1.99},
    "德邦稳盈增长灵活配置混合C": {"profit_amount": -31.87, "profit_rate": -12.75},
    "华夏中证电网设备主题ETF联接C": {"profit_amount": -32.69, "profit_rate": -3.27},
    "天弘国证绿色电力指数C": {"profit_amount": -45.61, "profit_rate": -3.04},
    "华泰柏瑞战略新兴产业混合C": {"profit_amount": -68.64, "profit_rate": -7.63},
    "华泰柏瑞南方东英恒生科技指数ETF联接": {"profit_amount": -142.97, "profit_rate": -17.87},
    "华宝中证沪港深新消费指数C": {"profit_amount": -177.71, "profit_rate": -22.21},
    "嘉实新能源新材料股票A": {"profit_amount": -191.00, "profit_rate": -3.35},
    "嘉实北证50成份指数C": {"profit_amount": -278.74, "profit_rate": -7.96},
    "招商中证大宗商品股票指数(LOF)": {"profit_amount": -424.90, "profit_rate": -2.42},
    "鹏华新能源汽车主题混合C": {"profit_amount": -518.11, "profit_rate": -15.70},
    "泰信发展主题混合": {"profit_amount": -559.91, "profit_rate": -17.50},
    "招商中证全指软件ETF联接C": {"profit_amount": -758.85, "profit_rate": -22.32},
    "华安中证有色金属矿业主题ETF联接A": {"profit_amount": -1255.59, "profit_rate": -10.35},
}

DEFAULT_HOLDINGS = [
    {"name": "易方达全球成长精选混合(QDII)A", "amount": 8659.84, "bucket": "overseas_core"},
    {"name": "国泰黄金ETF联接A", "amount": 89139.19, "bucket": "gold"},
    {"name": "广发纳斯达克100ETF联接(QDII)A", "amount": 6860.15, "bucket": "overseas_core"},
    {"name": "华安纳斯达克100ETF联接(QDII)A", "amount": 7375.09, "bucket": "overseas_core"},
    {"name": "国投瑞银白银期货(LOF)C", "amount": 2367.74, "bucket": "commodities"},
    {"name": "永赢半导体产业智选混合C", "amount": 1966.48, "bucket": "themes"},
    {"name": "鹏华创新未来混合(LOF)C", "amount": 5201.25, "bucket": "themes"},
    {"name": "方正富邦核心优势混合C", "amount": 2376.25, "bucket": "themes"},
    {"name": "方正富邦远见成长混合C", "amount": 2138.31, "bucket": "themes"},
    {"name": "富国全球科技互联网股票(QDII)C", "amount": 1129.98, "bucket": "overseas_core"},
    {"name": "上银先进制造混合C", "amount": 798.06, "bucket": "themes"},
    {"name": "创金合信兴选产业趋势混合A", "amount": 3449.55, "bucket": "themes"},
    {"name": "易方达机器人ETF联接A", "amount": 2525.72, "bucket": "themes"},
    {"name": "富国全球科技互联网股票(QDII)A", "amount": 727.12, "bucket": "overseas_core"},
    {"name": "易方达全球成长精选混合(QDII)C", "amount": 65.56, "bucket": "fragments"},
    {"name": "前海开源高端装备制造灵活配置混合C", "amount": 60.50, "bucket": "fragments"},
    {"name": "广发远见智选混合C", "amount": 188.94, "bucket": "fragments"},
    {"name": "天弘全球高端制造混合(QDII)C", "amount": 11.68, "bucket": "fragments"},
    {"name": "华夏全球科技先锋混合(QDII)A", "amount": 11.43, "bucket": "fragments"},
    {"name": "德邦鑫星价值灵活配置混合C", "amount": 11.38, "bucket": "fragments"},
    {"name": "国富全球科技互联混合(QDII)人民币A", "amount": 11.04, "bucket": "fragments"},
    {"name": "前海开源沪港深乐享生活灵活配置混合", "amount": 10.89, "bucket": "fragments"},
    {"name": "广发全球精选股票(QDII)C", "amount": 10.65, "bucket": "fragments"},
    {"name": "大成纳斯达克100ETF联接(QDII)A", "amount": 30.32, "bucket": "fragments"},
    {"name": "易方达沪深300ETF联接C", "amount": 10.00, "bucket": "a_share_core"},
    {"name": "上银资源精选混合C", "amount": 197.81, "bucket": "commodities"},
    {"name": "永赢高端装备智选混合C", "amount": 405.46, "bucket": "themes"},
    {"name": "英大策略优选混合C", "amount": 986.14, "bucket": "themes"},
    {"name": "嘉实中证稀土产业ETF联接C", "amount": 5077.19, "bucket": "commodities"},
    {"name": "国泰中证煤炭ETF联接E", "amount": 1470.14, "bucket": "commodities"},
    {"name": "德邦稳盈增长灵活配置混合C", "amount": 218.13, "bucket": "themes"},
    {"name": "华夏中证电网设备主题ETF联接C", "amount": 967.31, "bucket": "themes"},
    {"name": "天弘国证绿色电力指数C", "amount": 1454.39, "bucket": "themes"},
    {"name": "华泰柏瑞战略新兴产业混合C", "amount": 831.36, "bucket": "themes"},
    {"name": "华泰柏瑞南方东英恒生科技指数ETF联接", "amount": 657.03, "bucket": "overseas_core"},
    {"name": "华宝中证沪港深新消费指数C", "amount": 622.29, "bucket": "themes"},
    {"name": "嘉实新能源新材料股票A", "amount": 5504.31, "bucket": "themes"},
    {"name": "嘉实北证50成份指数C", "amount": 3221.26, "bucket": "a_share_core"},
    {"name": "招商中证大宗商品股票指数(LOF)", "amount": 17123.03, "bucket": "commodities"},
    {"name": "鹏华新能源汽车主题混合C", "amount": 2781.89, "bucket": "themes"},
    {"name": "泰信发展主题混合", "amount": 2640.09, "bucket": "themes"},
    {"name": "招商中证全指软件ETF联接C", "amount": 2641.15, "bucket": "themes"},
    {"name": "华安中证有色金属矿业主题ETF联接A", "amount": 10872.21, "bucket": "commodities"},
]


class HoldingIn(BaseModel):
    fund_code: Optional[str] = None
    name: str
    amount: float = Field(ge=0)
    profit_amount: Optional[float] = None
    profit_rate: Optional[float] = None
    bucket: str
    flow_sector_name: Optional[str] = None
    note: Optional[str] = None


class SnapshotIn(BaseModel):
    snapshot_date: date
    money_fund_amount: float = Field(ge=0)
    cash_amount: float = Field(ge=0)
    usable_cash_amount: float = Field(ge=0)
    reserve_floor_amount: float = Field(default=80000, ge=0)
    note: Optional[str] = None
    holdings: List[HoldingIn]


def _snapshot_payload(snapshot: PortfolioSnapshot) -> Dict:
    return {
        "id": snapshot.id,
        "snapshot_date": snapshot.snapshot_date.isoformat(),
        "money_fund_amount": snapshot.money_fund_amount,
        "cash_amount": snapshot.cash_amount,
        "usable_cash_amount": snapshot.usable_cash_amount,
        "reserve_floor_amount": snapshot.reserve_floor_amount,
        "note": snapshot.note,
        "holdings": [
            {
                "id": h.id,
                "fund_code": _normalise_fund_code(h.fund_code or KNOWN_FUND_CODES.get(h.name)),
                "name": h.name,
                "amount": h.amount,
                "profit_amount": h.profit_amount if h.profit_amount is not None else KNOWN_PROFITS.get(h.name, {}).get("profit_amount"),
                "profit_rate": h.profit_rate if h.profit_rate is not None else KNOWN_PROFITS.get(h.name, {}).get("profit_rate"),
                "bucket": h.bucket,
                "flow_sector_name": h.flow_sector_name,
                "note": h.note,
            }
            for h in sorted(snapshot.holdings, key=lambda item: item.amount, reverse=True)
        ],
    }


def _ensure_snapshot(db: Session) -> PortfolioSnapshot:
    latest = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.snapshot_date.desc(), PortfolioSnapshot.id.desc())
        .first()
    )
    if latest:
        return latest

    snapshot = PortfolioSnapshot(
        snapshot_date=date.today(),
        money_fund_amount=100000,
        cash_amount=50000,
        usable_cash_amount=20000,
        reserve_floor_amount=80000,
        note="初始化自支付宝截图快照",
    )
    snapshot.holdings = [
        PortfolioHolding(
            fund_code=h.get("fund_code") or KNOWN_FUND_CODES.get(h["name"]),
            name=h["name"],
            amount=h["amount"],
            profit_amount=h.get("profit_amount", KNOWN_PROFITS.get(h["name"], {}).get("profit_amount")),
            profit_rate=h.get("profit_rate", KNOWN_PROFITS.get(h["name"], {}).get("profit_rate")),
            bucket=h["bucket"],
            flow_sector_name=h.get("flow_sector_name"),
        )
        for h in DEFAULT_HOLDINGS
    ]
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _bucket_rows(snapshot: PortfolioSnapshot) -> List[Dict]:
    bucket_amounts = {key: 0.0 for key in TARGET_BUCKETS}
    for holding in snapshot.holdings:
        bucket_amounts.setdefault(holding.bucket, 0.0)
        bucket_amounts[holding.bucket] += holding.amount
    bucket_amounts["cash"] = snapshot.money_fund_amount + snapshot.cash_amount

    total_assets = sum(bucket_amounts.values())
    rows = []
    for key, meta in TARGET_BUCKETS.items():
        amount = bucket_amounts.get(key, 0.0)
        target = meta["target"]
        pct = amount / total_assets if total_assets else 0.0
        diff_amount = amount - total_assets * target
        rows.append({
            "bucket": key,
            "name": meta["name"],
            "short": BUCKET_ALIASES[key],
            "amount": round(amount, 2),
            "pct": round(pct, 4),
            "target": target,
            "diff_amount": round(diff_amount, 2),
            "diff_pct": round(pct - target, 4),
        })
    return rows


def _cash_budget(snapshot: PortfolioSnapshot) -> float:
    movable_money_fund = max(0.0, snapshot.money_fund_amount - snapshot.reserve_floor_amount)
    return max(0.0, min(snapshot.usable_cash_amount, movable_money_fund + snapshot.cash_amount))


def _normalise_fund_code(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    digits = re.sub(r"\D", "", code)
    if not digits:
        return None
    return digits.zfill(6)[-6:]


def _fetch_fund_estimate(code: Optional[str]) -> Dict:
    fund_code = _normalise_fund_code(code)
    if not fund_code:
        return {"available": False, "source": "eastmoney_fundgz", "message": "未填写基金代码"}

    cached = _estimate_cache.get(fund_code)
    now = time.time()
    if cached and now - cached["fetched_at"] < ESTIMATE_CACHE_TTL:
        return cached["payload"]

    url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js?rt={int(now * 1000)}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Referer": "https://fund.eastmoney.com/",
                "User-Agent": "Mozilla/5.0",
            },
        )
        raw = urllib.request.urlopen(req, timeout=INTRADAY_TIMEOUT).read().decode("utf-8")
        match = re.search(r"jsonpgz\((.*)\);?", raw)
        if not match:
            raise ValueError("估值接口返回格式异常")
        data = json.loads(match.group(1))
        estimate_change_pct = float(data["gszzl"]) if data.get("gszzl") not in (None, "") else None
        payload = {
            "available": True,
            "source": "eastmoney_fundgz",
            "fund_code": data.get("fundcode") or fund_code,
            "name": data.get("name"),
            "nav_date": data.get("jzrq"),
            "nav": float(data["dwjz"]) if data.get("dwjz") not in (None, "") else None,
            "estimate_nav": float(data["gsz"]) if data.get("gsz") not in (None, "") else None,
            "estimate_change_pct": estimate_change_pct,
            "estimate_time": data.get("gztime"),
            "message": "盘中估值仅作观察修正，不作为真实净值",
        }
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        payload = {
            "available": False,
            "source": "eastmoney_fundgz",
            "fund_code": fund_code,
            "message": f"估值不可用: {exc}",
        }

    _estimate_cache[fund_code] = {"fetched_at": now, "payload": payload}
    return payload


def _estimate_modifier(bucket: str, estimate_pct: Optional[float], bucket_action: Optional[Dict]) -> Dict:
    if estimate_pct is None:
        return {"factor": 0.0, "label": "无估值修正", "reason": "未取得盘中估值"}
    if bucket_action and bucket_action["type"] == "add":
        if estimate_pct <= -2:
            return {"factor": 0.15, "label": "小额加仓观察", "reason": "所属资产桶低配，盘中估值回撤超过 2%"}
        if estimate_pct >= 2:
            return {"factor": -0.10, "label": "暂停追高", "reason": "所属资产桶低配但盘中涨幅较大，避免追涨"}
    if bucket_action and bucket_action["type"] == "trim":
        if estimate_pct >= 2:
            return {"factor": 0.15, "label": "减仓窗口", "reason": "所属资产桶超配，盘中估值上涨，适合小额兑现"}
        if estimate_pct <= -2:
            return {"factor": -0.10, "label": "不杀跌", "reason": "所属资产桶超配但盘中下跌，减仓等待反弹或盘后确认"}
    if bucket == "gold" and estimate_pct >= 1.5:
        return {"factor": -0.10, "label": "黄金不追高", "reason": "黄金接近目标仓位，盘中上涨时不追加"}
    return {"factor": 0.0, "label": "观察", "reason": "盘中估值未触发小额修正"}


def _profit_modifier(profit_amount: Optional[float], profit_rate: Optional[float], action_type: str) -> Dict:
    if profit_amount is None and profit_rate is None:
        return {"factor": 0.0, "label": "无收益修正", "reason": "未录入持有收益金额/收益率"}
    rate = profit_rate if profit_rate is not None else 0.0
    amount = profit_amount if profit_amount is not None else 0.0
    if action_type == "intraday_trim_watch":
        if rate >= 20 or amount >= 3000:
            return {"factor": 0.20, "label": "浮盈兑现优先", "reason": "持有浮盈较厚，超配资产更适合分批落袋"}
        if rate <= -10 or amount <= -2000:
            return {"factor": -0.20, "label": "避免亏损杀跌", "reason": "当前浮亏较大，减仓等待反弹或盘后风险确认"}
    if action_type == "intraday_add_watch":
        if rate <= -15 or amount <= -2000:
            return {"factor": -0.15, "label": "亏损仓谨慎补", "reason": "当前浮亏较大，盘中加仓降为更小试探"}
        if rate >= 30 or amount >= 5000:
            return {"factor": -0.10, "label": "高浮盈不追", "reason": "已有浮盈垫，盘中不追高加仓"}
    if action_type == "clear_watch" and amount > 0:
        return {"factor": 0.0, "label": "盈利碎片可清", "reason": "碎片仓已有浮盈，清理心理阻力较低"}
    return {"factor": 0.0, "label": "收益中性", "reason": "收益状态未触发金额修正"}


def _latest_big_money_confirmation(db: Session) -> Dict[str, Any]:
    row = (
        db.query(BigMoneySignal)
        .order_by(BigMoneySignal.date.desc(), BigMoneySignal.id.desc())
        .first()
    )
    if not row:
        return {
            "status": "unavailable",
            "label": "托底数据缺失",
            "factor": 0.0,
            "date": None,
            "summary": "暂无国家队ETF份额/大资金托底信号，宽基加减仓只按仓位偏离处理。",
            "evidence": {},
        }

    caution = row.signal in ("reduce", "support_fading") or row.watch_signal == "watch_reduce"
    supportive = row.signal == "accumulate" or row.watch_signal == "watch_accumulate"
    if caution:
        status = "caution"
        factor = -0.25 if row.signal in ("reduce", "support_fading") else -0.15
        label = row.signal_label if row.signal != "neutral" else row.watch_label
        summary = "宽基托底减弱或出现减仓观察，低配宽基只给更小金额/等待确认。"
    elif supportive:
        status = "supportive"
        factor = 0.15 if row.signal == "accumulate" else 0.08
        label = row.signal_label if row.signal != "neutral" else row.watch_label
        summary = "宽基ETF份额显示托底/加仓观察，可支持低配宽基的小额补仓。"
    else:
        status = "neutral"
        factor = 0.0
        label = row.signal_label
        summary = "托底信号中性，不改变组合仓位主逻辑。"

    evidence = row.evidence or {}
    return {
        "status": status,
        "label": label,
        "factor": factor,
        "date": row.date.isoformat(),
        "summary": summary,
        "evidence": {
            "basket_delta_share": row.basket_delta_share,
            "estimated_amount": row.estimated_amount,
            "z_score": row.z_score,
            "market_drawdown_20": row.market_drawdown_20,
            "confidence": row.confidence,
            "data_quality": row.data_quality,
            "explanation": evidence.get("explanation"),
        },
    }


def _price_history(db: Session, asset_id: str, limit: int = 60) -> List[PriceData]:
    rows = (
        db.query(PriceData)
        .filter(PriceData.asset_id == asset_id, PriceData.interval == "1d")
        .order_by(PriceData.date.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def _select_dollar_history(db: Session, limit: int = 20) -> Dict[str, Any]:
    candidates = []
    for item in DOLLAR_CONFIRMATION_ASSETS:
        rows = _price_history(db, item["asset_id"], limit)
        candidate = {**item, "rows": rows, "days": len(rows)}
        candidates.append(candidate)
        if len(rows) >= 6:
            return candidate
    return candidates[0] if candidates else {
        "asset_id": DOLLAR_INDEX_ASSET_ID,
        "label": "美元指数现货",
        "quality": "missing",
        "rows": [],
        "days": 0,
    }


def _gold_macro_confirmation(db: Session) -> Dict[str, Any]:
    gold_rows = _price_history(db, GOLD_ASSET_ID, 40)
    dollar_candidate = _select_dollar_history(db, 20)
    dollar_rows = dollar_candidate["rows"]
    base = {
        "factor": 0.0,
        "operation_permission": "manual_confirm",
        "permission_label": "人工确认",
        "sector_name": None,
    }
    if len(gold_rows) < 20:
        return {
            **base,
            "status": "unavailable",
            "label": "黄金价格数据缺失",
            "date": None,
            "summary": "黄金仓位占比较高，当前缺少至少20个交易日金价数据；禁止自动加仓，只能人工确认。",
            "evidence": {
                "gold_asset_id": GOLD_ASSET_ID,
                "dollar_asset_id": dollar_candidate["asset_id"],
                "dollar_source_label": dollar_candidate["label"],
                "dollar_data_quality": "missing" if len(dollar_rows) < 6 else dollar_candidate["quality"],
                "gold_days": len(gold_rows),
                "dollar_days": len(dollar_rows),
            },
        }

    latest_gold = gold_rows[-1]
    ma20 = sum(row.close for row in gold_rows[-20:]) / 20
    gold_dev = ((latest_gold.close - ma20) / ma20) * 100 if ma20 else 0.0
    gold_trend_5d = (
        ((latest_gold.close - gold_rows[-6].close) / gold_rows[-6].close) * 100
        if len(gold_rows) >= 6 and gold_rows[-6].close
        else None
    )

    evidence = {
        "gold_asset_id": GOLD_ASSET_ID,
        "dollar_asset_id": dollar_candidate["asset_id"],
        "dollar_source_label": dollar_candidate["label"],
        "dollar_data_quality": "missing" if len(dollar_rows) < 6 else dollar_candidate["quality"],
        "gold_date": latest_gold.date.isoformat(),
        "gold_close": round(latest_gold.close, 4),
        "gold_ma20": round(ma20, 4),
        "gold_ma20_deviation_pct": round(gold_dev, 2),
        "gold_trend_5d_pct": round(gold_trend_5d, 2) if gold_trend_5d is not None else None,
        "gold_days": len(gold_rows),
        "dollar_days": len(dollar_rows),
    }

    if len(dollar_rows) < 6:
        return {
            **base,
            "status": "neutral",
            "label": "黄金宏观信号不完整",
            "date": latest_gold.date.isoformat(),
            "summary": "已接入金价20日均线偏离度，但FRED/DBnomics广义美元指数、DXY现货/期货和UUP代理均缺失或样本不足；黄金操作权限保持人工确认，不自动加仓。",
            "evidence": evidence,
        }

    latest_dollar = dollar_rows[-1]
    dollar_trend_5d = ((latest_dollar.close - dollar_rows[-6].close) / dollar_rows[-6].close) * 100
    evidence.update({
        "dollar_date": latest_dollar.date.isoformat(),
        "dollar_close": round(latest_dollar.close, 4),
        "dollar_trend_5d_pct": round(dollar_trend_5d, 2),
    })

    gold_above_ma = gold_dev >= 1.0
    gold_below_ma = gold_dev <= -1.0
    dollar_weaker = dollar_trend_5d <= -0.5
    dollar_stronger = dollar_trend_5d >= 0.5
    if gold_above_ma and dollar_weaker:
        status = "supportive"
        label = "黄金加仓观察"
        factor = 0.06
        summary = "金价高于20日均线且美元指数走弱，黄金防守仓信号偏正；因仓位已接近目标，仅允许人工确认后小额观察。"
    elif gold_below_ma and dollar_stronger:
        status = "caution"
        label = "黄金减仓观察"
        factor = -0.08
        summary = "金价跌破20日均线且美元指数走强，黄金仓位进入减仓观察；避免杀跌，需人工确认后分批处理。"
    else:
        status = "neutral"
        label = "黄金持有确认"
        factor = 0.0
        summary = "金价20日均线与美元指数信号未形成同向确认，黄金仓位以持有和人工确认优先。"

    return {
        **base,
        "status": status,
        "label": label,
        "factor": factor,
        "date": max(latest_gold.date, latest_dollar.date).isoformat(),
        "summary": summary,
        "evidence": evidence,
    }


def _gold_rebound_trim_trigger(confirmation: Dict[str, Any]) -> bool:
    ev = confirmation.get("evidence") or {}
    gold_dev = ev.get("gold_ma20_deviation_pct")
    dollar_trend = ev.get("dollar_trend_5d_pct")
    gold_trend = ev.get("gold_trend_5d_pct")
    return (
        gold_dev is not None
        and dollar_trend is not None
        and gold_dev >= 3.0
        and dollar_trend >= 0.5
        and (gold_trend is None or gold_trend >= 0)
    )


def _gold_position_action(
    row: Dict[str, Any],
    total_assets: float,
    daily_add_cap: float,
    daily_trim_cap: float,
    confirmation: Dict[str, Any],
) -> Dict[str, Any]:
    pct = row["pct"]
    target_amount = total_assets * GOLD_TARGET_HIGH_PCT
    excess_to_target = max(0.0, row["amount"] - target_amount)
    low_gap = max(0.0, total_assets * GOLD_TARGET_LOW_PCT - row["amount"])
    supportive = confirmation.get("status") == "supportive"
    caution = confirmation.get("status") == "caution"
    rebound_trim = _gold_rebound_trim_trigger(confirmation)

    if pct > GOLD_HARD_CAP_PCT:
        amount = min(daily_trim_cap, max(1000.0, excess_to_target * 0.50), 5000.0)
        return {
            "type": "trim",
            "bucket": "gold",
            "target_name": "黄金防守仓",
            "amount": round(amount, -2),
            "priority": 2,
            "reason": f"黄金当前 {pct * 100:.1f}%，超过30%硬上限，只讨论分批降仓。",
            "execution": "硬风控减仓：不看多加仓；优先把黄金仓位分批降回25%附近，单日不超过5000元。",
        }

    if pct >= GOLD_WARNING_PCT:
        if caution or rebound_trim:
            amount = min(daily_trim_cap, max(1000.0, excess_to_target * 0.35), 5000.0)
            return {
                "type": "trim",
                "bucket": "gold",
                "target_name": "黄金防守仓",
                "amount": round(amount, -2),
                "priority": 3,
                "reason": f"黄金当前 {pct * 100:.1f}%，高于28%警戒上限，且宏观/反弹窗口允许风控减仓。",
                "execution": "警戒减仓：只在反弹或宏观转弱时小额执行，避免单日大跌时杀跌。",
            }
        return {
            "type": "trim_watch",
            "bucket": "gold",
            "target_name": "黄金防守仓",
            "amount": 0,
            "priority": 3,
            "reason": f"黄金当前 {pct * 100:.1f}%，高于28%警戒上限，但尚未出现量化减仓窗口。",
            "execution": "减仓观察：等待金价反弹且美元转强，或宏观信号转弱后再分批降仓；不杀跌。",
        }

    if pct >= GOLD_TARGET_HIGH_PCT:
        if caution or rebound_trim:
            amount = min(daily_trim_cap, max(1000.0, excess_to_target * 0.25), 3000.0)
            return {
                "type": "trim",
                "bucket": "gold",
                "target_name": "黄金防守仓",
                "amount": round(amount, -2),
                "priority": 4,
                "reason": f"黄金当前 {pct * 100:.1f}%，高于25%目标上沿，且出现减仓观察触发。",
                "execution": "小额减仓：只在反弹窗口或宏观转弱时执行，单日不超过3000元。",
            }
        return {
            "type": "hold",
            "bucket": "gold",
            "target_name": "黄金防守仓",
            "amount": 0,
            "priority": 4,
            "reason": f"黄金当前 {pct * 100:.1f}%，高于25%目标上沿。",
            "execution": "不再主动加仓；以持有和人工确认为主，等待仓位回到20%-25%区间或出现减仓窗口。",
        }

    if pct < GOLD_LOW_WATCH_PCT:
        if supportive and daily_add_cap > 0:
            amount = min(daily_add_cap, max(1000.0, low_gap * 0.25), 3000.0)
            return {
                "type": "add",
                "bucket": "gold",
                "target_name": "黄金防守仓",
                "amount": round(amount, -2),
                "priority": 4,
                "reason": f"黄金当前 {pct * 100:.1f}%，低于18%低配观察线，且金价/美元形成双确认。",
                "execution": "小额加仓观察：只补低配缺口的20%-25%，单日不超过3000元，仍需人工确认。",
            }
        return {
            "type": "add_watch",
            "bucket": "gold",
            "target_name": "黄金防守仓",
            "amount": 0,
            "priority": 4,
            "reason": f"黄金当前 {pct * 100:.1f}%，低于18%低配观察线。",
            "execution": "宏观未确认，不补仓；等待金价趋势和美元趋势至少双确认后再小额执行。",
        }

    return {
        "type": "hold",
        "bucket": "gold",
        "target_name": "黄金防守仓",
        "amount": 0,
        "priority": 4,
        "reason": f"黄金当前 {pct * 100:.1f}%，处于20%-25%目标管理区附近。",
        "execution": "持有为主；黄金模块服务仓位上限/下限管理，不做短线预测。",
    }


def _normalise_sector_name(sector_name: Optional[str]) -> Optional[str]:
    if not sector_name:
        return None
    value = sector_name.strip()
    return value or None


def _sector_exists(sector_name: str, db: Session) -> bool:
    return bool(
        db.query(SectorFundFlow.id)
        .filter(SectorFundFlow.sector_type == "industry", SectorFundFlow.sector_name == sector_name)
        .first()
    )


def _match_sector_name(fund_name: str, db: Session) -> Optional[str]:
    for item in FUND_SECTOR_KEYWORDS:
        if any(keyword in fund_name for keyword in item["keywords"]):
            wanted = item["sector"]
            return wanted if _sector_exists(wanted, db) else None
    return None


def _build_sector_signal(row: SectorFundFlow, history: List[SectorFundFlow]) -> Dict[str, Any]:
    recent3_flow = sum(item.net_inflow_main or 0 for item in history[:3])
    recent5_flow = sum(item.net_inflow_main or 0 for item in history[:5])
    inflow_days_5 = sum(1 for item in history[:5] if (item.net_inflow_main or 0) > 0)
    negative_flow_days_3 = sum(1 for item in history[:3] if item.net_inflow_main is not None and item.net_inflow_main < 0)
    change_3d = sum(item.change_pct or 0 for item in history[:3])
    flow_yi = (row.net_inflow_main or 0) / 10000

    score = 50
    score += max(min(flow_yi * 2, 18), -18)
    score += (inflow_days_5 - 2.5) * 6
    score += max(min(change_3d * 2, 12), -12)
    if recent3_flow > 0:
        score += 8
    elif recent3_flow < 0:
        score -= 8
    score = max(0, min(100, round(score)))

    if score >= 65:
        status = "supportive"
        factor = 0.12
        label = "行业资金流支持"
        summary = "最新主力净流入和短线延续性偏强，可支持原本低配/回补动作。"
    elif score <= 35:
        status = "caution"
        factor = -0.20
        label = "行业资金流转弱"
        summary = "最新主力净流出或短线走弱，相关基金加仓应降级，减仓优先级提高。"
    else:
        status = "neutral"
        factor = 0.0
        label = "行业资金流中性"
        summary = "资金流没有形成明确确认，不改变仓位主逻辑。"

    return {
        "status": status,
        "label": label,
        "factor": factor,
        "date": row.date.isoformat(),
        "summary": summary,
        "sector_name": row.sector_name,
        "evidence": {
            "latest_change_pct": row.change_pct,
            "latest_net_inflow_main": row.net_inflow_main,
            "latest_net_inflow_yi": round(flow_yi, 2),
            "latest_net_inflow_main_ratio": row.net_inflow_main_ratio,
            "recent_3d_flow_yi": round(recent3_flow / 10000, 2),
            "recent_5d_flow_yi": round(recent5_flow / 10000, 2),
            "inflow_days_5": inflow_days_5,
            "negative_flow_days_3": negative_flow_days_3,
            "change_3d": round(change_3d, 2),
            "score": score,
        },
    }


def _sector_confirmation_for_fund(
    fund_name: str,
    bucket: str,
    db: Session,
    manual_sector_name: Optional[str] = None,
) -> Dict[str, Any]:
    if bucket == "gold":
        return _gold_macro_confirmation(db)
    if bucket in ("gold", "overseas_core", "fragments"):
        return {
            "status": "not_applicable",
            "label": "不适用A股资金流",
            "factor": 0.0,
            "date": None,
            "sector_name": None,
            "summary": "该资产主要看黄金/海外市场或碎片整理，A股板块资金流不作为确认因子。",
            "evidence": {},
        }

    manual = _normalise_sector_name(manual_sector_name)
    if manual and not _sector_exists(manual, db):
        return {
            "status": "unavailable",
            "label": "手动行业无数据",
            "factor": 0.0,
            "date": None,
            "sector_name": manual,
            "summary": "已手动选择行业，但板块资金流数据库中暂无该行业记录。",
            "evidence": {},
        }
    sector_name = manual or _match_sector_name(fund_name, db)
    if not sector_name:
        return {
            "status": "unavailable",
            "label": "未匹配行业",
            "factor": 0.0,
            "date": None,
            "sector_name": None,
            "summary": "基金名称未能高置信匹配到行业资金流，暂不做资金流修正。",
            "evidence": {},
        }

    latest_date = (
        db.query(SectorFundFlow.date)
        .filter(SectorFundFlow.sector_type == "industry", SectorFundFlow.sector_name == sector_name)
        .order_by(SectorFundFlow.date.desc())
        .first()
    )
    if not latest_date:
        return {
            "status": "unavailable",
            "label": "行业资金流缺失",
            "factor": 0.0,
            "date": None,
            "sector_name": sector_name,
            "summary": "已匹配行业，但数据库没有可用资金流记录。",
            "evidence": {},
        }

    rows = (
        db.query(SectorFundFlow)
        .filter(
            SectorFundFlow.sector_type == "industry",
            SectorFundFlow.sector_name == sector_name,
            SectorFundFlow.date <= latest_date[0],
            SectorFundFlow.date >= latest_date[0] - timedelta(days=14),
        )
        .order_by(SectorFundFlow.date.desc())
        .limit(5)
        .all()
    )
    if not rows:
        return {
            "status": "unavailable",
            "label": "行业资金流缺失",
            "factor": 0.0,
            "date": None,
            "sector_name": sector_name,
            "summary": "已匹配行业，但近期资金流记录不足。",
            "evidence": {},
        }
    return _build_sector_signal(rows[0], rows)


def _dedupe_sector_confirmations(confirmations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rank = {"caution": 3, "supportive": 2, "neutral": 1}
    by_sector: Dict[str, Dict[str, Any]] = {}
    for item in confirmations:
        sector_name = item.get("sector_name")
        if not sector_name:
            continue
        current = by_sector.get(sector_name)
        if not current:
            by_sector[sector_name] = item
            continue
        item_rank = rank.get(item.get("status"), 0)
        current_rank = rank.get(current.get("status"), 0)
        item_flow = abs(item.get("evidence", {}).get("latest_net_inflow_yi") or 0)
        current_flow = abs(current.get("evidence", {}).get("latest_net_inflow_yi") or 0)
        if (item_rank, item_flow) > (current_rank, current_flow):
            by_sector[sector_name] = item
    return list(by_sector.values())


def _top_sector_evidence(confirmation: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = confirmation.get("evidence") or {}
    top = evidence.get("top_sectors")
    return top if isinstance(top, list) else []


def _has_rebound_trim_trigger(confirmation: Dict[str, Any]) -> bool:
    """反弹减仓：主要行业当日涨幅 >= 1.5%，且主力净流入转为非负。"""
    for item in _top_sector_evidence(confirmation):
        ev = item.get("evidence") or {}
        change = ev.get("latest_change_pct")
        flow = ev.get("latest_net_inflow_yi")
        if change is not None and flow is not None and change >= 1.5 and flow >= 0:
            return True
    return False


def _has_risk_trim_trigger(confirmation: Dict[str, Any]) -> bool:
    """风控减仓：桶级仍偏弱，且主要行业主力净流入仍为负。"""
    if confirmation.get("status") != "caution":
        return False
    for item in _top_sector_evidence(confirmation):
        flow = (item.get("evidence") or {}).get("latest_net_inflow_yi")
        if flow is not None and flow < 0:
            return True
    return False


def _risk_trim_multiplier(confirmation: Dict[str, Any]) -> Dict[str, Any]:
    top = _top_sector_evidence(confirmation)
    if not top:
        return {"multiplier": 0.0, "label": "风控证据不足"}

    kill_drop = False
    sustained_weak = False
    extreme_weak = False
    for item in top:
        ev = item.get("evidence") or {}
        latest_change = ev.get("latest_change_pct")
        change_3d = ev.get("change_3d")
        latest_flow = ev.get("latest_net_inflow_yi")
        recent3_flow = ev.get("recent_3d_flow_yi")
        negative_days = ev.get("negative_flow_days_3") or 0

        if (latest_change is not None and latest_change <= -1.5) or (change_3d is not None and change_3d <= -5):
            kill_drop = True
        if negative_days >= 3 or ((recent3_flow or 0) < 0 and (latest_flow or 0) < 0):
            sustained_weak = True
        if (latest_flow or 0) <= -3 and (recent3_flow or 0) <= -6:
            extreme_weak = True

    if kill_drop:
        return {
            "multiplier": 0.35,
            "label": "杀跌刹车",
            "reason": "资金流偏弱但价格已明显杀跌，当日只允许 35% 小额风控，避免卖在低位。",
        }
    if extreme_weak:
        return {
            "multiplier": 0.80,
            "label": "极端弱势升档",
            "reason": "主要行业最新与近3日资金流均大幅为负，且未触发杀跌刹车，执行 80% 风控减仓。",
        }
    if sustained_weak:
        return {
            "multiplier": 0.75,
            "label": "连续弱势升档",
            "reason": "主要行业近3个有效资金流日持续偏弱，且未触发杀跌刹车，执行 75% 风控减仓。",
        }
    return {
        "multiplier": 0.60,
        "label": "普通风控减仓",
        "reason": "行业资金流偏弱但未形成连续弱势升档，执行 60% 小额风控减仓。",
    }


def _bucket_market_confirmations(snapshot: PortfolioSnapshot, db: Session) -> Dict[str, Dict[str, Any]]:
    big_money = _latest_big_money_confirmation(db)
    result: Dict[str, Dict[str, Any]] = {
        "a_share_core": big_money,
        "gold": _gold_macro_confirmation(db),
        "overseas_core": {
            "status": "not_applicable",
            "label": "海外独立确认",
            "factor": 0.0,
            "date": None,
            "summary": "海外/QDII仓位不使用A股资金流确认，后续应接入纳指、汇率和海外风险偏好。",
            "evidence": {},
        },
        "fragments": {
            "status": "not_applicable",
            "label": "碎片整理",
            "factor": 0.0,
            "date": None,
            "summary": "碎片仓主要按金额和策略清晰度整理，不用资金流放大交易。",
            "evidence": {},
        },
    }

    for bucket in ("themes", "commodities"):
        confirmations = [
            _sector_confirmation_for_fund(h.name, h.bucket, db, h.flow_sector_name)
            for h in snapshot.holdings
            if h.bucket == bucket
        ]
        actionable = _dedupe_sector_confirmations([
            c for c in confirmations if c["status"] in ("supportive", "caution", "neutral")
        ])
        if not actionable:
            result[bucket] = {
                "status": "unavailable",
                "label": "行业证据不足",
                "factor": 0.0,
                "date": None,
                "summary": "该资产桶内基金暂未匹配到足够行业资金流证据，只按仓位偏离处理。",
                "evidence": {},
            }
            continue

        caution_count = sum(1 for c in actionable if c["status"] == "caution")
        supportive_count = sum(1 for c in actionable if c["status"] == "supportive")
        top = sorted(
            actionable,
            key=lambda c: abs(c.get("evidence", {}).get("latest_net_inflow_yi") or 0),
            reverse=True,
        )[:4]
        if caution_count > supportive_count:
            status = "caution"
            factor = -0.18
            label = "桶内行业偏弱"
            summary = "桶内多个行业资金流转弱，相关加仓降级，减仓动作更容易执行。"
        elif supportive_count > caution_count:
            status = "supportive"
            factor = 0.10
            label = "桶内行业偏强"
            summary = "桶内多个行业资金流偏强，可支持原本低配的相关动作。"
        else:
            status = "neutral"
            factor = 0.0
            label = "桶内行业分歧"
            summary = "桶内行业资金流有分歧，不放大交易金额。"

        result[bucket] = {
            "status": status,
            "label": label,
            "factor": factor,
            "date": top[0]["date"] if top else None,
            "summary": summary,
            "evidence": {
                "supportive_count": supportive_count,
                "caution_count": caution_count,
                "matched_count": len(actionable),
                "top_sectors": top,
            },
        }
    return result


def _apply_market_to_action(action: Dict, confirmation: Optional[Dict[str, Any]]) -> Dict:
    if not confirmation:
        return action
    if action.get("bucket") == "gold":
        adjusted = dict(action)
        adjusted["raw_amount"] = round(float(action["amount"]), 2)
        adjusted["market_confirmation"] = confirmation
        return adjusted
    adjusted = dict(action)
    factor = confirmation.get("factor", 0.0) or 0.0
    original = float(action["amount"])
    adjusted_amount = original
    if action["type"] == "add":
        if confirmation["status"] == "caution":
            adjusted["type"] = "add_watch"
            adjusted["amount"] = 0
            adjusted["reason"] = f"{action['reason']} 但市场确认偏弱，取消当日加仓执行。"
            adjusted["execution"] = "不执行当日加仓；仅保留为观察，等待托底/行业资金流转中性或转强后再恢复小额加仓。"
        elif confirmation["status"] == "supportive":
            adjusted_amount = original * (1 + factor)
            adjusted["execution"] = f"{action['execution']} 市场确认支持，但仍不突破单日预算。"
        else:
            adjusted_amount = original * (1 + factor)
    elif action["type"] == "trim":
        if confirmation["status"] == "caution":
            if _has_risk_trim_trigger(confirmation):
                trim_rule = _risk_trim_multiplier(confirmation)
                adjusted_amount = original * trim_rule["multiplier"]
                adjusted["execution"] = f"风控减仓触发：{trim_rule['label']}。{trim_rule['reason']}"
            else:
                adjusted["type"] = "trim_watch"
                adjusted["amount"] = 0
                adjusted["reason"] = f"{action['reason']} 但尚未满足量化减仓触发条件。"
                adjusted["execution"] = "减仓观察：等待反弹减仓触发（当日涨幅 >= 1.5% 且主力净流入 >= 0）或风控减仓触发后再执行。"
        elif confirmation["status"] == "supportive":
            if _has_rebound_trim_trigger(confirmation):
                adjusted_amount = original * 0.75
                adjusted["execution"] = "反弹减仓触发：当日涨幅 >= 1.5% 且主力净流入 >= 0；资金流仍有支撑，减仓金额按原建议的 75% 控制。"
            else:
                adjusted["type"] = "trim_watch"
                adjusted["amount"] = 0
                adjusted["reason"] = f"{action['reason']} 但资金流仍有支撑，未满足反弹减仓触发条件。"
                adjusted["execution"] = "减仓观察：等待反弹减仓触发（当日涨幅 >= 1.5% 且主力净流入 >= 0）后再执行，避免卖在短线修复前。"
        else:
            adjusted["execution"] = "中性减仓：资产桶超配且资金流无明确支撑/恶化，按慢调仓金额执行。"

    if action["type"] in ("add", "trim") and adjusted["type"] not in ("add_watch", "trim_watch"):
        adjusted["amount"] = round(max(0, adjusted_amount), -2)
    adjusted["raw_amount"] = round(original, 2)
    adjusted["market_confirmation"] = confirmation
    return adjusted


def _fund_recommendations(snapshot: PortfolioSnapshot, actions: List[Dict], db: Session) -> List[Dict]:
    bucket_actions = {
        action["bucket"]: action
        for action in actions
        if action["type"] in ("add", "trim")
    }
    bucket_totals: Dict[str, float] = {}
    for holding in snapshot.holdings:
        bucket_totals[holding.bucket] = bucket_totals.get(holding.bucket, 0.0) + holding.amount

    result = []
    for holding in sorted(snapshot.holdings, key=lambda item: item.amount, reverse=True):
        fund_code = _normalise_fund_code(holding.fund_code or KNOWN_FUND_CODES.get(holding.name))
        estimate = _fetch_fund_estimate(fund_code)
        bucket_action = bucket_actions.get(holding.bucket)
        base_type = "hold"
        base_amount = 0.0
        reason = "资产桶未触发主动作，盘中仅观察。"

        if holding.amount < 1000:
            base_type = "clear_watch"
            base_amount = holding.amount
            reason = "金额低于 1000 元，符合碎片仓清理规则。"
        elif bucket_action:
            total = max(bucket_totals.get(holding.bucket, 0.0), 1.0)
            share = holding.amount / total
            base_amount = min(INTRADAY_MAX_ACTION, max(300.0, bucket_action["amount"] * share))
            base_type = "intraday_add_watch" if bucket_action["type"] == "add" else "intraday_trim_watch"
            reason = f"继承资产桶动作：{bucket_action['target_name']} {bucket_action['amount']:.0f} 元。"

        estimate_pct = estimate.get("estimate_change_pct") if estimate.get("available") else None
        modifier = _estimate_modifier(holding.bucket, estimate_pct, bucket_action)
        market_confirmation = (
            bucket_action.get("market_confirmation")
            if bucket_action and holding.bucket == "a_share_core"
            else _sector_confirmation_for_fund(holding.name, holding.bucket, db, holding.flow_sector_name)
        )
        profit_amount = holding.profit_amount if holding.profit_amount is not None else KNOWN_PROFITS.get(holding.name, {}).get("profit_amount")
        profit_rate = holding.profit_rate if holding.profit_rate is not None else KNOWN_PROFITS.get(holding.name, {}).get("profit_rate")
        profit_mod = _profit_modifier(profit_amount, profit_rate, base_type)
        final_amount = base_amount
        if base_amount > 0 and base_type != "clear_watch":
            confirmation_factor = 0.0 if market_confirmation.get("operation_permission") == "manual_confirm" else (market_confirmation.get("factor", 0.0) or 0.0)
            final_amount = max(0.0, min(
                INTRADAY_MAX_ACTION,
                base_amount * (1 + modifier["factor"] + profit_mod["factor"] + confirmation_factor),
            ))
        if modifier["factor"] < 0 and base_type.startswith("intraday_add"):
            final_amount = min(final_amount, 1000.0)
        if profit_mod["factor"] < 0 and base_type.startswith("intraday_add"):
            final_amount = min(final_amount, 1000.0)
        if market_confirmation["status"] == "caution" and base_type.startswith("intraday_add"):
            final_amount = min(final_amount, 800.0)
        if market_confirmation["status"] == "supportive" and base_type.startswith("intraday_trim"):
            final_amount = min(final_amount, max(500.0, base_amount * 0.75))

        result.append({
            "fund_code": fund_code,
            "name": holding.name,
            "bucket": holding.bucket,
            "amount": round(holding.amount, 2),
            "profit_amount": profit_amount,
            "profit_rate": profit_rate,
            "flow_sector_name": holding.flow_sector_name,
            "recommendation": base_type,
            "recommendation_label": {
                "hold": "持有观察",
                "clear_watch": "清仓观察",
                "intraday_add_watch": "盘中小额加仓观察",
                "intraday_trim_watch": "盘中小额减仓观察",
            }.get(base_type, base_type),
            "suggested_amount": round(final_amount, 2),
            "intraday_cap": INTRADAY_MAX_ACTION,
            "reason": reason,
            "estimate_modifier": modifier,
            "profit_modifier": profit_mod,
            "market_confirmation": market_confirmation,
            "estimate": estimate,
            "data_note": "盘中估值、持有收益、板块资金流只影响 0-3000 元观察动作；1-2 万主动作需盘后净值与市场信号确认。",
        })
    return result


def _recommend(snapshot: PortfolioSnapshot, db: Session) -> Dict:
    rows = _bucket_rows(snapshot)
    row_map = {row["bucket"]: row for row in rows}
    total_assets = sum(row["amount"] for row in rows)
    cash_budget = _cash_budget(snapshot)
    daily_add_cap = min(cash_budget, 20000.0)
    daily_trim_cap = min(total_assets * 0.02, 8000.0)
    slow_factor = 0.25
    market_confirmations = _bucket_market_confirmations(snapshot, db)

    actions = []

    a_core = row_map["a_share_core"]
    if a_core["diff_amount"] < -total_assets * 0.05 and daily_add_cap > 0:
        amount = min(daily_add_cap, abs(a_core["diff_amount"]) * slow_factor)
        actions.append({
            "type": "add",
            "bucket": "a_share_core",
            "target_name": "沪深300/中证500宽基",
            "amount": round(max(1000, amount), -2),
            "priority": 1,
            "reason": f"A股宽基当前 {a_core['pct'] * 100:.1f}%，目标 {a_core['target'] * 100:.0f}%，低配明显。",
            "execution": "分 1-3 次执行；当天只用可动用资金，不动 8 万货币基金底线。",
        })

    for bucket in ("commodities", "themes"):
        row = row_map[bucket]
        if row["diff_amount"] > total_assets * 0.02:
            amount = min(daily_trim_cap, row["diff_amount"] * slow_factor)
            actions.append({
                "type": "trim",
                "bucket": bucket,
                "target_name": row["name"],
                "amount": round(max(1000, amount), -2),
                "priority": 2 if bucket == "commodities" else 3,
                "reason": f"{row['name']} 当前 {row['pct'] * 100:.1f}%，高于目标 {row['target'] * 100:.0f}%。",
                "execution": "不追着杀跌；仅在反弹减仓触发（当日涨幅 >= 1.5% 且主力净流入 >= 0）或风控减仓触发后执行。",
            })

    gold = row_map["gold"]
    actions.append(_gold_position_action(
        gold,
        total_assets,
        daily_add_cap,
        daily_trim_cap,
        market_confirmations.get("gold", {}),
    ))

    fragment_holdings = [
        h for h in snapshot.holdings
        if h.bucket == "fragments" or h.amount < 1000
    ]
    for h in sorted(fragment_holdings, key=lambda item: item.amount)[:8]:
        if h.amount < 1000:
            action_type = "clear"
            amount = h.amount
            reason = "金额低于 1000 元，允许作为碎片仓清理，降低持仓噪音。"
        elif h.amount < 5000:
            action_type = "merge_watch"
            amount = min(h.amount * 0.5, 1000)
            reason = "1000-5000 元区间，只给合并/减仓观察，不直接清仓。"
        else:
            continue
        actions.append({
            "type": action_type,
            "bucket": h.bucket,
            "target_name": h.name,
            "amount": round(amount, 2),
            "priority": 5,
            "reason": reason,
            "execution": "可在下一次手动整理持仓时执行，避免过多小仓位分散注意力。",
        })

    actions = [
        _apply_market_to_action(action, market_confirmations.get(action["bucket"]))
        for action in actions
    ]
    actions = sorted(actions, key=lambda item: (item["priority"], -item["amount"]))

    has_add = any(a["type"] == "add" for a in actions)
    has_trim = any(a["type"] == "trim" for a in actions)
    if has_add and has_trim:
        signal = "rebalance"
        signal_label = "保守再平衡"
    elif has_add:
        signal = "conservative_add"
        signal_label = "保守加仓"
    elif has_trim:
        signal = "trim_watch"
        signal_label = "减仓观察"
    else:
        signal = "hold"
        signal_label = "观望"

    return {
        "snapshot": _snapshot_payload(snapshot),
        "total_assets": round(total_assets, 2),
        "cash_budget": round(cash_budget, 2),
        "daily_add_cap": round(daily_add_cap, 2),
        "daily_trim_cap": round(daily_trim_cap, 2),
        "signal": signal,
        "signal_label": signal_label,
        "policy": {
            "style": "稳健慢调仓",
            "slow_factor": slow_factor,
            "clear_below": 1000,
            "merge_watch_below": 5000,
            "daily_add_cap": 20000,
            "single_theme_rebalance_pct": "1%-2%",
        },
        "bucket_rows": rows,
        "market_confirmations": market_confirmations,
        "actions": actions,
        "fund_recommendations": _fund_recommendations(snapshot, actions, db),
        "formula": "建议金额 = 目标偏离金额 × 25%慢调仓系数，再由大资金动向/行业资金流作确认或降级，并受可动用现金、单日加仓上限、单日减仓上限和清仓阈值约束。",
        "intraday_policy": {
            "source": "eastmoney_fundgz",
            "max_action": INTRADAY_MAX_ACTION,
            "role": "盘中估值只作观察修正，不直接触发大额买卖。",
        },
    }


def _sector_options(db: Session) -> List[str]:
    rows = (
        db.query(SectorFundFlow.sector_name)
        .filter(SectorFundFlow.sector_type == "industry")
        .distinct()
        .order_by(SectorFundFlow.sector_name)
        .all()
    )
    return [row[0] for row in rows if row[0]]


def _build_review_prompt(recommendation: Dict) -> str:
    compact = {
        "total_assets": recommendation["total_assets"],
        "cash_budget": recommendation["cash_budget"],
        "signal_label": recommendation["signal_label"],
        "policy": recommendation["policy"],
        "bucket_rows": recommendation["bucket_rows"],
        "actions": recommendation["actions"][:10],
        "formula": recommendation["formula"],
    }
    return (
        "你是投资组合风控审阅员。请审阅下面由公式引擎生成的稳健慢调仓建议。"
        "不要输出具体基金标的买卖建议，不要替代公式引擎下指令。"
        "请只输出：1）三点主要风险；2）三点改进建议；3）是否需要降低当天交易金额。"
        "要求中文、简洁、可执行。\n\n"
        + json.dumps(compact, ensure_ascii=False, indent=2)
    )


@router.get("/latest")
def latest_snapshot(db: Session = Depends(get_db)):
    snapshot = _ensure_snapshot(db)
    result = _recommend(snapshot, db)
    result["sector_options"] = _sector_options(db)
    return result


@router.post("/snapshots")
def save_snapshot(payload: SnapshotIn, db: Session = Depends(get_db)):
    invalid = [h.bucket for h in payload.holdings if h.bucket not in TARGET_BUCKETS or h.bucket == "cash"]
    if invalid:
        raise HTTPException(400, f"未知或不可用于基金持仓的资产桶: {sorted(set(invalid))}")

    snapshot = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.snapshot_date == payload.snapshot_date)
        .first()
    )
    if not snapshot:
        snapshot = PortfolioSnapshot(snapshot_date=payload.snapshot_date)
        db.add(snapshot)

    snapshot.money_fund_amount = payload.money_fund_amount
    snapshot.cash_amount = payload.cash_amount
    snapshot.usable_cash_amount = payload.usable_cash_amount
    snapshot.reserve_floor_amount = payload.reserve_floor_amount
    snapshot.note = payload.note
    snapshot.holdings = [
        PortfolioHolding(
            fund_code=_normalise_fund_code(h.fund_code or KNOWN_FUND_CODES.get(h.name)),
            name=h.name,
            amount=h.amount,
            profit_amount=h.profit_amount if h.profit_amount is not None else KNOWN_PROFITS.get(h.name, {}).get("profit_amount"),
            profit_rate=h.profit_rate if h.profit_rate is not None else KNOWN_PROFITS.get(h.name, {}).get("profit_rate"),
            bucket=h.bucket,
            flow_sector_name=_normalise_sector_name(h.flow_sector_name),
            note=h.note,
        )
        for h in payload.holdings
    ]

    db.commit()
    db.refresh(snapshot)
    result = _recommend(snapshot, db)
    result["sector_options"] = _sector_options(db)
    return result


@router.get("/snapshots")
def list_snapshots(limit: int = 30, db: Session = Depends(get_db)):
    snapshots = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.snapshot_date.desc(), PortfolioSnapshot.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "data": [
            {
                "id": s.id,
                "snapshot_date": s.snapshot_date.isoformat(),
                "money_fund_amount": s.money_fund_amount,
                "cash_amount": s.cash_amount,
                "usable_cash_amount": s.usable_cash_amount,
                "holding_count": len(s.holdings),
            }
            for s in snapshots
        ]
    }


@router.post("/claude-review")
def claude_review(db: Session = Depends(get_db)):
    snapshot = _ensure_snapshot(db)
    recommendation = _recommend(snapshot, db)
    prompt = _build_review_prompt(recommendation)
    try:
        result = subprocess.run(
            [
                DUCC_BIN,
                "--print",
                "--permission-mode",
                "dontAsk",
                "--tools",
                "",
            ],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except FileNotFoundError:
        raise HTTPException(503, "ducc 未找到，无法生成 Claude Code 风控审阅")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Claude Code 风控审阅超时")

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Claude Code 风控审阅失败"
        raise HTTPException(502, detail)

    return {
        "review": result.stdout.strip(),
        "engine_signal": recommendation["signal_label"],
        "note": "Claude Code 仅作为二次风控审阅；最终操作建议仍以公式引擎和你的风险约束为准。",
    }
