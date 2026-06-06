"""Indicator API routes."""
from datetime import date, datetime, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.models.indicator import IndicatorTemplate, Indicator, IndicatorValue
from app.models.asset import Asset
from app.models.price_data import PriceData
from app.schemas.indicator import (
    IndicatorTemplateCreate, IndicatorTemplateUpdate, IndicatorTemplateResponse,
    IndicatorCreate, IndicatorUpdate, IndicatorResponse,
    IndicatorValueResponse, CalculateIndicatorRequest, CalculateIndicatorResponse,
    IndicatorQueryParams
)
from app.indicators.registry import create_processor

router = APIRouter(prefix="/indicators", tags=["indicators"])


# ============ Template Routes ============

@router.post("/templates", response_model=IndicatorTemplateResponse)
def create_template(template: IndicatorTemplateCreate, db: Session = Depends(get_db)):
    """Create a new indicator template."""
    db_template = db.query(IndicatorTemplate).filter(IndicatorTemplate.id == template.id).first()
    if db_template:
        raise HTTPException(status_code=400, detail="Template already exists")
    
    db_template = IndicatorTemplate(**template.model_dump())
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template


@router.get("/templates", response_model=List[IndicatorTemplateResponse])
def list_templates(
    indicator_type: str = None,
    category: str = None,
    skip: int = 0,
    limit: int = 100000,
    db: Session = Depends(get_db)
):
    """List indicator templates."""
    query = db.query(IndicatorTemplate)
    if indicator_type:
        query = query.filter(IndicatorTemplate.indicator_type == indicator_type)
    if category:
        query = query.filter(IndicatorTemplate.category == category)
    return query.offset(skip).limit(limit).all()


