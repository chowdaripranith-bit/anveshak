import pytest
from fastapi.testclient import TestClient
from app.main import app
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

client = TestClient(app)


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Security Monitoring Backend is running"


def test_evidence_dir_creation():
    assert os.path.exists("evidence/suspicious")
    assert os.path.exists("evidence/theft")
    assert os.path.exists("evidence/weapons")
    assert os.path.exists("evidence/critical")
