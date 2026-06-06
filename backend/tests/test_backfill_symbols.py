import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.asset import Asset
from app.services.backfill import get_yfinance_symbol


class BackfillSymbolTest(unittest.TestCase):
    def test_yfinance_uses_source_symbol_when_present(self):
        asset = Asset(
            id="DX-Y.NYB",
            symbol="DXY",
            name="US Dollar Index",
            asset_type="index",
            data_source="yfinance",
            source_symbol="DX-Y.NYB",
        )

        self.assertEqual("DX-Y.NYB", get_yfinance_symbol(asset))

    def test_yfinance_crypto_uses_id_when_source_symbol_missing(self):
        asset = Asset(
            id="BTC-USD",
            symbol="BTC",
            name="Bitcoin",
            asset_type="crypto",
            data_source="yfinance",
            source_symbol="",
        )

        self.assertEqual("BTC-USD", get_yfinance_symbol(asset))


if __name__ == "__main__":
    unittest.main()
