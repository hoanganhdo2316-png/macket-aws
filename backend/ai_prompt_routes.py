import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/api/admin/ai-prompts", tags=["AI Prompts"])


def require_admin(x_admin_token: str | None = Header(default=None)):
    expected = os.environ.get("ADMIN_API_TOKEN")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


class CreatePrompt(BaseModel):
    system_prompt: str = Field(min_length=1)
    description: str | None = None


def get_engine():
    from main import engine
    return engine


@router.get("", dependencies=[Depends(require_admin)])
def list_prompts():
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT id, version, description, is_active, created_at
            FROM ai_prompt_versions
            ORDER BY version DESC
        """)).mappings().all()
        return [dict(row) for row in rows]


@router.get("/active", dependencies=[Depends(require_admin)])
def get_active_prompt():
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT id, version, system_prompt, description,
                   is_active, created_at
            FROM ai_prompt_versions
            WHERE is_active = TRUE
        """)).mappings().first()
        return dict(row) if row else None


@router.get("/{prompt_id}", dependencies=[Depends(require_admin)])
def get_prompt(prompt_id: int):
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT id, version, system_prompt, description,
                   is_active, created_at
            FROM ai_prompt_versions
            WHERE id = :id
        """), {"id": prompt_id}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return dict(row)


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
def create_prompt(payload: CreatePrompt):
    content = payload.system_prompt.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")

    engine = get_engine()

    # Serialize version allocation to avoid duplicate versions.
    with engine.begin() as conn:
        conn.execute(text("""
            SELECT pg_advisory_xact_lock(20261120, 1)
        """))

        version = conn.execute(text("""
            SELECT COALESCE(MAX(version), 0) + 1
            FROM ai_prompt_versions
        """)).scalar_one()

        row = conn.execute(text("""
            INSERT INTO ai_prompt_versions
                (version, system_prompt, description)
            VALUES (:version, :prompt, :description)
            RETURNING id, version, description, is_active, created_at
        """), {
            "version": version,
            "prompt": content,
            "description": payload.description,
        }).mappings().one()

        return dict(row)


@router.post("/{prompt_id}/activate", dependencies=[Depends(require_admin)])
def activate_prompt(prompt_id: int):
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("""
            SELECT pg_advisory_xact_lock(20261120, 1)
        """))

        exists = conn.execute(text("""
            SELECT id FROM ai_prompt_versions WHERE id = :id
        """), {"id": prompt_id}).first()

        if not exists:
            raise HTTPException(status_code=404, detail="Prompt not found")

        conn.execute(text("""
            UPDATE ai_prompt_versions
            SET is_active = FALSE
            WHERE is_active = TRUE
        """))

        row = conn.execute(text("""
            UPDATE ai_prompt_versions
            SET is_active = TRUE
            WHERE id = :id
            RETURNING id, version, description, is_active, created_at
        """), {"id": prompt_id}).mappings().one()

        return dict(row)
