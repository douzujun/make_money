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

from app.api.v1 import sector_flow
from app.core.database import Base
from app.models.sector_flow import SectorFundFlow


class SectorFlowSignalsTest(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.engine = create_engine(f"sqlite:///{self.db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.patches = [
            patch.object(sector_flow, "SessionLocal", self.Session),
            patch.object(sector_flow, "_get_vix_risk_factor", lambda: 0.6),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()
        os.remove(self.db_path)

    def add_sector(self, name, changes, flows=None, ratios=None):
        start = date.today() - timedelta(days=len(changes) + 20)
        session = self.Session()
        try:
            for idx, change in enumerate(changes):
                session.add(
                    SectorFundFlow(
                        date=start + timedelta(days=idx),
                        sector_name=name,
                        sector_type="industry",
                        change_pct=change,
                        net_inflow_main=flows[idx] if flows is not None else None,
                        net_inflow_main_ratio=ratios[idx] if ratios is not None else None,
                    )
                )
            session.commit()
        finally:
            session.close()

    def test_signals_backtest_reports_excess_return_and_flow_coverage(self):
        self.add_sector(
            "strong-flow",
            changes=[1, 1, 1, 1, 1, 1, 2, 2, 2, 2],
            flows=[100] * 10,
            ratios=[2] * 10,
        )
        self.add_sector("weak-price", changes=[-1, -1, -1, -1, -1, -1, -2, -2, -2, -2])
        self.add_sector("flat-price", changes=[0] * 10)

        response = sector_flow.get_sector_signals()

        bullish = response["backtests"]["n1"]["bullish"]
        self.assertEqual(4, bullish["samples"])
        self.assertAlmostEqual(2.0, bullish["avg_return"])
        self.assertAlmostEqual(0.0, bullish["benchmark_avg_return"])
        self.assertAlmostEqual(2.0, bullish["excess_avg_return"])
        self.assertEqual(4, bullish["flow_coverage_samples"])
        self.assertAlmostEqual(100.0, bullish["flow_coverage_rate"])

    def test_signals_do_not_accumulate_when_flow_coverage_is_low(self):
        self.add_sector(
            "strong-price-no-flow",
            changes=[2, 2, 2, 2, 2, 2, 3, 3, 3, 3],
            flows=[None] * 10,
            ratios=[None] * 10,
        )
        self.add_sector("weak-price", changes=[-1, -1, -1, -1, -1, -1, -2, -2, -2, -2])
        self.add_sector("flat-price", changes=[0] * 10)

        response = sector_flow.get_sector_signals()
        signal = next(s for s in response["signals"] if s["sector_name"] == "strong-price-no-flow")

        self.assertGreaterEqual(signal["horizons"]["n1"]["score"], 65)
        self.assertEqual("observe", signal["signal_action"]["action"])
        self.assertEqual("资金流覆盖不足", signal["signal_action"]["reason"])

    def test_reduce_action_reports_the_low_score_that_triggered_it(self):
        self.add_sector(
            "decaying-flow",
            changes=[2, 2, 2, 2, 2, 2, -3, -3, -3, -3],
            flows=[100] * 6 + [-100] * 4,
            ratios=[2] * 6 + [-2] * 4,
        )
        self.add_sector("flat-price", changes=[0] * 10)

        response = sector_flow.get_sector_signals()
        signal = next(s for s in response["signals"] if s["sector_name"] == "decaying-flow")

        self.assertEqual("reduce", signal["signal_action"]["action"])
        self.assertEqual(signal["horizons"]["n2"]["score"], signal["signal_action"]["score"])
        self.assertEqual("n2", signal["signal_action"]["horizon"])

    def test_display_signal_prioritizes_risk_action_over_bullish_n1(self):
        self.add_sector(
            "bullish-but-decaying",
            changes=[0, 0, 0, 0, 0, 7, 7, 7, 7, -1],
            flows=[100] * 6 + [-100] * 4,
            ratios=[2] * 6 + [-2] * 4,
        )
        self.add_sector("flat-price", changes=[0] * 10)

        response = sector_flow.get_sector_signals()
        signal = next(s for s in response["signals"] if s["sector_name"] == "bullish-but-decaying")

        self.assertEqual("bullish", signal["horizons"]["n1"]["direction"])
        self.assertEqual("reduce_watch", signal["signal_action"]["action"])
        self.assertEqual("reduce_watch", signal["display_signal"]["direction"])
        self.assertEqual("减仓观察", signal["display_signal"]["label"])
        self.assertIn("N+2", signal["display_signal"]["summary"])

    def test_backfill_endpoint_accepts_one_year_history_window(self):
        route = next(r for r in sector_flow.router.routes if getattr(r, "path", "").endswith("/backfill"))
        days_param = route.dependant.query_params[0]
        max_days = next(item.le for item in days_param.field_info.metadata if hasattr(item, "le"))

        self.assertEqual(365, max_days)


if __name__ == "__main__":
    unittest.main()