@router.get("/templates/{template_id}", response_model=IndicatorTemplateResponse)
def get_template(template_id: str, db: Session = Depends(get_db)):
    """Get indicator template by ID."""
    template = db.query(IndicatorTemplate).filter(IndicatorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/templates/{template_id}", response_model=IndicatorTemplateResponse)
def update_template(template_id: str, template_update: IndicatorTemplateUpdate, db: Session = Depends(get_db)):
    """Update indicator template."""
    template = db.query(IndicatorTemplate).filter(IndicatorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    update_data = template_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)
    
    db.commit()
    db.refresh(template)
    return template


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    """Delete indicator template."""
    template = db.query(IndicatorTemplate).filter(IndicatorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    db.delete(template)
    db.commit()
    return {"message": "Template deleted successfully"}


# ============ Indicator Instance Routes ============

@router.post("", response_model=IndicatorResponse)
def create_indicator(indicator: IndicatorCreate, db: Session = Depends(get_db)):
    """Create a new indicator instance."""
    # Check template exists
    template = db.query(IndicatorTemplate).filter(IndicatorTemplate.id == indicator.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Check asset exists
    asset = db.query(Asset).filter(Asset.id == indicator.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Check duplicate
    existing = db.query(Indicator).filter(
        Indicator.template_id == indicator.template_id,
        Indicator.asset_id == indicator.asset_id,
        Indicator.name == indicator.name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Indicator already exists")
    
    db_indicator = Indicator(**indicator.model_dump())
    db.add(db_indicator)
    db.commit()
    db.refresh(db_indicator)
    return db_indicator


@router.get("", response_model=List[IndicatorResponse])
def list_indicators(
    asset_id: str = None,
    template_id: str = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List indicator instances."""
    query = db.query(Indicator).join(IndicatorTemplate, Indicator.template_id == IndicatorTemplate.id)
    if asset_id:
        query = query.filter(Indicator.asset_id == asset_id)
    if template_id:
        query = query.filter(Indicator.template_id == template_id)
    return query.order_by(IndicatorTemplate.category, Indicator.template_id, Indicator.id).offset(skip).limit(limit).all()


@router.get("/{indicator_id}", response_model=IndicatorResponse)
def get_indicator(indicator_id: int, db: Session = Depends(get_db)):
    """Get indicator instance by ID."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return indicator


@router.get("/{indicator_id}/config")
def get_indicator_config(
    indicator_id: int,
    db: Session = Depends(get_db)
):
    """Get indicator-specific configuration (e.g., MA200 multipliers)."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    # Return config for MA200 indicators
    if indicator.template and indicator.template.id == "MA200":
        from app.indicators.ma200 import MA200Indicator
        config = MA200Indicator.multiplier_config
        asset_id = indicator.asset_id
        return config.get(asset_id, config.get("default"))

    return {}


@router.put("/{indicator_id}", response_model=IndicatorResponse)
def update_indicator(indicator_id: int, indicator_update: IndicatorUpdate, db: Session = Depends(get_db)):
    """Update indicator instance."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    
    update_data = indicator_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(indicator, field, value)
    
    db.commit()
    db.refresh(indicator)
    return indicator


@router.delete("/{indicator_id}")
def delete_indicator(indicator_id: int, db: Session = Depends(get_db)):
    """Delete indicator instance."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    
    db.delete(indicator)
    db.commit()
    return {"message": "Indicator deleted successfully"}


# ============ Indicator Value Routes ============

@router.get("/{indicator_id}/values", response_model=List[IndicatorValueResponse])
def get_indicator_values(
    indicator_id: int,
    start: date = None,
    end: date = None,
    limit: int = 100,
    auto_fetch: bool = Query(True, description="数据为空时自动获取历史数据"),
    db: Session = Depends(get_db)
):
    """Get indicator values.
    
    - auto_fetch: 如果数据库中没有数据且此参数为 true，自动计算/获取历史数据（默认过去4年）
    """
    import asyncio
    from app.indicators.registry import create_processor
    
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    
    query = db.query(IndicatorValue).filter(IndicatorValue.indicator_id == indicator_id)
    
    if start:
        query = query.filter(IndicatorValue.date >= start)
    if end:
        query = query.filter(IndicatorValue.date <= end)
    
    print(f"[IndicatorValues] indicator_id={indicator_id}, limit={limit}, start={start}, end={end}")
    values = query.order_by(desc(IndicatorValue.date)).limit(limit).all()
    
    # 自动获取数据模式：如果数据库为空且允许自动获取
    if not values and auto_fetch:
        print(f"[Indicator] No data found for indicator {indicator_id}, auto-fetching...")
        
        try:
            template = indicator.template
            if template:
                # 创建处理器
                processor = create_processor(template.processor_class, indicator.params)
                if processor:
                    # 计算过去4年的数据
                    end_date = date.today()
                    start_date = end_date - timedelta(days=4*365)  # 4年
                    
                    results = asyncio.run(processor.calculate(indicator.asset_id, start_date, end_date))
                    
                    if results:
                        # 保存到数据库
                        for result in results:
                            existing = db.query(IndicatorValue).filter(
                                IndicatorValue.indicator_id == indicator_id,
                                IndicatorValue.date == result.date
                            ).first()
                            
                            if existing:
                                existing.value = result.value
                                existing.value_text = result.value_text
                                existing.grade = result.grade
                                existing.grade_label = result.grade_label
                                existing.extra_data = result.extra_data or {}
                            else:
                                db_value = IndicatorValue(
                                    indicator_id=indicator_id,
                                    date=result.date,
                                    timestamp=result.timestamp,
                                    value=result.value,
                                    value_text=result.value_text,
                                    grade=result.grade,
                                    grade_label=result.grade_label,
                                    extra_data=result.extra_data or {},
                                    source="auto_fetch"
                                )
                                db.add(db_value)
                        
                        db.commit()
                        print(f"[Indicator] Auto-fetched {len(results)} values for indicator {indicator_id}")
                        
                        # 重新查询获取最新数据
                        values = query.order_by(desc(IndicatorValue.date)).limit(limit).all()
        except Exception as e:
            print(f"[Indicator] Auto-fetch failed for indicator {indicator_id}: {e}")
            # 不抛出异常，返回空列表
    
    return values[::-1]  # Return in ascending order


# ============ Calculation Routes ============

async def _calculate_indicator_task(indicator_id: int, start: date, end: date):
    """Background task to calculate indicator values."""
    from app.core.database import SessionLocal
    
    db = SessionLocal()
    try:
        indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
        if not indicator:
            return
        
        template = indicator.template
        if not template:
            return
        
        # Create processor
        processor_class = template.processor_class
        # Extract class name from processor_class path
        if "." in processor_class:
            # e.g., "app.indicators.ma200.MA200Indicator" -> get from registry by name
            # The processor should be registered by its name attribute
            from app.indicators.registry import get_processor
            # Map class path to registered name
            processor_name = processor_class.split(".")[-1].replace("Indicator", "")
            processor = create_processor(processor_name, indicator.params)
        else:
            processor = create_processor(processor_class, indicator.params)
        
        if not processor:
            print(f"Processor not found: {processor_class}")
            return
        
        # Calculate values
        results = await processor.calculate(indicator.asset_id, start, end)
        
        # Save to database
        for result in results:
            # Check if value already exists for this date
            existing = db.query(IndicatorValue).filter(
                IndicatorValue.indicator_id == indicator_id,
                IndicatorValue.date == result.date
            ).first()
            
            if existing:
                # Update existing
                existing.value = result.value
                existing.value_text = result.value_text
                existing.grade = result.grade
                existing.grade_label = result.grade_label
                existing.extra_data = result.extra_data or {}
                existing.timestamp = result.timestamp
            else:
                # Create new
                db_value = IndicatorValue(
                    indicator_id=indicator_id,
                    date=result.date,
                    timestamp=result.timestamp,
                    value=result.value,
                    value_text=result.value_text,
                    grade=result.grade,
                    grade_label=result.grade_label,
                    extra_data=result.extra_data or {},
                    source="calculation"
                )
                db.add(db_value)
        
        # Update indicator last calculated
        indicator.last_calculated_at = datetime.utcnow()
        db.commit()
        print(f"Calculated {len(results)} values for indicator {indicator_id}")
        
    except Exception as e:
        print(f"Error calculating indicator {indicator_id}: {e}")
        db.rollback()
    finally:
        db.close()


@router.post("/{indicator_id}/calculate", response_model=CalculateIndicatorResponse)
def calculate_indicator(
    indicator_id: int,
    request: CalculateIndicatorRequest = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """Trigger indicator calculation."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    
    # Determine date range
    end = request.end if request and request.end else datetime.now().date()
    start = request.start if request and request.start else end - timedelta(days=365)
    
    # Run calculation in background
    if background_tasks:
        background_tasks.add_task(_calculate_indicator_task, indicator_id, start, end)
        return CalculateIndicatorResponse(
            indicator_id=indicator_id,
            calculated_count=0,
            message="Calculation started in background"
        )
    else:
        # Synchronous calculation (for testing)
        import asyncio
        asyncio.create_task(_calculate_indicator_task(indicator_id, start, end))
        return CalculateIndicatorResponse(
            indicator_id=indicator_id,
            calculated_count=0,
            message="Calculation started"
        )


@router.get("/{indicator_id}/latest", response_model=IndicatorValueResponse)
def get_latest_value(indicator_id: int, db: Session = Depends(get_db)):
    """Get latest indicator value."""
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    
    value = db.query(IndicatorValue).filter(
        IndicatorValue.indicator_id == indicator_id
    ).order_by(desc(IndicatorValue.date)).first()
    
    if not value:
        raise HTTPException(status_code=404, detail="No value found")
    
    return value


# ============ Recalculate & Price Data Check ============

@router.post("/{indicator_id}/recalculate", response_model=CalculateIndicatorResponse)
def recalculate_indicator(
    indicator_id: int,
    request: CalculateIndicatorRequest = None,
    db: Session = Depends(get_db)
):
    """
    Recalculate indicator values.

    - Clears all existing indicator values
    - Calculates new values for the specified date range (default: past 6 years)
    - Saves results to database
    """
    import asyncio

    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    template = indicator.template
    if not template:
        raise HTTPException(status_code=404, detail="Indicator template not found")

    # Determine date range
    end = request.end if request and request.end else date.today()
    start = request.start if request and request.start else end - timedelta(days=6*365)

    # Create processor
    processor = create_processor(template.processor_class, indicator.params)
    if not processor:
        raise HTTPException(status_code=500, detail=f"Processor not found: {template.processor_class}")

    # Clear existing values
    deleted = db.query(IndicatorValue).filter(IndicatorValue.indicator_id == indicator_id).delete()
    db.commit()
    print(f"[Recalculate] Cleared {deleted} old values for indicator {indicator_id}")

    # Calculate new values
    try:
        results = asyncio.run(processor.calculate(indicator.asset_id, start, end))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calculation failed: {str(e)}")

    if not results:
        raise HTTPException(status_code=500, detail="Calculation returned no data (insufficient price data?)")

    # Save to database
    for result in results:
        db_value = IndicatorValue(
            indicator_id=indicator_id,
            date=result.date,
            timestamp=result.timestamp,
            value=result.value,
            value_text=result.value_text,
            grade=result.grade,
            grade_label=result.grade_label,
            extra_data=result.extra_data or {},
            source="recalculate"
        )
        db.add(db_value)

    indicator.last_calculated_at = datetime.utcnow()
    db.commit()

    return CalculateIndicatorResponse(
        indicator_id=indicator_id,
        calculated_count=len(results),
        message=f"Recalculated {len(results)} values from {start} to {end}"
    )


@router.get("/{indicator_id}/price-data-check")
def check_indicator_price_data(
    indicator_id: int,
    db: Session = Depends(get_db)
):
    """
    Check if the associated asset has enough continuous price data for this indicator.

    Returns:
        - asset_id: associated asset
        - total_records: number of price records
        - earliest_date: earliest price date
        - latest_date: latest price date
        - has_enough_data: whether max continuous span >= 6 years
        - days_coverage: total calendar days covered (earliest -> latest)
        - max_continuous_days: longest gap-free segment
        - max_continuous_start/end: date range of longest continuous segment
        - gaps: list of detected gaps (>5 days between records)
        - needs_backfill: True if max continuous < 6 years or no data
    """
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    asset_id = indicator.asset_id
    if not asset_id:
        return {
            "asset_id": None,
            "total_records": 0,
            "earliest_date": None,
            "latest_date": None,
            "has_enough_data": False,
            "days_coverage": 0,
            "max_continuous_days": 0,
            "max_continuous_start": None,
            "max_continuous_end": None,
            "gaps": [],
            "needs_backfill": False,
            "message": "Global indicator (no associated asset)"
        }

    prices = db.query(PriceData).filter(
        PriceData.asset_id == asset_id,
        PriceData.interval == "1d"
    ).order_by(PriceData.date).all()

    if not prices:
        return {
            "asset_id": asset_id,
            "total_records": 0,
            "earliest_date": None,
            "latest_date": None,
            "has_enough_data": False,
            "days_coverage": 0,
            "max_continuous_days": 0,
            "max_continuous_start": None,
            "max_continuous_end": None,
            "gaps": [],
            "needs_backfill": True,
            "message": "No price data found"
        }

    dates = [p.date for p in prices]
    earliest = dates[0]
    latest = dates[-1]
    days_coverage = (latest - earliest).days + 1

    # Detect gaps (>5 days between consecutive records; covers long weekends/holidays)
    GAP_THRESHOLD = 5
    gaps = []
    continuous_segments = []
    segment_start = dates[0]

    for i in range(1, len(dates)):
        prev_date = dates[i - 1]
        curr_date = dates[i]
        gap_days = (curr_date - prev_date).days - 1

        if gap_days > GAP_THRESHOLD:
            # Close current segment
            segment_end = prev_date
            segment_days = (segment_end - segment_start).days + 1
            continuous_segments.append({
                "start": segment_start,
                "end": segment_end,
                "days": segment_days,
                "records": i - dates.index(segment_start)
            })
            gaps.append({
                "start_date": prev_date.isoformat(),
                "end_date": curr_date.isoformat(),
                "days": gap_days
            })
            # Start new segment
            segment_start = curr_date

    # Close final segment
    segment_end = dates[-1]
    segment_days = (segment_end - segment_start).days + 1
    continuous_segments.append({
        "start": segment_start,
        "end": segment_end,
        "days": segment_days,
        "records": len(dates) - dates.index(segment_start)
    })

    # Find longest continuous segment
    max_segment = max(continuous_segments, key=lambda s: s["days"]) if continuous_segments else None
    max_continuous_days = max_segment["days"] if max_segment else 0
    max_continuous_start = max_segment["start"] if max_segment else None
    max_continuous_end = max_segment["end"] if max_segment else None

    # Require max continuous span >= 6 years (~2190 days) for reliable MA200W etc.
    MIN_REQUIRED_DAYS = 6 * 365
    has_enough = max_continuous_days >= MIN_REQUIRED_DAYS

    if not has_enough:
        message = (
            f"{len(prices)} records, max continuous {max_continuous_days} days "
            f"({max_continuous_start} ~ {max_continuous_end}). "
            f"Need {MIN_REQUIRED_DAYS} continuous days."
        )
    else:
        message = (
            f"{len(prices)} records, {days_coverage} days coverage, "
            f"max continuous {max_continuous_days} days (sufficient)"
        )

    return {
        "asset_id": asset_id,
        "total_records": len(prices),
        "earliest_date": earliest.isoformat(),
        "latest_date": latest.isoformat(),
        "has_enough_data": has_enough,
        "days_coverage": days_coverage,
        "max_continuous_days": max_continuous_days,
        "max_continuous_start": max_continuous_start.isoformat() if max_continuous_start else None,
        "max_continuous_end": max_continuous_end.isoformat() if max_continuous_end else None,
        "gaps": gaps,
        "needs_backfill": not has_enough,
        "message": message
    }


@router.get("/{indicator_id}/price-chart-data")
def get_price_chart_data(
    indicator_id: int,
    start: date = None,
    end: date = None,
    db: Session = Depends(get_db)
):
    """
    Get OHLC price data + MA200W for the indicator's associated asset.

    Returns merged data suitable for candlestick + line chart rendering.
    """
    indicator = db.query(Indicator).filter(Indicator.id == indicator_id).first()
    if not indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    asset_id = indicator.asset_id
    if not asset_id:
        return []

    # Query price data (OHLC)
    price_query = db.query(PriceData).filter(
        PriceData.asset_id == asset_id,
        PriceData.interval == "1d"
    ).order_by(PriceData.date)
    if start:
        price_query = price_query.filter(PriceData.date >= start)
    if end:
        price_query = price_query.filter(PriceData.date <= end)
    prices = price_query.all()

    # Query indicator values for ma_value
    iv_query = db.query(IndicatorValue).filter(
        IndicatorValue.indicator_id == indicator_id
    ).order_by(IndicatorValue.date)
    if start:
        iv_query = iv_query.filter(IndicatorValue.date >= start)
    if end:
        iv_query = iv_query.filter(IndicatorValue.date <= end)
    ivs = iv_query.all()

    # Build ma_value lookup by date
    ma_lookup = {}
    for iv in ivs:
        ma = iv.extra_data.get("ma_value") if iv.extra_data else None
        if ma is not None:
            ma_lookup[iv.date.isoformat()] = float(ma)

    # Merge price data with ma_value
    results = []
    for p in prices:
        results.append({
            "date": p.date.isoformat(),
            "open": float(p.open) if p.open is not None else None,
            "high": float(p.high) if p.high is not None else None,
            "low": float(p.low) if p.low is not None else None,
            "close": float(p.close) if p.close is not None else None,
            "volume": int(p.volume) if p.volume is not None else None,
            "ma_value": ma_lookup.get(p.date.isoformat()),
        })

    return results
