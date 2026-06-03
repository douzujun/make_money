"""Big Money Flow models — northbound capital, ETF share tracking, and support signals."""
from datetime import datetime

from sqlalchemy import Column, String, Integer, Float, Date, DateTime, UniqueConstraint, Index, JSON

from app.core.database import Base


class NorthboundFlow(Base):
    """
    Daily northbound capital flow via 沪深港通.

    channel: 'sh_hk' (沪股通), 'sz_hk' (深股通), 'total' (合计北向)
    net_buy_amount unit: 亿元
    """
    __tablename__ = "northbound_flow"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    channel = Column(String, nullable=False)        # 'sh_hk' | 'sz_hk' | 'total'
    net_buy_amount = Column(Float, nullable=True)   # 成交净买额（亿元）
    net_inflow = Column(Float, nullable=True)        # 当日资金流入（亿元）
    balance = Column(Float, nullable=True)           # 当日余额（亿元）
    hs300_close = Column(Float, nullable=True)       # 沪深300收盘点位
    hs300_change_pct = Column(Float, nullable=True)  # 沪深300涨跌幅（%）
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "channel", name="uix_northbound_flow"),
        Index("idx_northbound_date_channel", "date", "channel"),
    )

    def __repr__(self):
        return f"<NorthboundFlow({self.channel} {self.date} {self.net_buy_amount})>"


class EtfShareRecord(Base):
    """
    Daily ETF total share count for state-intervention proxy ETFs.

    symbol: '510050' | '510300' | '510500'
    total_share unit: 亿份
    A spike in total_share signals large primary-market purchases (inferred 汇金 buying).
    """
    __tablename__ = "etf_share_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    symbol = Column(String, nullable=False)          # '510050' | '510300' | '510500'
    name = Column(String, nullable=True)             # ETF 简称
    total_share = Column(Float, nullable=True)        # 基金份额（亿份）
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "symbol", name="uix_etf_share_record"),
        Index("idx_etf_share_date_symbol", "date", "symbol"),
    )

    def __repr__(self):
        return f"<EtfShareRecord({self.symbol} {self.date} {self.total_share})>"


class BigMoneySignal(Base):
    """
    Daily conservative support signal inferred from broad ETF share changes.

    The signal is an inference about state-support traces, not a disclosure of
    actual 国家队 holdings.
    """
    __tablename__ = "big_money_signal"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)

    signal = Column(String, nullable=False, default="neutral")
    signal_label = Column(String, nullable=False, default="中性")
    watch_signal = Column(String, nullable=False, default="none")
    watch_label = Column(String, nullable=False, default="无观察信号")
    confidence = Column(String, nullable=False, default="low")

    basket_delta_share = Column(Float, nullable=True)    # 亿份
    estimated_amount = Column(Float, nullable=True)      # 亿元
    z_score = Column(Float, nullable=True)
    rolling_mean_20 = Column(Float, nullable=True)
    rolling_std_20 = Column(Float, nullable=True)

    market_daily_change = Column(Float, nullable=True)   # %
    market_drawdown_20 = Column(Float, nullable=True)    # %
    positive_etf_count = Column(Integer, nullable=False, default=0)
    negative_etf_count = Column(Integer, nullable=False, default=0)

    evidence = Column(JSON, nullable=True)
    data_quality = Column(String, nullable=False, default="unknown")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", name="uix_big_money_signal_date"),
        Index("idx_big_money_signal_date", "date"),
    )

    def __repr__(self):
        return f"<BigMoneySignal({self.date} {self.signal} z={self.z_score})>"
