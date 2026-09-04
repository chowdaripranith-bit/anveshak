from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import DetectionEvent
from app.schemas.domain import (
    DetectionEventResponse,
    DetectionEventCreate,
    SimulatedEventRequest,
    DetectionProcessResult,
)
from app.services.detection.processor import process_detection_event
from typing import List, Optional

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/", response_model=List[DetectionEventResponse])
async def get_events(limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DetectionEvent).order_by(DetectionEvent.timestamp.desc()).limit(limit))
    return result.scalars().all()


@router.get("/{event_id}", response_model=DetectionEventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    event = await db.get(DetectionEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/detect", response_model=DetectionProcessResult)
async def ingest_detection_event(event_in: DetectionEventCreate):
    """Ingest a detected event from the computer-vision/detection layer.
    Security-sensitive events are forwarded to Featherless AI for
    incident classification, severity scoring, and alert broadcast.
    """
    result = await process_detection_event(
        detected_object=event_in.object_type or event_in.event_type,
        confidence=event_in.confidence,
        incident_type=event_in.event_type,
        camera_id=event_in.camera_id,
        other_info={
            "tracking_id": event_in.tracking_id,
            "activity_type": event_in.activity_type,
            "weapon_type": event_in.weapon_type,
            "evidence_id": event_in.evidence_id,
            "evidence_path": event_in.evidence_path,
            "description": event_in.description,
        },
    )
    return result


@router.post("/simulate", response_model=DetectionProcessResult)
async def simulate_detection_event(sim_event: SimulatedEventRequest):
    """Simulate a detection event (e.g. knife with 0.91 confidence) to test
    the detection -> Featherless AI analysis -> Alert pipeline.
    """
    result = await process_detection_event(
        detected_object=sim_event.object_detected,
        confidence=sim_event.confidence,
        incident_type=sim_event.incident_type,
        camera_id=sim_event.camera_id,
        timestamp=sim_event.timestamp,
        other_info=sim_event.other_info,
    )
    return result
