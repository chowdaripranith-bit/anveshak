from fastapi import APIRouter
from app.services.featherless import analyze_security_incident
from app.schemas.domain import (
    SecurityIncidentAnalysisRequest,
    SecurityIncidentAnalysisResponse,
)

router = APIRouter(prefix="/featherless", tags=["featherless"])


@router.get("/test", response_model=SecurityIncidentAnalysisResponse)
@router.post("/test", response_model=SecurityIncidentAnalysisResponse)
def test_featherless_connection():
    """Test the Featherless AI integration using the required test prompt:
    'Analyze this security event: a suspicious object was detected.'
    """
    result = analyze_security_incident(
        raw_prompt="Analyze this security event: a suspicious object was detected."
    )
    return result


@router.post("/analyze", response_model=SecurityIncidentAnalysisResponse)
def analyze_incident(request: SecurityIncidentAnalysisRequest):
    """Analyze a security incident with Featherless AI using structured detection details."""
    result = analyze_security_incident(
        detected_object=request.detected_object,
        confidence=request.confidence,
        incident_type=request.incident_type,
        timestamp=request.timestamp,
        other_info=request.other_info,
        raw_prompt=request.raw_prompt,
    )
    return result
