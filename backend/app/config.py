from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import json


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/anveshak"

    JWT_SECRET: str = "supersecretjwtkey"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    FEATHERLESS_API_KEY: str = ""
    FEATHERLESS_MODEL: str = ""

    YOLO_MODEL_PATH: str = "models/human/yolov8n.pt"
    WEAPON_MODEL_PATH: str = "models/weapons/weapon_model.pt"

    PERSON_CONFIDENCE_THRESHOLD: float = 0.5
    WEAPON_CONFIDENCE_THRESHOLD: float = 0.5
    THEFT_CONFIDENCE_THRESHOLD: float = 0.6
    SUSPICIOUS_ACTIVITY_THRESHOLD: float = 0.6

    ALERT_COOLDOWN_SECONDS: int = 10
    MAX_UPLOAD_SIZE: int = 52428800
    CORS_ORIGINS: List[str] = ["*"]

    CAMERA_SOURCE: str = "0"
    CAMERA_FRAME_SKIP: int = 5
    CAMERA_DETECTION_CONFIDENCE: float = 0.4

    EVIDENCE_RETENTION_DAYS: int = 30
    EVIDENCE_FOLDER: str = "evidence"

    # Rack Zone Configuration (Normalized coordinates 0.0 to 1.0)
    RACK_ZONE_ID: str = "rack_zone_1"
    RACK_ZONE_NAME: str = "Main_Display_Rack_1"
    RACK_ZONE_X1: float = 0.25
    RACK_ZONE_Y1: float = 0.20
    RACK_ZONE_X2: float = 0.75
    RACK_ZONE_Y2: float = 0.80

    # Theft Detection Thresholds
    THEFT_MIN_INTERACTION_SECONDS: float = 2.0
    THEFT_PROXIMITY_MARGIN: float = 0.05
    THEFT_COOLDOWN_SECONDS: int = 15
    THEFT_CONCEALMENT_CHECK_ENABLED: bool = True

    # Suspicious Activity Thresholds
    LOITERING_THRESHOLD_SECONDS: float = 10.0
    PROLONGED_PRESENCE_SECONDS: float = 20.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
