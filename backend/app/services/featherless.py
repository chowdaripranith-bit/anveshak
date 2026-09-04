import json
import logging
import re
from typing import Any, Dict, Optional, Union
from datetime import datetime

from openai import OpenAI, APIError, APITimeoutError
from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert AI security monitoring analyst. "
    "Analyze the provided security incident or detection event and respond ONLY with a valid JSON object "
    "containing exactly these keys:\n"
    '- "incident_classification": string (e.g., "WEAPON_DETECTED", "THEFT", "SUSPICIOUS_ACTIVITY", "UNAUTHORIZED_ENTRY", "FALSE_ALARM")\n'
    '- "severity": string ("LOW", "MEDIUM", "HIGH", or "CRITICAL")\n'
    '- "short_explanation": string (concise explanation of the security risk)\n'
    '- "recommended_action": string (immediate actionable protocol for on-site security personnel)\n'
    "Do NOT include any markdown code fences, greetings, or explanations outside the JSON object."
)


class FeatherlessService:
    """Service for interacting with Featherless AI's OpenAI-compatible API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: str = "https://api.featherless.ai/v1",
        timeout: float = 45.0,
    ):
        self.api_key = api_key or settings.FEATHERLESS_API_KEY
        self.model = model or settings.FEATHERLESS_MODEL or "Qwen/Qwen2.5-7B-Instruct"
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        """Lazy instantiation of the OpenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("Featherless API key is not configured.")
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract and parse JSON safely from model response."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError(f"Could not parse response as JSON: {text[:100]}...")

    def analyze_incident(
        self,
        detected_object: Optional[str] = None,
        confidence: Optional[float] = None,
        incident_type: Optional[str] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        other_info: Optional[Dict[str, Any]] = None,
        raw_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a security incident to Featherless AI for analysis.
        
        Accepts structured detection details or a raw event prompt.
        Safely handles errors and timeouts without exposing API keys.
        """
        if not self.api_key:
            return {
                "status": "error",
                "incident_classification": "UNKNOWN",
                "severity": "UNKNOWN",
                "short_explanation": "Featherless API key is not configured.",
                "recommended_action": "Configure FEATHERLESS_API_KEY in backend/.env.",
                "model": self.model,
            }

        if raw_prompt:
            user_message = raw_prompt
        else:
            ts_str = (
                timestamp.isoformat()
                if isinstance(timestamp, datetime)
                else (timestamp or datetime.utcnow().isoformat())
            )
            details = [
                f"Incident Type: {incident_type or 'Unknown'}",
                f"Detected Object: {detected_object or 'Unknown'}",
                f"Detection Confidence: {f'{confidence:.2f}' if confidence is not None else 'N/A'}",
                f"Timestamp: {ts_str}",
            ]
            if other_info:
                details.append(f"Additional Detection Information: {json.dumps(other_info)}")
            user_message = "Analyze this security incident:\n" + "\n".join(details)

        try:
            logger.info("Sending security incident to Featherless AI (model: %s)", self.model)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=350,
            )

            raw_content = response.choices[0].message.content or ""
            parsed = self._extract_json(raw_content)

            return {
                "status": "success",
                "incident_classification": parsed.get("incident_classification", "UNKNOWN"),
                "severity": parsed.get("severity", "MEDIUM"),
                "short_explanation": parsed.get("short_explanation", ""),
                "recommended_action": parsed.get("recommended_action", ""),
                "model": self.model,
            }

        except APITimeoutError:
            logger.error("Featherless AI request timed out.")
            return {
                "status": "error",
                "incident_classification": "TIMEOUT_ERROR",
                "severity": "HIGH",
                "short_explanation": "The security analysis request to Featherless AI timed out.",
                "recommended_action": "Check external API connectivity and retry.",
                "model": self.model,
            }
        except APIError as e:
            logger.error("Featherless API error: %s", getattr(e, "message", str(e)))
            return {
                "status": "error",
                "incident_classification": "API_ERROR",
                "severity": "HIGH",
                "short_explanation": f"Featherless AI API error: {getattr(e, 'message', 'API Error')}",
                "recommended_action": "Verify model availability and API key quota on Featherless AI.",
                "model": self.model,
            }
        except Exception as e:
            logger.error("Unexpected error during Featherless security analysis: %s", str(e))
            return {
                "status": "error",
                "incident_classification": "INTERNAL_ERROR",
                "severity": "MEDIUM",
                "short_explanation": "An unexpected error occurred during incident analysis.",
                "recommended_action": "Inspect backend service logs.",
                "model": self.model,
            }


def analyze_security_incident(
    detected_object: Optional[str] = None,
    confidence: Optional[float] = None,
    incident_type: Optional[str] = None,
    timestamp: Optional[Union[datetime, str]] = None,
    other_info: Optional[Dict[str, Any]] = None,
    raw_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience function to analyze a security incident using default service settings."""
    service = FeatherlessService()
    return service.analyze_incident(
        detected_object=detected_object,
        confidence=confidence,
        incident_type=incident_type,
        timestamp=timestamp,
        other_info=other_info,
        raw_prompt=raw_prompt,
    )
