"""Enterprise knowledge API — ad-hoc search + document catalog."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..knowledge.store import index
from ..models import KnowledgeDoc
from ..schemas import KnowledgeHit

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search", response_model=list[KnowledgeHit])
async def search(q: str = Query(..., min_length=2), k: int = 4) -> list[KnowledgeHit]:
    hits = await index.search(q, k=k)
    return [KnowledgeHit(**h.__dict__) for h in hits]


@router.get("/docs")
def list_docs(db: Session = Depends(get_db)) -> list[dict]:
    docs = db.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.title)).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "doc_type": d.doc_type,
            "source": d.source,
            "mime": d.mime,
            "url": d.url,
        }
        for d in docs
    ]


@router.get("/status")
def status() -> dict:
    return {"backend": index.mode, "chunks": len(index.chunks)}
