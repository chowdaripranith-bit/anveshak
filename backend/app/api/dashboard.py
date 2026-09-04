from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import Camera, DetectionEvent, Alert
from app.schemas import DashboardStats
from typing import List

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    total_cameras = await db.scalar(select(func.count(Camera.id)))
    active_cameras = await db.scalar(select(func.count(Camera.id)).where(Camera.is_active == True))

    humans_detected = await db.scalar(select(func.count(DetectionEvent.id)).where(DetectionEvent.event_type == "HUMAN_DETECTED"))
    weapons_detected = await db.scalar(select(func.count(DetectionEvent.id)).where(DetectionEvent.event_type == "WEAPON_DETECTED"))
    suspicious_activities = await db.scalar(select(func.count(DetectionEvent.id)).where(DetectionEvent.event_type == "SUSPICIOUS_ACTIVITY"))
    theft_events = await db.scalar(select(func.count(DetectionEvent.id)).where(DetectionEvent.event_type == "THEFT"))

    high_alerts = await db.scalar(select(func.count(Alert.id)).where(Alert.threat_level == "HIGH"))
    critical_alerts = await db.scalar(select(func.count(Alert.id)).where(Alert.threat_level == "CRITICAL"))

    return DashboardStats(
        total_cameras=total_cameras or 0,
        active_cameras=active_cameras or 0,
        humans_detected=humans_detected or 0,
        weapons_detected=weapons_detected or 0,
        suspicious_activities=suspicious_activities or 0,
        theft_events=theft_events or 0,
        high_alerts=high_alerts or 0,
        critical_alerts=critical_alerts or 0,
    )
