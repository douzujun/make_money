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
from app.models.sector_flow import SectorFundFlow


class PortfolioMarketConfirmationsTest(unittest.TestCase):
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

    def make_snapshot(self, holdings):
        session = self.Session()
        snapshot = PortfolioSnapshot(
            snapshot_date=date.today(),
            money_fund_amount=100000,
            cash_amount=50000,
            usable_cash_amount=20000,
            reserve_floor_amount=80000,
        )
        snapshot.holdings = [PortfolioHolding(**item) for item in holdings]
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        return session, snapshot

    def test_big_money_caution_reduces_a_share_add_amount(self):
        session, snapshot = self.make_snapshot([
            {"name": "易方达沪深300ETF联接C", "amount": 10, "bucket": "a_share_core"},
            {"name": "国泰黄金ETF联接A", "amount": 90000, "bucket": "gold"},
            {"name": "招商中证大宗商品股票指数(LOF)", "amount": 40000, "bucket": "commodities"},
        ])
        try:
            session.add(BigMoneySignal(
                date=date.today(),
                signal="support_fading",
                signal_label="托底减弱",
                watch_signal="none",
                watch_label="无观察信号",
                confidence="medium",
                basket_delta_share=-3.2,
                estimated_amount=-18.3,
                z_score=0.5,
                positive_etf_count=0,
                negative_etf_count=2,
                data_quality="complete",
            ))
            session.commit()

            result = portfolio._recommend(snapshot, session)
            action = next(a for a in result["actions"] if a["bucket"] == "a_share_core")

            self.assertEqual("caution", action["market_confirmation"]["status"])
            self.assertLess(action["amount"], action["raw_amount"])
            self.assertIn("市场确认偏弱", action["execution"])
        finally:
            session.close()

    def test_sector_caution_caps_intraday_add_for_matching_fund(self):
        session, snapshot = self.make_snapshot([
            {"name": "招商中证全指软件ETF联接C", "amount": 2000, "bucket": "themes"},
            {"name": "国泰黄金ETF联接A", "amount": 90000, "bucket": "gold"},
            {"name": "现金替代测试", "amount": 2000, "bucket": "fragments"},
        ])
        try:
            start = date.today() - timedelta(days=5)
            for idx in range(5):
                session.add(SectorFundFlow(
                    date=start + timedelta(days=idx),
                    sector_name="软件开发",
                    sector_type="industry",
                    change_pct=-1.0,
                    net_inflow_main=-200000.0,
                    net_inflow_main_ratio=-2.0,
                ))
            session.commit()

            actions = [{
                "type": "add",
                "bucket": "themes",
                "target_name": "行业主题仓",
                "amount": 5000,
                "priority": 1,
                "reason": "test",
                "execution": "test",
                "market_confirmation": {"status": "neutral", "label": "test", "factor": 0, "summary": "", "evidence": {}},
            }]
            recs = portfolio._fund_recommendations(snapshot, actions, session)
            software = next(r for r in recs if "软件" in r["name"])

            self.assertEqual("caution", software["market_confirmation"]["status"])
            self.assertLessEqual(software["suggested_amount"], 800)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
