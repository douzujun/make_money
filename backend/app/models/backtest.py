"""Backtest ETF price cache model."""
from datetime import date, datetime

from sqlalchemy import Column, Integer, String, Date, Float, DateTime, UniqueConstraint

from app.core.database import Base


class EtfPriceCache(Base):
    __tablename__ = "etf_price_cache"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    nav = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "symbol", name="uq_etf_price_date_symbol"),
    )
