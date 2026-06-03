"""Sector fund flow models — A-share industry/concept daily money flow data."""
from datetime import datetime, date

from sqlalchemy import (
    Column, String, Integer, Float, Date, DateTime,
    UniqueConstraint, Index, Boolean,
)

from app.core.database import Base


class SectorFundFlow(Base):
    """
    Daily fund flow record for an A-share industry or concept sector.

    Populated by the AkShare fetcher every trading day at 16:00.
    主力净流入 unit: 万元 (10,000 RMB).
    """

    __tablename__ = "sector_fund_flow"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identity
    date = Column(Date, nullable=False, index=True)
    sector_name = Column(String, nullable=False, index=True)
    sector_type = Column(String, nullable=False)  # 'industry' | 'concept'

    # Core metrics
    change_pct = Column(Float, nullable=True)           # 涨跌幅 (%)
    net_inflow_main = Column(Float, nullable=True)      # 主力净流入-净额 (万元)
    net_inflow_main_ratio = Column(Float, nullable=True)# 主力净流入-净占比 (%)

    # Breakdown
    net_inflow_super_large = Column(Float, nullable=True)  # 超大单净流入 (万元)
    net_inflow_large = Column(Float, nullable=True)        # 大单净流入 (万元)
    net_inflow_medium = Column(Float, nullable=True)       # 中单净流入 (万元)
    net_inflow_small = Column(Float, nullable=True)        # 小单净流入 (万元)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "sector_name", "sector_type", name="uix_sector_flow_date"),
        Index("idx_sector_flow_query", "sector_type", "sector_name", "date"),
    )

    def __repr__(self):
        return f"<SectorFundFlow({self.sector_type} {self.sector_name} {self.date} {self.net_inflow_main})>"
