import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.fetchers.fred_fetcher import FredFetcher


class FredFetcherTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_fred_csv_series(self):
        csv = "observation_date,DTWEXBGS\n2026-01-01,100.1\n2026-01-02,101.2\n"
        response = Mock()
        response.text = csv
        response.raise_for_status.return_value = None

        with patch("app.fetchers.fred_fetcher.requests.get", return_value=response):
            rows = await FredFetcher().fetch_prices("DTWEXBGS", date(2026, 1, 1), date(2026, 1, 2))

        self.assertEqual(2, len(rows))
        self.assertEqual(date(2026, 1, 2), rows[-1]["date"])
        self.assertEqual(101.2, rows[-1]["close"])
        self.assertEqual(rows[-1]["open"], rows[-1]["close"])

    async def test_falls_back_to_dbnomics_when_fred_fails(self):
        fred_error = RuntimeError("fred timeout")
        dbnomics_response = Mock()
        dbnomics_response.json.return_value = {
            "series": {
                "docs": [{
                    "period": ["2026-01-01", "2026-01-02"],
                    "value": [100.1, 101.2],
                }]
            }
        }
        dbnomics_response.raise_for_status.return_value = None

        with patch("app.fetchers.fred_fetcher.requests.get", side_effect=[fred_error, dbnomics_response]):
            rows = await FredFetcher().fetch_prices("DTWEXBGS", date(2026, 1, 1), date(2026, 1, 2))

        self.assertEqual(2, len(rows))
        self.assertEqual(101.2, rows[-1]["close"])


if __name__ == "__main__":
    unittest.main()
