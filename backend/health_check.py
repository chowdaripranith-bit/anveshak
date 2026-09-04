import os
import sys
import time
import requests
import asyncio
import cv2
import numpy as np

# Suppress warnings
import warnings
warnings.filterwarnings("ignore")

print("=== 1. PROJECT STRUCTURE ===")
backend_exists = os.path.isdir("app")
frontend_exists = os.path.isdir("../frontend") or os.path.isdir("../../frontend") # assuming backend is root or sub
print(f"Backend exists: {backend_exists}")

from app.config import settings

print("=== 2. PYTHON ENVIRONMENT ===")
print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")

print("=== 4. FEATHERLESS AI ===")
print("Loaded FEATHERLESS_API_KEY: " + ("YES (Hidden)" if settings.FEATHERLESS_API_KEY else "NO"))
print(f"Loaded FEATHERLESS_MODEL: {settings.FEATHERLESS_MODEL}")

try:
    from app.services.featherless import FeatherlessService
    f_service = FeatherlessService()
    # test a harmless request
    from openai import OpenAI
    client = OpenAI(
        base_url="https://api.featherless.ai/v1",
        api_key=settings.FEATHERLESS_API_KEY
    )
    resp = client.chat.completions.create(
        model=settings.FEATHERLESS_MODEL,
        messages=[{"role": "user", "content": "Say 'hello world' and nothing else."}],
        max_tokens=10
    )
    print(f"Featherless Response SUCCESS: {resp.choices[0].message.content.strip()}")
except Exception as e:
    print(f"Featherless Response FAILURE: {e}")

print("=== 5. CAMERA & 6. YOLO ===")
print(f"CAMERA_SOURCE: {settings.CAMERA_SOURCE}")

from app.services.detection.camera_worker import _CV_BACKEND, CameraWorker
print(f"CV Backend: {'CAP_DSHOW' if _CV_BACKEND == cv2.CAP_DSHOW else 'default'}")

cap = cv2.VideoCapture(int(settings.CAMERA_SOURCE) if str(settings.CAMERA_SOURCE).isdigit() else settings.CAMERA_SOURCE, _CV_BACKEND)
if cap.isOpened():
    print("Camera opened successfully.")
    ret, frame = cap.read()
    if ret and frame is not None:
        print(f"Frame captured successfully. Shape: {frame.shape}")
        
        # Test YOLO
        from ultralytics import YOLO
        try:
            model = YOLO("yolov8n.pt")
            print("YOLO model loaded successfully.")
            results = model(frame, verbose=False)
            print(f"YOLO inference successful. Detected {len(results[0].boxes)} objects.")
            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                label = model.names.get(cls_id, str(cls_id))
                print(f" - {label}: {conf:.2f}")
        except Exception as e:
            print(f"YOLO Error: {e}")
    else:
        print("Camera opened but failed to capture frame.")
    cap.release()
else:
    print("Camera FAILED to open.")

print("=== 7. SECURITY EVENT PIPELINE & 8. SNAPSHOT ===")
async def test_pipeline():
    from app.services.detection.processor import DetectionProcessor
    processor = DetectionProcessor()
    
    # Create fake frame and save snapshot to test #8
    from app.services.detection.camera_worker import _save_snapshot
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    snap_path = _save_snapshot(fake_frame, "knife", "health_test_cam")
    if snap_path and os.path.exists(snap_path):
        print(f"Snapshot saved successfully: {snap_path}")
    else:
        print("Snapshot saving failed.")

    # Test processor #7
    res = await processor.process_event(
        detected_object="knife",
        confidence=0.91,
        incident_type="weapon_detected",
        camera_id=999,
        other_info={"snapshot": snap_path},
        db=None,
        broadcast_alert=False # prevent ws issues during test
    )
    print(f"Pipeline Security Event: {res['security_event']}")
    if res.get("ai_analysis"):
        analysis = res["ai_analysis"]
        print("AI Analysis received:")
        print(f" - Classification: {analysis.get('incident_classification')}")
        print(f" - Severity: {analysis.get('severity')}")
        print(f" - Explanation: {analysis.get('short_explanation')}")
        print(f" - Action: {analysis.get('recommended_action')}")
    else:
        print("AI Analysis failed or skipped.")

asyncio.run(test_pipeline())

