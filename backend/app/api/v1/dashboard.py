"""Investment Dashboard API — GET /api/v1/dashboard/investment."""
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.indicator import Indicator, IndicatorValue

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# ---------------------------------------------------------------------------
# Grade → numeric score mappings
# ---------------------------------------------------------------------------

_MA200_SCORE: Dict[str, int] = {
    "very_low":   5,
    "low":        20,
    "medium_low": 35,
    "medium":     50,
    "medium_high":65,
    "high":       80,
    "very_high":  95,
}

# RSI value is the score directly (0–100), no mapping needed.

# Volatility grade → inverted sentiment score (high vol = fear = low score)
_VOL_SCORE: Dict[str, int] = {
    "calm":     85,
    "low":      68,
    "normal":   50,
    "elevated": 32,
    "fear":     18,
    "panic":    8,
}

_MA200_GRADE_LABEL: Dict[str, str] = {
    "very_low":   "极度低估",
    "low":        "低估",
    "medium_low": "偏低",
    "medium":     "合理",
    "medium_high":"偏高",
    "high":       "高估",
    "very_high":  "极度高估",
}

_VOL_GRADE_LABEL: Dict[str, str] = {
    "calm":     "极度平静",
    "low":      "低波动",
    "normal":   "正常波动",
    "elevated": "波动加剧",
    "fear":     "市场恐慌",
    "panic":    "极度恐慌",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_latest_value(db: Session, template_id: str, asset_id: str) -> Optional[IndicatorValue]:
    """Return the most recent IndicatorValue for the given template+asset pair."""
    indicator = (
        db.query(Indicator)
        .filter(Indicator.template_id == template_id, Indicator.asset_id == asset_id)
        .first()
    )
    if not indicator:
        return None
    return (
        db.query(IndicatorValue)
        .filter(IndicatorValue.indicator_id == indicator.id)
        .order_by(IndicatorValue.date.desc())
        .first()
    )


def _ma200_score_block(iv: Optional[IndicatorValue]) -> Dict[str, Any]:
    if not iv:
        return {"score": None, "grade": None, "grade_label": "暂无数据", "value": None, "value_text": None, "date": None}
    score = _MA200_SCORE.get(iv.grade) if iv.grade else None
    return {
        "score": score,
        "grade": iv.grade,
        "grade_label": iv.grade_label or _MA200_GRADE_LABEL.get(iv.grade),
        "value": round(iv.value, 2) if iv.value is not None else None,
        "value_text": iv.value_text,
        "date": iv.date.isoformat() if iv.date else None,
    }


def _rsi_score_block(iv: Optional[IndicatorValue]) -> Dict[str, Any]:
    if not iv:
        return {"score": None, "grade": None, "grade_label": "暂无数据", "value": None, "value_text": None, "date": None}
    score = round(iv.value) if iv.value is not None else None
    return {
        "score": score,
        "grade": iv.grade,
        "grade_label": iv.grade_label,
        "value": round(iv.value, 2) if iv.value is not None else None,
        "value_text": iv.value_text,
        "date": iv.date.isoformat() if iv.date else None,
    }


def _vol_score_block(iv: Optional[IndicatorValue]) -> Dict[str, Any]:
    """Convert a volatility indicator value to an inverted sentiment score."""
    if not iv:
        return {"score": None, "grade": None, "grade_label": "暂无数据", "value": None, "value_text": None, "date": None}
    score = _VOL_SCORE.get(iv.grade) if iv.grade else None
    return {
        "score": score,
        "grade": iv.grade,
        "grade_label": iv.grade_label or _VOL_GRADE_LABEL.get(iv.grade),
        "value": round(iv.value, 2) if iv.value is not None else None,
        "value_text": iv.value_text,
        "date": iv.date.isoformat() if iv.date else None,
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/investment")
def get_investment_dashboard():
    """
    Return long-term score (MA200) + daily score (RSI / volatility) for 4 markets.

    Markets: A股 (000300.SS) · 港股 (^HSI) · 黄金 (GC=F) · 原油 (CL=F)
    """
    db = SessionLocal()
    try:
        markets = [
            {
                "id": "a_shares",
                "name": "A股 沪深300",
                "asset_id": "000300.SS",
                "long_term": _ma200_score_block(_get_latest_value(db, "MA200", "000300.SS")),
                "daily": _rsi_score_block(_get_latest_value(db, "RSI", "000300.SS")),
            },
            {
                "id": "hk_stocks",
                "name": "港股 恒生指数",
                "asset_id": "^HSI",
                "long_term": _ma200_score_block(_get_latest_value(db, "MA200", "^HSI")),
                "daily": _rsi_score_block(_get_latest_value(db, "RSI", "^HSI")),
            },
            {
                "id": "gold",
                "name": "黄金 GC=F",
                "asset_id": "GC=F",
                "long_term": _ma200_score_block(_get_latest_value(db, "MA200", "GC=F")),
                "daily": _vol_score_block(_get_latest_value(db, "GVZ", "^GVZ")),
            },
            {
                "id": "oil",
                "name": "原油 CL=F",
                "asset_id": "CL=F",
                "long_term": _ma200_score_block(_get_latest_value(db, "MA200", "CL=F")),
                "daily": _vol_score_block(_get_latest_value(db, "OVX", "^OVX")),
            },
        ]
        return {"markets": markets}
    finally:
        db.close()
