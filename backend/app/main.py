"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.api import api_router
from app.services.scheduler import get_data_scheduler
from app.models.asset import Asset
from app.models.indicator import Indicator, IndicatorTemplate
from app.models.big_money import NorthboundFlow, EtfShareRecord, BigMoneySignal  # noqa: F401
from app.models.backtest import EtfPriceCache  # noqa: F401
from app.models.portfolio import PortfolioSnapshot, PortfolioHolding  # noqa: F401
from app.indicators.btc_fear_greed import init_btc_fear_greed_targets
from app.indicators.cnn_fear_greed import init_cnn_fear_greed_targets
from app.indicators.ma200 import init_ma200_targets
from app.indicators.volatility_indices import init_volatility_targets
from app.indicators.rsi import init_dashboard_targets

# Import fetchers to register them
import app.fetchers  # noqa: F401
# Import indicators to register processors
import app.indicators  # noqa: F401

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Create database tables
Base.metadata.create_all(bind=engine)


def ensure_lightweight_schema_updates():
    """Apply small SQLite-safe schema additions for non-Alembic local upgrades."""
    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect != "sqlite":
            return
        tables = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "portfolio_holdings" not in tables:
            return
        columns = {row[1] for row in conn.exec_driver_sql(
            "PRAGMA table_info(portfolio_holdings)"
        ).fetchall()}
        if "fund_code" not in columns:
            conn.exec_driver_sql("ALTER TABLE portfolio_holdings ADD COLUMN fund_code VARCHAR(20)")
        if "profit_amount" not in columns:
            conn.exec_driver_sql("ALTER TABLE portfolio_holdings ADD COLUMN profit_amount FLOAT")
        if "profit_rate" not in columns:
            conn.exec_driver_sql("ALTER TABLE portfolio_holdings ADD COLUMN profit_rate FLOAT")
        if "flow_sector_name" not in columns:
            conn.exec_driver_sql("ALTER TABLE portfolio_holdings ADD COLUMN flow_sector_name VARCHAR")


ensure_lightweight_schema_updates()


def init_portfolio_macro_assets():
    """Ensure portfolio macro confirmation assets exist for price refresh."""
    db = SessionLocal()
    try:
        defaults = [
            Asset(
                id="DTWEXBGS",
                symbol="DTWEXBGS",
                name="Nominal Broad U.S. Dollar Index",
                asset_type="index",
                exchange="FRED",
                country="US",
                currency="USD",
                data_source="fred",
                source_symbol="DTWEXBGS",
                is_active=True,
                is_watched=True,
                config={"fallback": "DBnomics FED/H10 JRXWTFB_N.B"},
            ),
            Asset(
                id="DX-Y.NYB",
                symbol="DXY",
                name="US Dollar Index",
                asset_type="index",
                exchange="ICE",
                country="US",
                currency="USD",
                data_source="yfinance",
                source_symbol="DX-Y.NYB",
                is_active=True,
                is_watched=True,
            ),
            Asset(
                id="DX=F",
                symbol="DX=F",
                name="US Dollar Index Futures",
                asset_type="index",
                exchange="ICE",
                country="US",
                currency="USD",
                data_source="yfinance",
                source_symbol="DX=F",
                is_active=True,
                is_watched=True,
            ),
            Asset(
                id="UUP",
                symbol="UUP",
                name="Invesco DB US Dollar Index Bullish Fund",
                asset_type="etf",
                exchange="NYSEARCA",
                country="US",
                currency="USD",
                data_source="yfinance",
                source_symbol="UUP",
                is_active=True,
                is_watched=True,
            ),
            Asset(
                id="GC=F",
                symbol="GC=F",
                name="Gold Futures",
                asset_type="commodity",
                exchange="COMEX",
                country="US",
                currency="USD",
                data_source="yfinance",
                source_symbol="GC=F",
                is_active=True,
                is_watched=True,
            ),
        ]
        created = 0
        for asset in defaults:
            if not db.query(Asset).filter(Asset.id == asset.id).first():
                db.add(asset)
                created += 1
        if created:
            db.commit()
            logging.getLogger("main").info("Portfolio macro assets initialized, created=%s", created)
    except Exception as e:
        db.rollback()
        logging.getLogger("main").error("Failed to initialize portfolio macro assets: %s", e)
    finally:
        db.close()

# Initialize indicator templates and default indicators
def init_indicators():
    """Initialize default indicator templates and instances."""
    import sys
    import os
    # Add parent directory to path to import init_indicators
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from init_indicators import init_indicator_templates
    db = SessionLocal()
    try:
        # Initialize templates
        init_indicator_templates(db)

        # Create default indicator instances if not exists
        created_count = 0

        # Let indicator modules own their required watched-asset bootstrap logic
        created_count += init_btc_fear_greed_targets(db)
        created_count += init_cnn_fear_greed_targets(db)
        created_count += init_ma200_targets(db)
        created_count += init_volatility_targets(db)
        created_count += init_dashboard_targets(db)

        db.commit()
        
        logging.getLogger("main").info("Indicators initialized, created=%s", created_count)
    except Exception as e:
        db.rollback()
        logging.getLogger("main").error(f"Failed to initialize indicators: {e}")
    finally:
        db.close()


init_indicators()
init_portfolio_macro_assets()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # --- Startup ---
    scheduler = get_data_scheduler()
    if settings.SCHEDULER_ENABLED:
        scheduler.start()
        logging.getLogger("main").info("Daily scheduler started")
    else:
        logging.getLogger("main").info("Daily scheduler disabled (SCHEDULER_ENABLED=false)")

    yield

    # --- Shutdown ---
    scheduler.stop()
    logging.getLogger("main").info("Daily scheduler stopped")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="数据终端 - 统一数据采集与管理系统",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Data Terminal API",
        "version": "0.2.0",
        "docs": "/docs",
        "scheduler": "enabled" if settings.SCHEDULER_ENABLED else "disabled",
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    scheduler = get_data_scheduler()
    return {
        "status": "healthy",
        "scheduler_running": scheduler.is_running,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
