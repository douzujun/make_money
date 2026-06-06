"""Price update scheduler service."""
import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Callable
import threading

from app.services.backfill import incremental_update_multi_source, update_asset_with_fetcher
from app.core.database import SessionLocal
from app.models.asset import Asset


class PriceUpdateScheduler:
    """
    Scheduler for automatic price updates.
    
    For Phase 3 testing: runs on-demand, not daily.
    Full daily scheduling will be implemented when watch list is ready.
    """
    
    def __init__(self):
        self._running = False
        self._lock = threading.Lock()
        self._last_run: Optional[datetime] = None
        self._results: List[Dict] = []
    
    @property
    def is_running(self) -> bool:
        """Check if an update is currently running."""
        with self._lock:
            return self._running
    
    @property
    def last_run(self) -> Optional[datetime]:
        """Get timestamp of last successful run."""
        return self._last_run
    
    def run_update(
        self,
        asset_ids: List[str] = None,
        lookback_days: int = 5,
        force: bool = False
    ) -> List[Dict]:
        """
        Run price update for specified assets or all assets.
        
        Args:
            asset_ids: Specific assets to update (None = all)
            lookback_days: Extra days to fetch for safety
            force: Run even if another update is in progress
        
        Returns:
            List of update results
        """
        with self._lock:
            if self._running and not force:
                print("Update already in progress, skipping...")
                return []
            self._running = True
        
        try:
            print(f"[{datetime.now()}] Starting price update...")
            results = incremental_update_multi_source(
                asset_ids=asset_ids,
                lookback_days=lookback_days
            )
            
            self._last_run = datetime.now()
            self._results = results
            
            # Print summary
            print(f"[{datetime.now()}] Price update completed")
            success_count = sum(1 for r in results if r.get("status") == "success")
            total_new = sum(r.get("inserted", 0) for r in results)
            total_updated = sum(r.get("updated", 0) for r in results)
            print(f"  Success: {success_count}/{len(results)}")
            print(f"  New records: {total_new}")
            print(f"  Updated records: {total_updated}")
            
            return results
            
        finally:
            with self._lock:
                self._running = False
    
    def get_status(self) -> Dict:
        """Get scheduler status."""
        return {
            "is_running": self.is_running,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_result_count": len(self._results)
        }


# Global scheduler instance
_scheduler: Optional[PriceUpdateScheduler] = None


def get_scheduler() -> PriceUpdateScheduler:
    """Get or create global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = PriceUpdateScheduler()
    return _scheduler


def run_price_update(
    asset_ids: List[str] = None,
    lookback_days: int = 5
) -> List[Dict]:
    """
    Convenience function to run price update.
    
    Usage:
        results = run_price_update()
        results = run_price_update(['BTC-USD', 'SPY'])
    """
    scheduler = get_scheduler()
    return scheduler.run_update(asset_ids=asset_ids, lookback_days=lookback_days)


def update_single_asset(asset_id: str, lookback_days: int = 30) -> Dict:
    """
    Update a single asset's price data.
    
    Args:
        asset_id: Asset ID to update
        lookback_days: Days to look back
    
    Returns:
        Update result dict
    """
    db = SessionLocal()
    try:
        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            return {
                "asset_id": asset_id,
                "status": "error",
                "message": "Asset not found"
            }
        
        end = date.today()
        start = end - timedelta(days=lookback_days)

        result = update_asset_with_fetcher(
            asset=asset,
            start=start,
            end=end,
            db=db,
            close_db=False,
        )
        
        return result
    finally:
        db.close()


# Future: Daily scheduled updates (to be implemented with watch list)
async def schedule_daily_updates(hour: int = 8, minute: int = 0):
    """
    Schedule daily price updates at specified time.
    
    This is for future use when watch list is implemented.
    
    Args:
        hour: Hour of day (24h format)
        minute: Minute of hour
    """
    # TODO: Implement when watch list feature is ready
    # Will use APScheduler or similar
    raise NotImplementedError("Daily scheduling will be implemented with watch list feature")
