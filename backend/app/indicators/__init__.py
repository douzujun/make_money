"""Indicators package."""
from app.indicators.base import BaseIndicatorProcessor, IndicatorResult
from app.indicators.registry import (
    register_processor,
    get_processor,
    list_processors,
    create_processor,
)

# Import all indicator implementations to register them
from app.indicators.ma200 import MA200Indicator
from app.indicators.btc_fear_greed import BTCFearGreedIndicator
from app.indicators.cnn_fear_greed import CNNFearGreedIndicator
from app.indicators.volatility_indices import (
    VXNIndicator,
    VXDIndicator,
    OVXIndicator,
    GVZIndicator,
)
from app.indicators.rsi import RSIIndicator

__all__ = [
    "BaseIndicatorProcessor",
    "IndicatorResult",
    "register_processor",
    "get_processor",
    "list_processors",
    "create_processor",
    "MA200Indicator",
    "BTCFearGreedIndicator",
    "VIXIndicator",
    "VXNIndicator",
    "VXDIndicator",
    "OVXIndicator",
    "GVZIndicator",
    "RSIIndicator",
]
