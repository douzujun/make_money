"""Historical data backfill utilities."""
import os
import time
import asyncio
import yfinance as yf
import pandas as pd
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.price_data import PriceData
from app.core.database import SessionLocal
from app.core.config import settings
from app.fetchers.registry import get_fetcher


# Set proxy environment variables if configured
if settings.PROXY_URL:
    os.environ['HTTP_PROXY'] = settings.PROXY_URL
    os.environ['HTTPS_PROXY'] = settings.PROXY_URL
    print(f"Proxy configured: {settings.PROXY_URL}")


def fetch_historical_prices(
    symbol: str,
    start: date,
    end: date,
    interval: str = "1d"
) -> Optional[pd.DataFrame]:
    """
    Fetch historical price data from Yahoo Finance.
    
    Args:
        symbol: Yahoo Finance symbol (e.g., "BTC-USD", "SPY", "^VIX")
        start: Start date
        end: End date (inclusive)
        interval: Data interval (1d, 1wk, 1mo)
    
    Returns:
        DataFrame with columns: date, open, high, low, close, volume, adjusted_close
    """
    try:
        ticker = yf.Ticker(symbol)
        # yfinance end date is exclusive, so add 1 day
        df = ticker.history(start=start, end=end + timedelta(days=1), interval=interval)
        
        if df.empty:
            print(f"No data returned for {symbol}")
            return None
        
        # Reset index to make date a column
        df = df.reset_index()
        
        # Standardize column names
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        
        # Handle different date column names
        if 'date' not in df.columns:
            # Try common alternatives
            for col in ['datetime', 'timestamp']:
                if col in df.columns:
                    df = df.rename(columns={col: 'date'})
                    break
        
        # Rename columns to match our schema
        column_map = {
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "dividends": "dividends",
            "stock_splits": "stock_splits",
            "adj_close": "adjusted_close",
            "adjusted_close": "adjusted_close",
        }
        
        # Keep only needed columns
        df = df.rename(columns=column_map)
        
        # Ensure required columns exist
        required = ["date", "open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                print(f"Missing required column: {col}. Available: {df.columns.tolist()}")
                return None
        
        # Convert date to date object (not datetime)
        if pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = df["date"].dt.date
        else:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        
        # Fill missing volume with 0
        if "volume" not in df.columns:
            df["volume"] = 0
        df["volume"] = df["volume"].fillna(0).astype(int)
        
        return df
        
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None


def save_price_data(
    db: Session,
    asset_id: str,
    df: pd.DataFrame,
    interval: str = "1d",
    source: str = "yfinance"
) -> Tuple[int, int]:
    """
    Save price data to database.
    
    Returns:
        (inserted_count, updated_count)
    """
    inserted = 0
    updated = 0
    
    for _, row in df.iterrows():
        # Check if record exists
        existing = db.query(PriceData).filter(
            PriceData.asset_id == asset_id,
            PriceData.date == row["date"],
            PriceData.interval == interval
        ).first()
        
        if existing:
            # Update existing
            existing.open = float(row["open"])
            existing.high = float(row["high"])
            existing.low = float(row["low"])
            existing.close = float(row["close"])
            existing.volume = int(row["volume"])
            existing.source = source
            existing.updated_at = datetime.utcnow()
            updated += 1
        else:
            # Create new
            price_data = PriceData(
                asset_id=asset_id,
                date=row["date"],
                interval=interval,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                source=source,
                timestamp=datetime.combine(row["date"], datetime.min.time())
            )
            db.add(price_data)
            inserted += 1
    
    db.commit()
    return inserted, updated


def backfill_asset(
    asset_id: str,
    symbol: str,
    start: date,
    end: date = None,
    interval: str = "1d",
    db: Session = None
) -> dict:
    """
    Backfill historical price data for a single asset.
    
    Args:
        asset_id: Internal asset ID
        symbol: Yahoo Finance symbol
        start: Start date
        end: End date (default: today)
        interval: Data interval
        db: Database session (optional)
    
    Returns:
        Result dict with status and counts
    """
    if end is None:
        end = datetime.now().date()
    
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    
    try:
        print(f"Backfilling {asset_id} ({symbol}): {start} to {end}")
        
        df = fetch_historical_prices(symbol, start, end, interval)
        
        if df is None or df.empty:
            return {
                "asset_id": asset_id,
                "symbol": symbol,
                "status": "error",
                "message": "No data fetched",
                "inserted": 0,
                "updated": 0
            }
        
        inserted, updated = save_price_data(db, asset_id, df, interval)
        
        return {
            "asset_id": asset_id,
            "symbol": symbol,
            "status": "success",
            "start_date": df["date"].min(),
            "end_date": df["date"].max(),
            "records": len(df),
            "inserted": inserted,
            "updated": updated
        }
        
    except Exception as e:
        db.rollback()
        return {
            "asset_id": asset_id,
            "symbol": symbol,
            "status": "error",
            "message": str(e),
            "inserted": 0,
            "updated": 0
        }
    finally:
        if close_db:
            db.close()


def get_yfinance_symbol(asset: Asset) -> str:
    """
    Get Yahoo Finance symbol for an asset.
    
    Prefer source_symbol because some Yahoo tickers differ from display symbols
    (for example DX-Y.NYB vs DXY). Fall back to ID for crypto and symbol for
    regular stocks/ETFs.
    """
    if asset.source_symbol:
        return asset.source_symbol
    if asset.asset_type == "crypto":
        return asset.id  # e.g., BTC-USD, ETH-USD
    return asset.symbol  # e.g., SPY, AAPL


def backfill_all_assets(
    start: date = None,
    end: date = None,
    interval: str = "1d",
    asset_ids: List[str] = None
) -> List[dict]:
    """
    Backfill all assets or specified assets.
    
    Args:
        start: Start date (default: 1 year ago)
        end: End date (default: today)
        interval: Data interval
        asset_ids: Specific asset IDs to backfill (None = all)
    
    Returns:
        List of result dicts
    """
    if start is None:
        start = datetime.now().date() - timedelta(days=365)
    if end is None:
        end = datetime.now().date()
    
    db = SessionLocal()
    try:
        query = db.query(Asset)
        if asset_ids:
            query = query.filter(Asset.id.in_(asset_ids))
        
        assets = query.all()
        results = []
        
        print(f"Backfilling {len(assets)} assets from {start} to {end}")
        print("-" * 50)
        
        for asset in assets:
            yf_symbol = get_yfinance_symbol(asset)
            result = backfill_asset(
                asset_id=asset.id,
                symbol=yf_symbol,
                start=start,
                end=end,
                interval=interval,
                db=db
            )
            results.append(result)
            print(f"  {result['asset_id']}: {result.get('records', 0)} records "
                  f"({result.get('inserted', 0)} new, {result.get('updated', 0)} updated)")
        
        print("-" * 50)
        total_records = sum(r.get("records", 0) for r in results)
        total_inserted = sum(r.get("inserted", 0) for r in results)
        total_updated = sum(r.get("updated", 0) for r in results)
        print(f"Total: {total_records} records ({total_inserted} new, {total_updated} updated)")
        
        return results
        
    finally:
        db.close()


def get_latest_price_date(asset_id: str, interval: str = "1d", db: Session = None) -> Optional[date]:
    """Get the latest price date for an asset."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    
    try:
        latest = db.query(PriceData).filter(
            PriceData.asset_id == asset_id,
            PriceData.interval == interval
        ).order_by(PriceData.date.desc()).first()
        
        return latest.date if latest else None
    finally:
        if close_db:
            db.close()


def incremental_update(
    asset_ids: List[str] = None,
    lookback_days: int = 5,
    interval: str = "1d"
) -> List[dict]:
    """
    Incremental update - fetch data from latest date to today.
    
    Args:
        asset_ids: Specific assets to update (None = all)
        lookback_days: Extra days to fetch for safety
        interval: Data interval
    
    Returns:
        List of result dicts
    """
    db = SessionLocal()
    try:
        query = db.query(Asset)
        if asset_ids:
            query = query.filter(Asset.id.in_(asset_ids))
        
        assets = query.all()
        results = []
        end = datetime.now().date()
        
        print(f"Incremental update for {len(assets)} assets (today: {end})")
        print("-" * 50)
        
        for asset in assets:
            yf_symbol = get_yfinance_symbol(asset)
            latest = get_latest_price_date(asset.id, interval, db)
            
            if latest:
                # Start from latest date minus lookback buffer
                start = latest - timedelta(days=lookback_days)
                print(f"  {asset.id}: updating from {start} (latest was {latest})")
            else:
                # No existing data, fetch last year
                start = end - timedelta(days=365)
                print(f"  {asset.id}: no existing data, fetching from {start}")
            
            result = backfill_asset(
                asset_id=asset.id,
                symbol=yf_symbol,
                start=start,
                end=end,
                interval=interval,
                db=db
            )
            results.append(result)
        
        return results
        
    finally:
        db.close()


# ============== Multi-source support ==============

def get_source_symbol(asset: Asset) -> str:
    """
    Get the source-specific symbol for an asset.
    
    For yfinance: use symbol or id (for crypto)
    For binance: use source_symbol
    """
    if asset.data_source == "binance":
        return asset.source_symbol
    elif asset.data_source == "yfinance":
        if asset.asset_type == "crypto":
            return asset.id  # e.g., BTC-USD
        return asset.symbol  # e.g., SPY
    else:
        # Default fallback
        return asset.source_symbol or asset.symbol


def update_asset_with_fetcher_by_props(
    asset_id: str,
    source_symbol: str,
    data_source: str,
    start: date,
    end: date,
    interval: str = "1d",
    db: Session = None
) -> dict:
    """
    Update price data using extracted properties (not ORM object).
    
    This avoids DetachedInstanceError after session commit.
    """
    if db is None:
        db = SessionLocal()
        should_close_db = True
    else:
        should_close_db = False
    
    try:
        # Get the appropriate fetcher
        fetcher_class = get_fetcher(data_source)
        if not fetcher_class:
            return {
                "asset_id": asset_id,
                "symbol": source_symbol,
                "status": "error",
                "message": f"No fetcher found for data_source: {data_source}",
                "inserted": 0,
                "updated": 0
            }
        
        fetcher = fetcher_class()
        
        print(f"Updating {asset_id} ({source_symbol}) via {data_source}: {start} to {end}")
        
        # Fetch prices using async method
        prices = asyncio.run(fetcher.fetch_prices(source_symbol, start, end, interval))
        
        if not prices:
            return {
                "asset_id": asset_id,
                "symbol": source_symbol,
                "status": "error",
                "message": "No data fetched",
                "inserted": 0,
                "updated": 0
            }
        
        # Convert to DataFrame for compatibility with save_price_data
        df = pd.DataFrame(prices)
        
        # Save to database
        inserted, updated = save_price_data(db, asset_id, df, interval, source=data_source)
        
        return {
            "asset_id": asset_id,
            "symbol": source_symbol,
            "status": "success",
            "start_date": df["date"].min(),
            "end_date": df["date"].max(),
            "records": len(df),
            "inserted": inserted,
            "updated": updated,
            "source": data_source
        }
        
    except Exception as e:
        db.rollback()
        return {
            "asset_id": asset_id,
            "symbol": source_symbol,
            "status": "error",
            "message": str(e),
            "inserted": 0,
            "updated": 0
        }
    finally:
        if should_close_db:
            db.close()


def update_asset_with_fetcher(
    asset: Asset,
    start: date,
    end: date,
    interval: str = "1d",
    db: Session = None,
    close_db: bool = True
) -> dict:
    """
    Update price data for an asset using its configured fetcher.
    
    This is a generic function that works with any registered fetcher.
    """
    should_close_db = close_db
    if db is None:
        db = SessionLocal()
        should_close_db = True
    
    try:
        # Get the appropriate fetcher
        fetcher_class = get_fetcher(asset.data_source)
        if not fetcher_class:
            return {
                "asset_id": asset.id,
                "symbol": asset.source_symbol,
                "status": "error",
                "message": f"No fetcher found for data_source: {asset.data_source}",
                "inserted": 0,
                "updated": 0
            }
        
        fetcher = fetcher_class()
        source_symbol = get_source_symbol(asset)
        
        print(f"Updating {asset.id} ({source_symbol}) via {asset.data_source}: {start} to {end}")
        
        # Fetch prices using async method
        prices = asyncio.run(fetcher.fetch_prices(source_symbol, start, end, interval))
        
        if not prices:
            return {
                "asset_id": asset.id,
                "symbol": source_symbol,
                "status": "error",
                "message": "No data fetched",
                "inserted": 0,
                "updated": 0
            }
        
        # Convert to DataFrame for compatibility with save_price_data
        df = pd.DataFrame(prices)
        
        # Save to database
        inserted, updated = save_price_data(db, asset.id, df, interval, source=asset.data_source)
        
        return {
            "asset_id": asset.id,
            "symbol": source_symbol,
            "status": "success",
            "start_date": df["date"].min(),
            "end_date": df["date"].max(),
            "records": len(df),
            "inserted": inserted,
            "updated": updated,
            "source": asset.data_source
        }
        
    except Exception as e:
        db.rollback()
        return {
            "asset_id": asset.id,
            "symbol": asset.source_symbol,
            "status": "error",
            "message": str(e),
            "inserted": 0,
            "updated": 0
        }
    finally:
        if should_close_db:
            db.close()


def incremental_update_multi_source(
    asset_ids: List[str] = None,
    lookback_days: int = 5,
    interval: str = "1d",
    data_source: str = None
) -> List[dict]:
    """
    Incremental update supporting multiple data sources.
    
    Args:
        asset_ids: Specific assets to update (None = all)
        lookback_days: Extra days to fetch for safety
        interval: Data interval
        data_source: Filter by data_source (e.g., 'yfinance', 'binance')
    
    Returns:
        List of result dicts
    """
    db = SessionLocal()
    try:
        query = db.query(Asset)
        if asset_ids:
            query = query.filter(Asset.id.in_(asset_ids))
        if data_source:
            query = query.filter(Asset.data_source == data_source)
        
        assets = query.all()
        results = []
        end = datetime.now().date()
        
        print(f"Incremental update for {len(assets)} assets (today: {end})")
        print("-" * 50)
        
        for asset in assets:
            # 在 commit 前提取所有需要的属性
            asset_id = asset.id
            asset_data_source = asset.data_source
            asset_source_symbol = asset.source_symbol
            
            latest = get_latest_price_date(asset_id, interval, db)
            
            if latest:
                start = latest - timedelta(days=lookback_days)
                print(f"  {asset_id} ({asset_data_source}): updating from {start}")
            else:
                start = end - timedelta(days=365)
                print(f"  {asset_id} ({asset_data_source}): no data, fetching from {start}")
            
            # 使用提取的属性调用，避免 commit 后访问 ORM 对象
            result = update_asset_with_fetcher_by_props(
                asset_id=asset_id,
                source_symbol=asset_source_symbol,
                data_source=asset_data_source,
                start=start,
                end=end,
                interval=interval,
                db=db
            )
            results.append(result)
            
            status_icon = "✓" if result["status"] == "success" else "✗"
            print(f"    {status_icon} {result.get('inserted', 0)} new, {result.get('updated', 0)} updated")
        
        return results
        
    finally:
        db.close()


if __name__ == "__main__":
    # Test: backfill last year of data
    results = backfill_all_assets()
    for r in results:
        print(r)
