import os
import secrets

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/api/admin", tags=["Admin"])


def verify_admin(x_admin_token: str | None = Header(default=None)):
    expected = os.getenv("ADMIN_API_TOKEN")

    if not expected:
        raise HTTPException(503, "Admin API is not configured")

    if not x_admin_token or not secrets.compare_digest(
        x_admin_token, expected
    ):
        raise HTTPException(401, "Unauthorized")


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str
    enabled: bool = True
    max_posts: int | None = Field(default=None, ge=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        from urllib.parse import urlparse
        parsed = urlparse(value.strip())
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ("facebook.com", "www.facebook.com")
            or not parsed.path.startswith("/groups/")
            or not parsed.path.removeprefix("/groups/").strip("/")
        ):
            raise ValueError("Must be a Facebook group HTTPS URL")
        return value.strip()


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = None
    enabled: bool | None = None
    max_posts: int | None = Field(default=None, ge=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        if value is not None:
            GroupCreate(name="validation", url=value)
        return value


def register_admin_routes(app, engine):

    @router.get("/groups", dependencies=[Depends(verify_admin)])
    def list_groups():
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, name, url, enabled, max_posts,
                       created_at, updated_at
                FROM facebook_groups
                ORDER BY id
            """))
            return {"groups": [dict(r) for r in rows.mappings()]}

    @router.post("/groups", status_code=201,
                 dependencies=[Depends(verify_admin)])
    def create_group(data: GroupCreate):
        try:
            with engine.begin() as conn:
                row = conn.execute(text("""
                    INSERT INTO facebook_groups
                        (name, url, enabled, max_posts)
                    VALUES (:name, :url, :enabled, :max_posts)
                    RETURNING id, name, url, enabled, max_posts
                """), data.model_dump()).mappings().one()
                return dict(row)
        except IntegrityError:
            raise HTTPException(409, "Group URL already exists")

    @router.patch("/groups/{group_id}",
                  dependencies=[Depends(verify_admin)])
    def update_group(group_id: int, data: GroupUpdate):
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(400, "No fields provided")
        if any(v is None for k, v in changes.items() if k != "max_posts"):
            raise HTTPException(422, "Field cannot be null")

        assignments = ", ".join(f"{k} = :{k}" for k in changes)
        params = {**changes, "id": group_id}

        try:
            with engine.begin() as conn:
                row = conn.execute(text(f"""
                    UPDATE facebook_groups
                    SET {assignments}, updated_at = NOW()
                    WHERE id = :id
                    RETURNING id, name, url, enabled, max_posts
                """), params).mappings().first()
                if row is None:
                    raise HTTPException(404, "Group not found")
                return dict(row)
        except IntegrityError:
            raise HTTPException(409, "Group URL already exists")

    @router.delete("/groups/{group_id}",
                   dependencies=[Depends(verify_admin)])
    def delete_group(group_id: int):
        with engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM facebook_groups WHERE id = :id"),
                {"id": group_id}
            )
            if result.rowcount == 0:
                raise HTTPException(404, "Group not found")
            return {"deleted": True, "id": group_id}

    app.include_router(router)
