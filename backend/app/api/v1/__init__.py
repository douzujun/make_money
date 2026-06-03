"""API router package."""
from fastapi import APIRouter, Depends

from app.api.v1 import auth, assets, prices, update, indicators, scheduler, binance, dashboard, sector_flow, big_money, backtest
from app.api.v1.auth import get_current_admin

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(assets.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(prices.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(update.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(indicators.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(scheduler.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(binance.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(dashboard.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(sector_flow.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(big_money.router, dependencies=[Depends(get_current_admin)])
api_router.include_router(backtest.router, dependencies=[Depends(get_current_admin)])
