"""
Daily data scheduler service.

Manages automatic price and indicator updates using APScheduler.

Default jobs:
  - update_crypto:     every day 09:00 Asia/Shanghai  (BTC-USD prices + Fear & Greed)
  - update_us_market:  every day 06:00 Asia/Shanghai  (SPY prices + VIX)
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, JobExecutionEvent

from app.core.database import SessionLocal
from app.models.asset import Asset
from app.models.indicator import Indicator
from app.models.scheduler import SchedulerRunLog
from app.services.backfill import incremental_update, incremental_update_multi_source
from app.services.indicator_scheduler import (
    fetch_external_indicator,
    fetch_latest_external_indicator,
    calculate_indicator_latest,
)

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)

# Timezone for all cron triggers
TZ = "Asia/Shanghai"

# ---------------------------------------------------------------------------
# Job definitions (centralised so they can be referenced by id)
# ---------------------------------------------------------------------------

DEFAULT_JOBS = [
    {
        "id": "update_crypto",
        "name": "加密货币每日更新 (BTC)",
        "func": "_job_update_crypto",
        "trigger_type": "cron",
        "hour": 9,
        "minute": 0,
        "description": "更新加密货币价格 + BTC 恐慌贪婪指数",
    },
    {
        "id": "update_us_market",
        "name": "美股每日更新 (SPY/VIX)",
        "func": "_job_update_us_market",
        "trigger_type": "cron",
        "hour": 6,
        "minute": 0,
        "description": "更新美股/ETF 价格 + VIX 波动率指数",
    },
    {
        "id": "sync_sectors_weekly",
        "name": "Sector/Industry 每周同步",
        "func": "_job_sync_sectors_weekly",
        "trigger_type": "cron",
        "day_of_week": "sun",
        "hour": 3,
        "minute": 0,
        "description": "每周同步 Sector/Industry 及龙头公司数据",
    },
    {
        "id": "update_sector_flow",
        "name": "A股板块资金流每日更新",
        "func": "_job_update_sector_flow",
        "trigger_type": "cron",
        "hour": 16,
        "minute": 5,
        "description": "每个交易日16:05抓取东方财富行业/概念板块资金流数据",
    },
    {
        "id": "update_big_money_evening",
        "name": "国家队托底信号盘后预警",
        "func": "_job_update_big_money",
        "trigger_type": "cron",
        "hour": 20,
        "minute": 30,
        "description": "盘后抓取北向资金 + 核心ETF份额并计算托底大盘信号",
    },
    {
        "id": "update_big_money_morning",
        "name": "国家队托底信号开盘前确认",
        "func": "_job_update_big_money",
        "trigger_type": "cron",
        "hour": 8,
        "minute": 45,
        "description": "开盘前确认最新核心ETF份额并更新托底大盘信号",
    },
]


class DataScheduler:
    """
    Central scheduler that owns an APScheduler BackgroundScheduler
    and exposes helpers for the API layer.
    """

    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone=TZ)
        self._started = False
        self._lock = threading.Lock()
        # In-memory ring buffer of recent run summaries (last 100)
        self._recent_runs: deque = deque(maxlen=100)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the scheduler and register default jobs."""
        with self._lock:
            if self._started:
                return
            self._register_default_jobs()
            self._scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
            self._scheduler.start()
            self._started = True
            logger.info("DataScheduler started (tz=%s)", TZ)

    def stop(self):
        """Gracefully shut down."""
        with self._lock:
            if not self._started:
                return
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("DataScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._started

    # ------------------------------------------------------------------
    # Job registration
    # ------------------------------------------------------------------

    def _register_default_jobs(self):
        """Register the built-in daily jobs."""
        job_funcs = {
            "_job_update_crypto": self._job_update_crypto,
            "_job_update_us_market": self._job_update_us_market,
            "_job_sync_sectors_weekly": self._job_sync_sectors_weekly,
            "_job_update_sector_flow": self._job_update_sector_flow,
            "_job_update_big_money": self._job_update_big_money,
        }
        for job_def in DEFAULT_JOBS:
            func = job_funcs[job_def["func"]]
            if job_def.get("trigger_type") == "cron":
                trigger_kwargs = {"timezone": TZ}
                if "day_of_week" in job_def:
                    trigger_kwargs["day_of_week"] = job_def["day_of_week"]
                if "hour" in job_def:
                    trigger_kwargs["hour"] = job_def["hour"]
                if "minute" in job_def:
                    trigger_kwargs["minute"] = job_def["minute"]
                trigger = CronTrigger(**trigger_kwargs)
            else:
                trigger = CronTrigger(hour=job_def["hour"], minute=job_def["minute"], timezone=TZ)
            self._scheduler.add_job(
                func,
                trigger=trigger,
                id=job_def["id"],
                name=job_def["name"],
                replace_existing=True,
                misfire_grace_time=3600,  # allow 1h late execution
            )
            logger.info(
                "Registered job %s → %s",
                job_def["id"], str(trigger),
            )

    # ------------------------------------------------------------------
    # Job implementations
    # ------------------------------------------------------------------

    def _job_update_crypto(self):
        """Update crypto prices + BTC Fear & Greed indicator."""
        job_id = "update_crypto"
        run_log = self._start_run_log(job_id, "加密货币每日更新")
        results: Dict[str, Any] = {"prices": [], "indicators": []}

        try:
            db = SessionLocal()
            try:
                # 1. Find all active crypto assets
                crypto_assets = (
                    db.query(Asset)
                    .filter(Asset.asset_type == "crypto", Asset.is_active == True)
                    .all()
                )
                asset_ids = [a.id for a in crypto_assets]
                
                # Group by data source for reporting
                yf_assets = [a for a in crypto_assets if a.data_source == "yfinance"]
                binance_assets = [a for a in crypto_assets if a.data_source == "binance"]
            finally:
                db.close()

            if not asset_ids:
                results["message"] = "No active crypto assets found"
                self._finish_run_log(run_log, "success", results)
                return

            # 2. Incremental price update (multi-source)
            logger.info("[%s] Updating prices for %s assets (yfinance: %s, binance: %s)", 
                       job_id, len(asset_ids), len(yf_assets), len(binance_assets))
            
            price_results = incremental_update_multi_source(
                asset_ids=asset_ids, 
                lookback_days=5
            )
            results["prices"] = self._summarise_price_results(price_results)
            
            # Report by source
            yf_results = [r for r in price_results if r.get("source") == "yfinance" or "yfinance" in str(r.get("symbol", "")).lower()]
            binance_results = [r for r in price_results if r.get("source") == "binance"]
            results["by_source"] = {
                "yfinance": {"count": len(yf_results), "success": sum(1 for r in yf_results if r["status"] == "success")},
                "binance": {"count": len(binance_results), "success": sum(1 for r in binance_results if r["status"] == "success")}
            }

            # 3. Update BTC Fear & Greed indicator
            indicator_results = self._update_indicators_for_assets(asset_ids, ["BTC_FEAR_GREED"])
            results["indicators"] = indicator_results

            self._finish_run_log(run_log, "success", results)
            logger.info("[%s] Done: %s", job_id, results)

        except Exception as e:
            logger.exception("[%s] Failed", job_id)
            self._finish_run_log(run_log, "error", results, str(e))

    def _job_update_us_market(self):
        """Update US stock/ETF prices + VIX indicator."""
        job_id = "update_us_market"
        run_log = self._start_run_log(job_id, "美股每日更新")
        results: Dict[str, Any] = {"prices": [], "indicators": []}

        try:
            db = SessionLocal()
            try:
                # 1. Find all active stock/etf/index/equity assets
                us_assets = (
                    db.query(Asset)
                    .filter(
                        Asset.asset_type.in_(["stock", "etf", "index", "equity"]),
                        Asset.is_active == True,
                    )
                    .all()
                )
                asset_ids = [a.id for a in us_assets]
            finally:
                db.close()

            if not asset_ids:
                results["message"] = "No active US market assets found"
                self._finish_run_log(run_log, "success", results)
                return

            # 2. Incremental price update
            logger.info("[%s] Updating prices for %s", job_id, asset_ids)
            price_results = incremental_update(asset_ids=asset_ids, lookback_days=5)
            results["prices"] = self._summarise_price_results(price_results)

            # 3. Update VIX / VXN / VXD / OVX / GVZ + CNN Fear & Greed indicators
            indicator_results = self._update_indicators_for_assets(
                asset_ids, ["VIX", "VXN", "VXD", "OVX", "GVZ", "CNN_FEAR_GREED"]
            )
            results["indicators"] = indicator_results

            self._finish_run_log(run_log, "success", results)
            logger.info("[%s] Done: %s", job_id, results)

        except Exception as e:
            logger.exception("[%s] Failed", job_id)
            self._finish_run_log(run_log, "error", results, str(e))

    def _job_sync_sectors_weekly(self):
        """Sync sectors, industries and top companies from yfinance."""
        job_id = "sync_sectors_weekly"
        run_log = self._start_run_log(job_id, "Sector/Industry 每周同步")
        results: Dict[str, Any] = {}

        try:
            from app.services.sector_sync import sync_all

            logger.info("[%s] Starting sector sync...", job_id)
            results = sync_all()
            status = "success" if all(r["status"] == "success" for r in results.values()) else "partial"
            self._finish_run_log(run_log, status, results)
            logger.info("[%s] Done", job_id)

        except Exception as e:
            logger.exception("[%s] Failed", job_id)
            self._finish_run_log(run_log, "error", results, str(e))

    def _job_update_sector_flow(self):
        """Fetch A-share industry/concept sector fund flow from 东方财富 via AkShare."""
        job_id = "update_sector_flow"
        run_log = self._start_run_log(job_id, "A股板块资金流每日更新")
        results: Dict[str, Any] = {}

        try:
            from app.fetchers.akshare_fetcher import run_daily_sector_flow_job
            results = run_daily_sector_flow_job()
            status = "success" if results.get("industry", {}).get("fetched", 0) > 0 else "error"
            self._finish_run_log(run_log, status, results)
            logger.info("[%s] Done: %s", job_id, results)

        except Exception as e:
            logger.exception("[%s] Failed", job_id)
            self._finish_run_log(run_log, "error", results, str(e))

    def _job_update_big_money(self):
        """Fetch daily big-money inputs and calculate support signal."""
        job_id = "update_big_money"
        run_log = self._start_run_log(job_id, "国家队托底信号更新")
        results: Dict[str, Any] = {}

        try:
            from app.fetchers.akshare_fetcher import fetch_northbound_today, fetch_etf_shares_for_date
            from app.services.big_money_signal import calculate_latest_signal

            results["northbound"] = fetch_northbound_today()
            results["etf_shares"] = fetch_etf_shares_for_date()
            results["signal"] = calculate_latest_signal()
            status = "success" if results.get("signal") else "partial"
            self._finish_run_log(run_log, status, results)
            logger.info("[%s] Done: %s", job_id, results)

        except Exception as e:
            logger.exception("[%s] Failed", job_id)
            self._finish_run_log(run_log, "error", results, str(e))

    # ------------------------------------------------------------------
    # Indicator helpers
    # ------------------------------------------------------------------

    def _update_indicators_for_assets(
        self, asset_ids: List[str], template_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Update indicators matching given templates for given assets."""
        results = []
        db = SessionLocal()
        try:
            indicators = (
                db.query(Indicator)
                .filter(
                    Indicator.asset_id.in_(asset_ids),
                    Indicator.template_id.in_(template_ids),
                    Indicator.is_active == True,
                )
                .all()
            )

            for ind in indicators:
                template_id = ind.template_id
                try:
                    # External indicators are fetched from APIs
                    if template_id == "BTC_FEAR_GREED":
                        r = fetch_latest_external_indicator("fear_greed", ind.id)
                    elif template_id == "VIX":
                        r = calculate_indicator_latest(ind.id)
                    else:
                        r = calculate_indicator_latest(ind.id)

                    results.append({
                        "indicator_id": ind.id,
                        "name": ind.name,
                        "template_id": template_id,
                        "status": r.get("status", "unknown"),
                        "value": r.get("value"),
                        "value_text": r.get("value_text"),
                        "date": r.get("date"),
                    })
                except Exception as e:
                    results.append({
                        "indicator_id": ind.id,
                        "name": ind.name,
                        "template_id": template_id,
                        "status": "error",
                        "error": str(e),
                    })
        finally:
            db.close()

        return results

    # ------------------------------------------------------------------
    # Run log persistence
    # ------------------------------------------------------------------

    def _start_run_log(self, job_id: str, job_name: str) -> SchedulerRunLog:
        """Create a run-log entry with status=running."""
        db = SessionLocal()
        try:
            log = SchedulerRunLog(
                job_id=job_id,
                job_name=job_name,
                started_at=datetime.utcnow(),
                status="running",
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            return log
        except Exception:
            db.rollback()
            # Return a detached object so the rest still works
            return SchedulerRunLog(
                id=0, job_id=job_id, job_name=job_name,
                started_at=datetime.utcnow(), status="running",
            )
        finally:
            db.close()

    def _finish_run_log(
        self,
        log: SchedulerRunLog,
        status: str,
        result: Optional[Dict] = None,
        error_message: Optional[str] = None,
    ):
        """Update the run-log entry with final status."""
        now = datetime.utcnow()
        duration = (now - log.started_at).total_seconds() if log.started_at else 0

        # Persist
        if log.id:
            db = SessionLocal()
            try:
                db_log = db.query(SchedulerRunLog).filter(SchedulerRunLog.id == log.id).first()
                if db_log:
                    db_log.finished_at = now
                    db_log.duration_seconds = duration
                    db_log.status = status
                    db_log.result = result
                    db_log.error_message = error_message
                    db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

        # Also keep in memory ring buffer
        self._recent_runs.append({
            "id": log.id,
            "job_id": log.job_id,
            "job_name": log.job_name,
            "started_at": log.started_at.isoformat() if log.started_at else None,
            "finished_at": now.isoformat(),
            "duration_seconds": round(duration, 2),
            "status": status,
            "error_message": error_message,
        })

    # ------------------------------------------------------------------
    # APScheduler event listener
    # ------------------------------------------------------------------

    def _on_job_event(self, event: JobExecutionEvent):
        """Called by APScheduler after each job execution."""
        if event.exception:
            logger.error("Job %s raised exception: %s", event.job_id, event.exception)
        else:
            logger.info("Job %s finished OK", event.job_id)

    # ------------------------------------------------------------------
    # Helpers for price results
    # ------------------------------------------------------------------

    @staticmethod
    def _summarise_price_results(results: List[Dict]) -> List[Dict[str, Any]]:
        """Turn raw incremental_update results into a compact summary."""
        summary = []
        for r in results:
            summary.append({
                "asset_id": r.get("asset_id"),
                "status": r.get("status"),
                "inserted": r.get("inserted", 0),
                "updated": r.get("updated", 0),
                "records": r.get("records", 0),
            })
        return summary

    # ------------------------------------------------------------------
    # Public API helpers (called from the router)
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return scheduler status + job list."""
        jobs = []
        if self._started:
            for job in self._scheduler.get_jobs():
                next_run = job.next_run_time
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run.isoformat() if next_run else None,
                    "trigger": str(job.trigger),
                    "status": "active" if next_run else "paused",
                })
        return {
            "running": self._started,
            "job_count": len(jobs),
            "jobs": jobs,
            "timezone": TZ,
        }

    def get_run_history(self, limit: int = 20, job_id: Optional[str] = None) -> List[Dict]:
        """Get recent run logs from database."""
        db = SessionLocal()
        try:
            query = db.query(SchedulerRunLog).order_by(SchedulerRunLog.started_at.desc())
            if job_id:
                query = query.filter(SchedulerRunLog.job_id == job_id)
            logs = query.limit(limit).all()
            return [
                {
                    "id": l.id,
                    "job_id": l.job_id,
                    "job_name": l.job_name,
                    "started_at": l.started_at.isoformat() if l.started_at else None,
                    "finished_at": l.finished_at.isoformat() if l.finished_at else None,
                    "duration_seconds": l.duration_seconds,
                    "status": l.status,
                    "result": l.result,
                    "error_message": l.error_message,
                }
                for l in logs
            ]
        finally:
            db.close()

    def run_job_now(self, job_id: str) -> Dict[str, Any]:
        """Manually trigger a job in a background thread."""
        job_funcs = {
            "update_crypto": self._job_update_crypto,
            "update_us_market": self._job_update_us_market,
            "sync_sectors_weekly": self._job_sync_sectors_weekly,
            "update_sector_flow": self._job_update_sector_flow,
            "update_big_money_evening": self._job_update_big_money,
            "update_big_money_morning": self._job_update_big_money,
            "update_big_money": self._job_update_big_money,
        }
        func = job_funcs.get(job_id)
        if not func:
            return {"job_id": job_id, "message": f"Unknown job: {job_id}"}

        thread = threading.Thread(target=func, name=f"manual-{job_id}", daemon=True)
        thread.start()
        return {"job_id": job_id, "message": f"Job {job_id} triggered (running in background)"}

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        try:
            self._scheduler.pause_job(job_id)
            logger.info("Paused job %s", job_id)
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        try:
            self._scheduler.resume_job(job_id)
            logger.info("Resumed job %s", job_id)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_data_scheduler: Optional[DataScheduler] = None


def get_data_scheduler() -> DataScheduler:
    """Get or create the global DataScheduler instance."""
    global _data_scheduler
    if _data_scheduler is None:
        _data_scheduler = DataScheduler()
    return _data_scheduler
