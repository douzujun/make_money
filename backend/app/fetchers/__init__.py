"""Fetchers package."""
from app.fetchers.base import BaseFetcher, AssetSearchResult
from app.fetchers.registry import register_fetcher, get_fetcher, list_fetchers

# Import fetchers to register them
from app.fetchers.yfinance_fetcher import YahooFinanceFetcher
from app.fetchers.binance_fetcher import BinanceFetcher
from app.fetchers.fred_fetcher import FredFetcher

__all__ = [
    "BaseFetcher",
    "AssetSearchResult", 
    "register_fetcher",
    "get_fetcher",
    "list_fetchers",
    "YahooFinanceFetcher",
    "BinanceFetcher",
    "FredFetcher",
]
