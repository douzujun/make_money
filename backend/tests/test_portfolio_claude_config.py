import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.v1 import portfolio
from app.core.database import Base
from app.models.big_money import BigMoneySignal
from app.models.portfolio import PortfolioHolding, PortfolioSnapshot
from app.models.price_data import PriceData


class PortfolioClaudeConfigTest(unittest.TestCase):
    def test_saves_and_loads_claude_code_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "local_settings.json"
            with patch.object(portfolio, "LOCAL_SETTINGS_PATH", config_path):
                portfolio.save_claude_review_config(
                    portfolio.ClaudeReviewConfigIn(path="/tmp/custom-ducc")
                )

                self.assertEqual("/tmp/custom-ducc", portfolio._claude_review_bin())

    def test_empty_path_restores_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "local_settings.json"
            with patch.object(portfolio, "LOCAL_SETTINGS_PATH", config_path):
                portfolio.save_claude_review_config(
                    portfolio.ClaudeReviewConfigIn(path="/tmp/custom-ducc")
                )
                portfolio.save_claude_review_config(
                    portfolio.ClaudeReviewConfigIn(path="")
                )

                self.assertEqual(portfolio.DEFAULT_DUCC_BIN, portfolio._claude_review_bin())

    def test_config_payload_reports_executable_status(self):
        with tempfile.NamedTemporaryFile() as handle:
            os.chmod(handle.name, 0o755)
            payload = portfolio._claude_review_config_payload(handle.name)

        self.assertTrue(payload["exists"])
        self.assertTrue(payload["executable"])
        self.assertEqual("ready", payload["status"])


class PortfolioClaudeEvidenceTest(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.engine = create_engine(f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.estimate_patch = patch.object(
            portfolio,
            "_fetch_fund_estimate",
            lambda code: {"available": False, "source": "test", "message": "mocked"},
        )
        self.estimate_patch.start()

    def tearDown(self):
        self.estimate_patch.stop()
        self.engine.dispose()
        os.remove(self.db_path)

    def make_snapshot(self, session):
        snapshot = PortfolioSnapshot(
            snapshot_date=date.today(),
            money_fund_amount=100000,
            cash_amount=50000,
            usable_cash_amount=20000,
            reserve_floor_amount=80000,
        )
        snapshot.holdings = [
            PortfolioHolding(
                fund_code="000218",
                name="国泰黄金ETF联接A",
                amount=90000,
                profit_amount=1000,
                profit_rate=1.2,
                bucket="gold",
            ),
            PortfolioHolding(
                fund_code="022501",
                name="国泰中证煤炭ETF联接E",
                amount=5000,
                profit_amount=-100,
                profit_rate=-2,
                bucket="commodities",
                flow_sector_name="煤炭开采加工",
            ),
        ]
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return snapshot

    def add_prices(self, session, asset_id, closes):
        start = date.today() - timedelta(days=len(closes))
        for idx, close in enumerate(closes):
            day = start + timedelta(days=idx + 1)
            session.add(PriceData(
                asset_id=asset_id,
                timestamp=day,
                date=day,
                interval="1d",
                close=close,
                source="test",
            ))
        session.commit()

    def test_build_review_evidence_includes_quality_and_fund_details(self):
        session = self.Session()
        try:
            snapshot = self.make_snapshot(session)
            self.add_prices(session, "GC=F", [100 + idx for idx in range(25)])
            self.add_prices(session, "DTWEXBGS", [110 - idx * 0.2 for idx in range(25)])
            session.add(BigMoneySignal(
                date=date.today(),
                signal="neutral",
                signal_label="中性",
                watch_signal="none",
                watch_label="无观察信号",
                confidence="medium",
                data_quality="ok",
            ))
            session.commit()

            recommendation = portfolio._recommend(snapshot, session)
            evidence = portfolio._build_review_evidence(recommendation, snapshot, session)

            self.assertIn("data_quality", evidence)
            self.assertIn("fund_recommendations", evidence)
            self.assertIn("market_confirmations", evidence)
            self.assertEqual("DTWEXBGS", evidence["macro_price_evidence"]["dollar"]["asset_id"])
            self.assertLessEqual(len(evidence["fund_recommendations"]), portfolio.MAX_REVIEW_FUNDS)
            self.assertEqual("Claude Code 不允许联网或调用外部工具；只审阅本地证据包。", evidence["limits"]["network_policy"])
        finally:
            session.close()

    def test_parse_review_result_json_and_fallback(self):
        parsed = portfolio._parse_review_result(
            '{"risk_level":"high","trade_amount_adjustment":"pause","can_execute_today":false,"top_risks":[],"action_overrides":[],"missing_data_warnings":[],"summary":"暂停"}',
            {"data_quality": {"overall": "good"}},
        )
        self.assertEqual("high", parsed["risk_level"])
        self.assertFalse(parsed["can_execute_today"])

        fallback = portfolio._parse_review_result("不是 JSON", {"data_quality": {"overall": "poor", "missing": ["x"]}})
        self.assertEqual("high", fallback["risk_level"])
        self.assertEqual("reduce_50", fallback["trade_amount_adjustment"])
        self.assertIn("raw_review", fallback)


if __name__ == "__main__":
    unittest.main()
