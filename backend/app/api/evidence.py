from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Evidence
from app.schemas import EvidenceResponse
from typing import List
import os

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/", response_model=List[EvidenceResponse])
async def list_evidence(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Evidence).order_by(Evidence.created_at.desc()).limit(limit))
    return result.scalars().all()


@router.get("/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(evidence_id: int, db: AsyncSession = Depends(get_db)):
    evidence = await db.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return evidence


@router.get("/{evidence_id}/file")
async def get_evidence_file(evidence_id: int, db: AsyncSession = Depends(get_db)):
    evidence = await db.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not os.path.exists(evidence.file_path):
        raise HTTPException(status_code=404, detail="Evidence file missing from disk")
    return FileResponse(evidence.file_path)
