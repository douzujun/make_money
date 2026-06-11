import unittest
from datetime import date
from unittest.mock import patch

from app.fetchers import akshare_fetcher


class BigMoneyEtfRefreshTests(unittest.TestCase):
    def test_refresh_recent_etf_shares_attempts_recent_trading_days(self):
        calls = []

        def fake_fetch(date_str):
            calls.append(date_str)
            if date_str == "2026-06-08":
                return {"inserted": 3, "updated": 0, "errors": 0}
            return {"inserted": 0, "updated": 0, "errors": 1}

        with patch.object(akshare_fetcher, "fetch_etf_shares_for_date", side_effect=fake_fetch):
            result = akshare_fetcher.refresh_recent_etf_shares(days=5, end_date=date(2026, 6, 9))

        self.assertIn("2026-06-09", calls)
        self.assertIn("2026-06-08", calls)
        self.assertNotIn("2026-06-07", calls)
        self.assertNotIn("2026-06-06", calls)
        self.assertEqual(result["inserted"], 3)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["attempted_dates"], ["2026-06-09", "2026-06-08", "2026-06-05"])


if __name__ == "__main__":
    unittest.main()
