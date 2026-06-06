"""FRED / DBnomics macro price fetcher."""
from datetime import date, datetime
from io import StringIO
from typing import List

import pandas as pd
import requests

from app.fetchers.base import AssetSearchResult, BaseFetcher
from app.fetchers.registry import register_fetcher


@register_fetcher
class FredFetcher(BaseFetcher):
    """Fetch macro time series from FRED, falling back to DBnomics FED/H10."""

    name = "fred"
    display_name = "FRED / DBnomics"
    supported_asset_types = ["index", "macro"]

    FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    DBNOMICS_MAP = {
        "DTWEXBGS": "FED/H10/JRXWTFB_N.B",
    }

    async def search(self, keyword: str, limit: int = 20) -> List[AssetSearchResult]:
        if keyword.upper() not in {"DTWEXBGS", "DOLLAR", "USD"}:
            return []
        return [
            AssetSearchResult(
                symbol="DTWEXBGS",
                name="Nominal Broad U.S. Dollar Index",
                asset_type="index",
                exchange="FRED",
                source_symbol="DTWEXBGS",
                extra={"provider": "FRED", "fallback": "DBnomics FED/H10"},
            )
        ][:limit]

    async def fetch_prices(
        self,
        source_symbol: str,
        start: date,
        end: date,
        interval: str = "1d",
    ) -> List[dict]:
        if interval != "1d":
            raise ValueError("FRED fetcher currently supports daily interval only")

        series = source_symbol.upper()
        errors = []
        for fetch in (self._fetch_fred_csv, self._fetch_dbnomics):
            try:
                prices = fetch(series, start, end)
                if prices:
                    return prices
            except Exception as exc:
                errors.append(f"{fetch.__name__}: {exc}")

        raise RuntimeError("; ".join(errors) or f"No macro data fetched for {series}")

    def _fetch_fred_csv(self, series: str, start: date, end: date) -> List[dict]:
        response = requests.get(self.FRED_CSV_URL.format(series=series), timeout=4)
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text))
        if df.empty or series not in df.columns:
            return []

        rows = []
        for _, row in df.iterrows():
            day = pd.to_datetime(row["observation_date"]).date()
            value = row[series]
            if day < start or day > end or pd.isna(value) or value == ".":
                continue
            rows.append(self._price_row(day, float(value)))
        return rows

    def _fetch_dbnomics(self, series: str, start: date, end: date) -> List[dict]:
        dbnomics_code = self.DBNOMICS_MAP.get(series)
        if not dbnomics_code:
            return []
        url = f"https://api.db.nomics.world/v22/series/{dbnomics_code}?observations=1"
        response = requests.get(url, timeout=12)
        response.raise_for_status()
        docs = response.json().get("series", {}).get("docs", [])
        if not docs:
            return []

        periods = docs[0].get("period", [])
        values = docs[0].get("value", [])
        rows = []
        for period, value in zip(periods, values):
            if value is None or value == "NA":
                continue
            day = datetime.strptime(period, "%Y-%m-%d").date()
            if day < start or day > end:
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            rows.append(self._price_row(day, numeric_value))
        return rows

    def _price_row(self, day: date, value: float) -> dict:
        timestamp = datetime.combine(day, datetime.min.time())
        return {
            "timestamp": timestamp,
            "date": day,
            "open": value,
            "high": value,
            "low": value,
            "close": value,
            "volume": 0,
        }
