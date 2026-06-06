"""API router package."""
from fastapi import APIRouter

from app.api.v1 import assets, prices, update, indicators, scheduler, binance, dashboard, sector_flow, big_money, backtest, portfolio

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(assets.router)
api_router.include_router(prices.router)
api_router.include_router(update.router)
api_router.include_router(indicators.router)
api_router.include_router(scheduler.router)
api_router.include_router(binance.router)
api_router.include_router(dashboard.router)
api_router.include_router(sector_flow.router)
api_router.include_router(big_money.router)
api_router.include_router(backtest.router)
api_router.include_router(portfolio.router)
