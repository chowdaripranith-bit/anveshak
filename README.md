# 🛡️ Anveshak — AI-Powered Security Monitoring System

> Real-time security surveillance powered by YOLOv8 + Featherless AI (Qwen 2.5-7B)

![Dashboard](docs/dashboard_preview.png)

## Overview

**Anveshak** is a full-stack, AI-driven security monitoring system that watches a live camera feed and automatically detects, classifies, and alerts on security threats in real time.

### Key Features

| Feature | Details |
|---|---|
| 🎥 **Live Camera Stream** | MJPEG stream from webcam with camera ON/OFF power control |
| 👤 **Person Detection & Tracking** | YOLOv8n + custom ByteTrack-inspired PersonTracker |
| 🔪 **Weapon Detection** | Knife & Gun detection via dedicated weapon model |
| 🚨 **Suspicious Activity** | Loitering, prolonged presence, restricted-area entry |
| 🛒 **Theft Detection** | Behavioral theft pattern recognition |
| 📸 **Evidence Snapshots** | Auto-captures JPEG frames at moment of detection |
| 🤖 **AI Analysis** | Featherless AI (Qwen 2.5-7B) classifies incidents & recommends actions |
| ⚡ **Real-time Alerts** | WebSocket push alerts to dashboard instantly |
| 📊 **Security Dashboard** | Professional black-theme UI with incident feed |

## Tech Stack

**Backend**
- Python 3.11 + FastAPI + Uvicorn
- YOLOv8 (Ultralytics) for object detection
- OpenCV for camera capture & frame processing
- SQLAlchemy + Alembic (async SQLite)
- WebSockets for real-time alert broadcasting
- Featherless AI API for incident classification

**Frontend**
- Vanilla HTML5 / CSS3 / JavaScript (no framework)
- MJPEG live video stream
- WebSocket real-time updates
- California FB font, dark professional theme

## Project Structure

```
anveshak/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routers (alerts, cameras, events, evidence)
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   ├── services/
│   │   │   ├── detection/  # CameraWorker, DetectionProcessor
│   │   │   ├── threat/     # WeaponDetector
│   │   │   ├── tracking/   # PersonTracker
│   │   │   └── featherless.py  # Featherless AI client
│   │   ├── websocket/      # WebSocket alert manager
│   │   ├── workers/        # CameraManager lifecycle
│   │   ├── config.py
│   │   └── main.py
│   ├── alembic/            # DB migrations
│   ├── tests/              # Test suite
│   ├── .env.example        # Environment variable template
│   ├── alembic.ini
│   └── requirements.txt (or pyproject.toml)
└── frontend/
    ├── index.html
    ├── index.css
    └── app.js
```

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/chowdaripranith-bit/anveshak.git
cd anveshak
```

### 2. Backend setup
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env and add your Featherless API key
```

### 4. Run database migrations
```bash
alembic upgrade head
```

### 5. Download YOLOv8 model
```bash
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
# Place any weapon model at: models/weapons/weapon_model.pt
```

### 6. Start the backend
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 7. Open the dashboard
Open `frontend/index.html` in your browser, or serve it:
```bash
cd ../frontend
npx serve .
```
Then visit: http://127.0.0.1:8000/dashboard/

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/stream` | Live MJPEG camera stream |
| `POST` | `/api/camera/start` | Power on camera worker |
| `POST` | `/api/camera/stop` | Power off camera & release webcam |
| `GET` | `/api/camera/status` | Camera worker status |
| `GET` | `/api/alerts/` | List all security alerts |
| `POST` | `/api/events/simulate` | Simulate a detection event (testing) |
| `GET` | `/evidence/{category}/{filename}` | Serve evidence snapshot |
| `WS` | `/ws/alerts` | WebSocket — real-time alert stream |

## Detection Categories

- **Weapons**: `knife`, `gun` / `firearm` *(grenade/explosive intentionally excluded)*
- **Theft**: Behavioral theft pattern (`person_theft_behavior`)
- **Suspicious**: `loitering`, `prolonged_presence`, `restricted_area_entry`, `abnormal_movement`

## License

MIT License — see [LICENSE](LICENSE) for details.
