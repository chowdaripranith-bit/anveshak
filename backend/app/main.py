import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.workers.camera import camera_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup: launch camera worker
    await camera_manager.startup()
    yield
    # Shutdown: stop camera worker gracefully
    await camera_manager.shutdown()


app = FastAPI(
    title="Security Monitoring API",
    description="Backend for AI-based Human, Suspicious Activity, Theft & Weapon Detection System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(os.path.join(settings.EVIDENCE_FOLDER, "suspicious"), exist_ok=True)
os.makedirs(os.path.join(settings.EVIDENCE_FOLDER, "theft"), exist_ok=True)
os.makedirs(os.path.join(settings.EVIDENCE_FOLDER, "weapons"), exist_ok=True)
os.makedirs(os.path.join(settings.EVIDENCE_FOLDER, "critical"), exist_ok=True)

from app.api import alerts, dashboard, evidence, events, cameras, featherless
from fastapi import WebSocket, WebSocketDisconnect
from app.websocket.alerts import manager

app.include_router(dashboard.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(cameras.router, prefix="/api")
app.include_router(featherless.router, prefix="/api")


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# MJPEG live camera stream
# ---------------------------------------------------------------------------
from fastapi.responses import StreamingResponse
import numpy as np


# Pre-encode placeholders once to avoid OpenCV overhead in the async generator
def _create_placeholder_jpeg(text: str = "CAMERA OFFLINE") -> bytes:
    try:
        import cv2 as _cv2
        img = np.full((240, 320, 3), 16, dtype=np.uint8)
        _cv2.putText(
            img, text,
            (25, 125), _cv2.FONT_HERSHEY_SIMPLEX, 0.62, (150, 150, 150), 1, _cv2.LINE_AA,
        )
        ok, buf = _cv2.imencode(".jpg", img, [_cv2.IMWRITE_JPEG_QUALITY, 60])
        return buf.tobytes() if ok else b""
    except Exception:
        return b""

_PLACEHOLDER_OFFLINE_JPEG: bytes = _create_placeholder_jpeg("CAMERA OFF (STANDBY)")
_PLACEHOLDER_INIT_JPEG: bytes = _create_placeholder_jpeg("CAMERA INITIALISING...")


async def _mjpeg_frame_generator():
    """
    Yield MJPEG boundary frames from the CameraWorker frame buffer.
    When camera is off/stopped, does not capture hardware frames and serves offline placeholder.
    When camera is on/running, streams live video frames at ~25 fps.
    """
    boundary = b"--frame"

    while True:
        payload = None
        sleep_sec = 0.04

        if camera_manager.is_running and camera_manager._worker is not None:
            raw = camera_manager._worker.get_latest_frame()
            payload = raw if raw else _PLACEHOLDER_INIT_JPEG
            sleep_sec = 0.04
        else:
            payload = _PLACEHOLDER_OFFLINE_JPEG
            sleep_sec = 0.25

        if payload:
            yield (
                boundary
                + b"\r\nContent-Type: image/jpeg\r\n"
                + b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
                + payload
                + b"\r\n"
            )

        await asyncio.sleep(sleep_sec)


@app.get("/api/stream")
async def mjpeg_stream():
    """Live MJPEG stream sourced from the CameraWorker frame buffer."""
    return StreamingResponse(
        _mjpeg_frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
def read_root():
    return {"message": "Security Monitoring Backend is running"}


@app.get("/api/camera/status")
def camera_status():
    """Check whether the camera worker is currently active."""
    return {
        "camera_worker_running": camera_manager.is_running,
        "camera_source": settings.CAMERA_SOURCE,
        "frame_skip": settings.CAMERA_FRAME_SKIP,
        "detection_confidence": settings.CAMERA_DETECTION_CONFIDENCE,
    }


@app.post("/api/camera/start")
async def start_camera():
    """Start the camera worker and begin live capture."""
    await camera_manager.startup()
    return {
        "status": "success",
        "message": "Camera started",
        "camera_worker_running": camera_manager.is_running,
    }


@app.post("/api/camera/stop")
async def stop_camera():
    """Stop the camera worker and release the webcam device."""
    await camera_manager.shutdown()
    return {
        "status": "success",
        "message": "Camera stopped",
        "camera_worker_running": camera_manager.is_running,
    }


@app.post("/api/camera/toggle")
async def toggle_camera():
    """Toggle camera between active and standby."""
    if camera_manager.is_running:
        await camera_manager.shutdown()
    else:
        await camera_manager.startup()
    return {
        "status": "success",
        "camera_worker_running": camera_manager.is_running,
    }


# Mount Frontend Dashboard & Evidence for Local Server
from fastapi.staticfiles import StaticFiles

frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/dashboard", StaticFiles(directory=frontend_dir, html=True), name="dashboard")

from fastapi.responses import FileResponse
from fastapi import HTTPException

@app.get("/evidence/{file_path:path}")
async def get_evidence_file_endpoint(file_path: str):
    """Serve evidence JPEG snapshots with subfolder fallback."""
    full_path = os.path.join(settings.EVIDENCE_FOLDER, file_path)
    if os.path.isfile(full_path):
        return FileResponse(full_path, media_type="image/jpeg")

    fname = os.path.basename(file_path)
    for sub in ["weapons", "theft", "suspicious", "critical"]:
        cand = os.path.join(settings.EVIDENCE_FOLDER, sub, fname)
        if os.path.isfile(cand):
            return FileResponse(cand, media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="Evidence file not found")

if os.path.exists(settings.EVIDENCE_FOLDER):
    app.mount("/evidence", StaticFiles(directory=settings.EVIDENCE_FOLDER), name="evidence")
