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
from app.models.asset import Asset
from app.models.portfolio import PortfolioHolding, PortfolioSnapshot
from app.models.price_data import PriceData
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

    def add_asset_prices(self, session, asset_id, closes, name=None):
        session.add(Asset(
            id=asset_id,
            symbol=asset_id,
            name=name or asset_id,
            asset_type="commodity" if asset_id == "GC=F" else "index",
            data_source="yfinance",
            source_symbol=asset_id,
            is_active=True,
        ))
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

    def test_big_money_caution_downgrades_a_share_add_to_watch(self):
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
            self.assertEqual("add_watch", action["type"])
            self.assertEqual(0, action["amount"])
            self.assertIn("不执行当日加仓", action["execution"])
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

    def test_manual_flow_sector_drives_confirmation_when_name_does_not_match(self):
        session, _snapshot = self.make_snapshot([
            {"name": "自定义主动基金", "amount": 2000, "bucket": "themes", "flow_sector_name": "软件开发"},
            {"name": "国泰黄金ETF联接A", "amount": 90000, "bucket": "gold"},
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

            confirmation = portfolio._sector_confirmation_for_fund(
                "自定义主动基金",
                "themes",
                session,
                "软件开发",
            )

            self.assertEqual("软件开发", confirmation["sector_name"])
            self.assertEqual("caution", confirmation["status"])
        finally:
            session.close()

    def test_bucket_market_confirmation_dedupes_repeated_sector_names(self):
        session, snapshot = self.make_snapshot([
            {"name": "招商中证全指软件ETF联接C", "amount": 2000, "bucket": "themes"},
            {"name": "自定义软件主动基金", "amount": 3000, "bucket": "themes", "flow_sector_name": "软件开发"},
            {"name": "国泰黄金ETF联接A", "amount": 90000, "bucket": "gold"},
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

            confirmations = portfolio._bucket_market_confirmations(snapshot, session)
            evidence = confirmations["themes"]["evidence"]

            self.assertEqual("caution", confirmations["themes"]["status"])
            self.assertEqual(1, evidence["matched_count"])
            self.assertEqual(1, evidence["caution_count"])
            self.assertEqual(["软件开发"], [s["sector_name"] for s in evidence["top_sectors"]])
        finally:
            session.close()

    def test_caution_trim_uses_small_risk_control_amount_not_larger_amount(self):
        action = {
            "type": "trim",
            "bucket": "themes",
            "target_name": "行业主题仓",
            "amount": 5000,
            "priority": 1,
            "reason": "主题仓超配",
            "execution": "old",
        }
        confirmation = {
            "status": "caution",
            "label": "桶内行业偏弱",
            "factor": -0.18,
            "evidence": {
                "top_sectors": [{
                    "sector_name": "软件开发",
                    "evidence": {"latest_change_pct": -1.0, "latest_net_inflow_yi": -2.0},
                }],
            },
        }

        adjusted = portfolio._apply_market_to_action(action, confirmation)

        self.assertEqual("trim", adjusted["type"])
        self.assertEqual(3000, adjusted["amount"])
        self.assertIn("风控减仓触发", adjusted["execution"])

    def test_sustained_weak_trim_steps_up_when_not_selling_into_drop(self):
        action = {
            "type": "trim",
            "bucket": "themes",
            "target_name": "行业主题仓",
            "amount": 5000,
            "priority": 1,
            "reason": "主题仓超配",
            "execution": "old",
        }
        confirmation = {
            "status": "caution",
            "label": "桶内行业偏弱",
            "factor": -0.18,
            "evidence": {
                "top_sectors": [{
                    "sector_name": "软件开发",
                    "evidence": {
                        "latest_change_pct": -0.5,
                        "change_3d": -2.0,
                        "latest_net_inflow_yi": -2.0,
                        "recent_3d_flow_yi": -4.5,
                        "negative_flow_days_3": 3,
                    },
                }],
            },
        }

        adjusted = portfolio._apply_market_to_action(action, confirmation)

        self.assertEqual("trim", adjusted["type"])
        self.assertEqual(3800, adjusted["amount"])
        self.assertIn("连续弱势升档", adjusted["execution"])

    def test_kill_drop_brake_reduces_risk_trim_amount(self):
        action = {
            "type": "trim",
            "bucket": "themes",
            "target_name": "行业主题仓",
            "amount": 5000,
            "priority": 1,
            "reason": "主题仓超配",
            "execution": "old",
        }
        confirmation = {
            "status": "caution",
            "label": "桶内行业偏弱",
            "factor": -0.18,
            "evidence": {
                "top_sectors": [{
                    "sector_name": "软件开发",
                    "evidence": {
                        "latest_change_pct": -2.0,
                        "change_3d": -6.0,
                        "latest_net_inflow_yi": -2.0,
                        "recent_3d_flow_yi": -4.5,
                        "negative_flow_days_3": 3,
                    },
                }],
            },
        }

        adjusted = portfolio._apply_market_to_action(action, confirmation)

        self.assertEqual("trim", adjusted["type"])
        self.assertEqual(1800, adjusted["amount"])
        self.assertIn("杀跌刹车", adjusted["execution"])

    def test_supportive_trim_without_rebound_trigger_becomes_watch(self):
        action = {
            "type": "trim",
            "bucket": "themes",
            "target_name": "行业主题仓",
            "amount": 5000,
            "priority": 1,
            "reason": "主题仓超配",
            "execution": "old",
        }
        confirmation = {
            "status": "supportive",
            "label": "桶内行业偏强",
            "factor": 0.10,
            "evidence": {
                "top_sectors": [{
                    "sector_name": "软件开发",
                    "evidence": {"latest_change_pct": 1.0, "latest_net_inflow_yi": 1.0},
                }],
            },
        }

        adjusted = portfolio._apply_market_to_action(action, confirmation)

        self.assertEqual("trim_watch", adjusted["type"])
        self.assertEqual(0, adjusted["amount"])
        self.assertIn("减仓观察", adjusted["execution"])

    def test_supportive_trim_with_rebound_trigger_executes_reduced_amount(self):
        action = {
            "type": "trim",
            "bucket": "themes",
            "target_name": "行业主题仓",
            "amount": 5000,
            "priority": 1,
            "reason": "主题仓超配",
            "execution": "old",
        }
        confirmation = {
            "status": "supportive",
            "label": "桶内行业偏强",
            "factor": 0.10,
            "evidence": {
                "top_sectors": [{
                    "sector_name": "软件开发",
                    "evidence": {"latest_change_pct": 1.6, "latest_net_inflow_yi": 0.1},
                }],
            },
        }

        adjusted = portfolio._apply_market_to_action(action, confirmation)

        self.assertEqual("trim", adjusted["type"])
        self.assertEqual(3800, adjusted["amount"])
        self.assertIn("反弹减仓触发", adjusted["execution"])

    def test_gold_confirmation_uses_gold_ma_and_dollar_downtrend(self):
        session, snapshot = self.make_snapshot([
            {"name": "国泰黄金ETF联接A", "amount": 90000, "bucket": "gold"},
            {"name": "现金替代测试", "amount": 50000, "bucket": "fragments"},
        ])
        try:
            self.add_asset_prices(session, "GC=F", [100 + idx for idx in range(25)], "Gold Futures")
            self.add_asset_prices(session, "DX-Y.NYB", [110 - idx * 0.2 for idx in range(25)], "US Dollar Index")

            confirmations = portfolio._bucket_market_confirmations(snapshot, session)
            gold = confirmations["gold"]

            self.assertEqual("supportive", gold["status"])
            self.assertEqual("人工确认", gold["permission_label"])
            self.assertEqual("manual_confirm", gold["operation_permission"])
            self.assertIn("20日均线", gold["summary"])
            self.assertGreater(gold["evidence"]["gold_ma20_deviation_pct"], 0)
            self.assertLess(gold["evidence"]["dollar_trend_5d_pct"], 0)
        finally:
            session.close()

    def test_gold_confirmation_warns_when_dollar_data_missing(self):
        session, snapshot = self.make_snapshot([
            {"name": "国泰黄金ETF联接A", "amount": 90000, "bucket": "gold"},
            {"name": "现金替代测试", "amount": 50000, "bucket": "fragments"},
        ])
        try:
            self.add_asset_prices(session, "GC=F", [100 + idx for idx in range(25)], "Gold Futures")

            confirmations = portfolio._bucket_market_confirmations(snapshot, session)
            gold = confirmations["gold"]

            self.assertEqual("neutral", gold["status"])
            self.assertEqual("黄金宏观信号不完整", gold["label"])
            self.assertEqual("manual_confirm", gold["operation_permission"])
            self.assertIn("美元指数缺失", gold["summary"])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
