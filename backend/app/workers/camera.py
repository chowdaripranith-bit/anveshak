"""
Async lifecycle manager for the CameraWorker.

Designed to be called from FastAPI lifespan events:

    async with lifespan(app):
        ...  # startup runs camera_manager.startup()

Or explicitly:

    @app.on_event("startup")
    async def on_startup():
        await camera_manager.startup()

    @app.on_event("shutdown")
    async def on_shutdown():
        await camera_manager.shutdown()
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CameraManager:
    """Manages the lifecycle of the background CameraWorker."""

    def __init__(self):
        self._worker = None
        self._enabled: bool = True

    async def startup(self):
        """Start the camera worker using the current event-loop."""
        self._enabled = True
        if self._worker and self._worker.is_running:
            logger.info("CameraManager: camera worker is already running.")
            return

        try:
            from app.services.detection.camera_worker import CameraWorker

            loop = asyncio.get_running_loop()
            self._worker = CameraWorker(camera_id="camera_0", loop=loop)
            self._worker.start()
            logger.info("CameraManager: worker started successfully.")
        except ImportError as exc:
            logger.warning(
                "CameraManager: could not import CameraWorker (cv2/ultralytics missing?): %s",
                exc,
            )
        except Exception as exc:
            logger.error("CameraManager: startup failed: %s", exc)

    async def shutdown(self):
        """Stop the camera worker gracefully and release the webcam."""
        self._enabled = False
        if self._worker:
            logger.info("CameraManager: stopping worker...")
            worker = self._worker
            self._worker = None
            await asyncio.to_thread(worker.stop)
            logger.info("CameraManager: worker stopped.")
        else:
            logger.info("CameraManager: already stopped.")

    def disable(self):
        """Prevent the worker from starting (useful in tests)."""
        self._enabled = False

    def enable(self):
        self._enabled = True

    @property
    def is_running(self) -> bool:
        return bool(self._worker and self._worker.is_running)

    def capture_current_frame(self):
        """Return the current camera frame as numpy ndarray if worker is running."""
        if self._worker and hasattr(self._worker, "get_latest_raw_frame"):
            return self._worker.get_latest_raw_frame()
        return None


# Singleton used throughout the application
camera_manager = CameraManager()
