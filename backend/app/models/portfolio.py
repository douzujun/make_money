"""Portfolio holding snapshots and recommendation records."""
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class PortfolioSnapshot(Base):
    """One manually maintained daily portfolio snapshot."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    money_fund_amount = Column(Float, nullable=False, default=0.0)
    cash_amount = Column(Float, nullable=False, default=0.0)
    usable_cash_amount = Column(Float, nullable=False, default=0.0)
    reserve_floor_amount = Column(Float, nullable=False, default=80000.0)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    holdings = relationship(
        "PortfolioHolding",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_portfolio_snapshot_date"),
    )


class PortfolioHolding(Base):
    """Fund-level holding inside a daily snapshot."""

    __tablename__ = "portfolio_holdings"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("portfolio_snapshots.id"), nullable=False, index=True)
    fund_code = Column(String(20), nullable=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False, default=0.0)
    profit_amount = Column(Float, nullable=True)
    profit_rate = Column(Float, nullable=True)
    bucket = Column(String, nullable=False, index=True)
    flow_sector_name = Column(String, nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    snapshot = relationship("PortfolioSnapshot", back_populates="holdings")
