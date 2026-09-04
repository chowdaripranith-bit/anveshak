from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
from datetime import datetime


class EvidenceBase(BaseModel):
    file_path: str
    media_type: str = "image"


class EvidenceResponse(EvidenceBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class CameraBase(BaseModel):
    name: str
    stream_url: str
    location: Optional[str] = None
    is_active: bool = True


class CameraCreate(CameraBase):
    pass


class CameraResponse(CameraBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class DetectionEventBase(BaseModel):
    camera_id: int
    tracking_id: Optional[int] = None
    event_type: str
    activity_type: Optional[str] = None
    weapon_type: Optional[str] = None
    object_type: Optional[str] = None
    confidence: float
    risk_score: Optional[float] = None
    threat_level: Optional[str] = None
    evidence_id: Optional[int] = None
    evidence_path: Optional[str] = None
    description: Optional[str] = None
    status: str = "NEW"


class DetectionEventCreate(DetectionEventBase):
    pass


class DetectionEventResponse(DetectionEventBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class AlertBase(BaseModel):
    event_id: int
    camera_id: int
    threat_level: str
    message: str
    is_read: bool = False
    evidence_id: Optional[int] = None


class AlertCreate(AlertBase):
    pass


class AlertResponse(AlertBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_cameras: int
    active_cameras: int
    humans_detected: int
    weapons_detected: int
    suspicious_activities: int
    theft_events: int
    high_alerts: int
    critical_alerts: int


class SecurityIncidentAnalysisRequest(BaseModel):
    detected_object: Optional[str] = None
    confidence: Optional[float] = None
    incident_type: Optional[str] = None
    timestamp: Optional[Union[datetime, str]] = None
    other_info: Optional[Dict[str, Any]] = None
    raw_prompt: Optional[str] = None


class SecurityIncidentAnalysisResponse(BaseModel):
    status: str
    incident_classification: str
    severity: str
    short_explanation: str
    recommended_action: str
    model: str


class SimulatedEventRequest(BaseModel):
    object_detected: str = "knife"
    confidence: float = 0.91
    incident_type: str = "weapon_detected"
    camera_id: Optional[int] = 1
    timestamp: Optional[str] = None
    other_info: Optional[Dict[str, Any]] = None


class DetectionProcessResult(BaseModel):
    status: str
    security_event: bool
    saved_to_db: bool
    event: Dict[str, Any]
    ai_analysis: Optional[Dict[str, Any]] = None
    alert: Optional[Dict[str, Any]] = None
