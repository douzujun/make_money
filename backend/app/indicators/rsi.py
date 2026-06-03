"""RSI Indicator - 相对强弱指数 (14日)."""
from datetime import date, datetime, timedelta
from typing import List, Optional

import pandas as pd

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.price_data import PriceData
from app.indicators.base import BaseIndicatorProcessor, IndicatorResult
from app.indicators.registry import register_processor
from app.indicators.init_targets import ensure_yfinance_asset, ensure_indicator


@register_processor
class RSIIndicator(BaseIndicatorProcessor):
    """
    相对强弱指数 (RSI-14).

    用于判断市场短期超买/超卖状态，辅助择时。
    值域 0–100：RSI 越低越超卖（潜在买入时机），越高越超买（潜在卖出时机）。
    使用 Wilder 平滑法（EWM，与 TradingView 默认一致）。
    """

    name = "RSI"
    display_name = "RSI 相对强弱指数"
    description = "14日相对强弱指数，用于判断短期超买/超卖状态"

    default_params = {
        "period": 14,
        "price_field": "close",
    }

    param_descriptions = {
        "period": "RSI 计算周期（天数）",
        "price_field": "使用的价格字段 (open/high/low/close)",
    }

    output_fields = [
        {"name": "value", "type": "float", "description": "RSI 值 (0–100)"},
        {"name": "value_text", "type": "string", "description": "文本描述", "optional": True},
        {"name": "grade", "type": "string", "description": "档位", "optional": True},
        {"name": "grade_label", "type": "string", "description": "档位标签", "optional": True},
    ]

    grading_config = {
        "grades": [
            {"grade": "extreme_oversold",   "min": 0,   "max": 20,  "label": "极度超卖"},
            {"grade": "oversold",           "min": 20,  "max": 30,  "label": "超卖"},
            {"grade": "weak",               "min": 30,  "max": 45,  "label": "偏弱"},
            {"grade": "neutral",            "min": 45,  "max": 55,  "label": "中性"},
            {"grade": "strong",             "min": 55,  "max": 70,  "label": "偏强"},
            {"grade": "overbought",         "min": 70,  "max": 80,  "label": "超买"},
            {"grade": "extreme_overbought", "min": 80,  "max": 101, "label": "极度超买"},
        ]
    }

    async def calculate(
        self, asset_id: str, start: date, end: date
    ) -> List[IndicatorResult]:
        period = self.params.get("period", 14)
        price_field = self.params.get("price_field", "close")

        # Wilder smoothing needs at least 2*period warmup days
        buffer_days = period * 4 + 30
        data_start = start - timedelta(days=buffer_days)

        db = SessionLocal()
        try:
            prices = (
                db.query(PriceData)
                .filter(
                    PriceData.asset_id == asset_id,
                    PriceData.date >= data_start,
                    PriceData.date <= end,
                    PriceData.interval == "1d",
                )
                .order_by(PriceData.date)
                .all()
            )
        finally:
            db.close()

        if len(prices) < period + 2:
            return []

        df = pd.DataFrame(
            [
                {
                    "date": p.date,
                    "close": p.close,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                }
                for p in prices
            ]
        )
        df.set_index("date", inplace=True)
        df.index = pd.to_datetime(df.index)

        # Wilder smoothing via EWM (com = period - 1)
        delta = df[price_field].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, float("inf"))
        df["rsi"] = 100 - (100 / (1 + rs))

        # Filter to requested range
        df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]

        results = []
        for idx, row in df.iterrows():
            if pd.isna(row["rsi"]):
                continue
            value = round(float(row["rsi"]), 2)
            grading = self.apply_grading(value)
            d = idx.date() if hasattr(idx, "date") else idx
            results.append(
                IndicatorResult(
                    date=d,
                    timestamp=datetime.combine(d, datetime.min.time()),
                    value=value,
                    value_text=f"RSI({period}): {value:.1f}",
                    grade=grading.get("grade"),
                    grade_label=grading.get("grade_label"),
                )
            )
        return results


# ---------------------------------------------------------------------------
# Dashboard markets — RSI targets
# ---------------------------------------------------------------------------

_RSI_TARGETS = [
    {"asset_id": "000300.SS", "name": "沪深300 RSI-14"},
    {"asset_id": "^HSI",      "name": "恒生指数 RSI-14"},
    {"asset_id": "GC=F",      "name": "黄金 RSI-14"},
    {"asset_id": "CL=F",      "name": "WTI原油 RSI-14"},
]

# MA200 also needed for the 4 dashboard markets
_MA200_TARGETS = [
    {"asset_id": "000300.SS", "name": "沪深300 200周均线偏离度"},
    {"asset_id": "^HSI",      "name": "恒生指数 200周均线偏离度"},
    {"asset_id": "GC=F",      "name": "黄金 200周均线偏离度"},
    {"asset_id": "CL=F",      "name": "WTI原油 200周均线偏离度"},
]


def init_dashboard_targets(db: Session) -> int:
    """Ensure assets + RSI/MA200 indicator instances exist for all 4 dashboard markets."""
    created = 0

    for target in _RSI_TARGETS:
        asset = ensure_yfinance_asset(db, asset_id=target["asset_id"], watch=True)
        if not asset:
            continue
        if ensure_indicator(
            db, "RSI", target["asset_id"], target["name"],
            {"period": 14, "price_field": "close"},
        ):
            created += 1

    for target in _MA200_TARGETS:
        asset = ensure_yfinance_asset(db, asset_id=target["asset_id"], watch=True)
        if not asset:
            continue
        if ensure_indicator(
            db, "MA200", target["asset_id"], target["name"],
            {"period": 200, "price_field": "close"},
        ):
            created += 1

    return created
