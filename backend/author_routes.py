from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from admin_routes import verify_admin

router = APIRouter(
    prefix="/api/admin/authors",
    tags=["Admin Authors"],
    dependencies=[Depends(verify_admin)]
)


class AuthorCreate(BaseModel):
    facebook_author_id: str | None = Field(default=None, max_length=255)
    profile_url: str | None = None
    display_name: str | None = Field(default=None, max_length=255)
    classification: str = "unknown"
    skip_enabled: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def validate_author(self):
        if not self.facebook_author_id and not self.profile_url:
            raise ValueError("Author ID or Profile URL is required")
        if self.classification not in ("seller", "individual", "unknown"):
            raise ValueError("Invalid classification")
        if self.profile_url:
            from urllib.parse import urlparse
            parsed = urlparse(self.profile_url)
            if parsed.scheme != "https" or parsed.hostname not in (
                "facebook.com", "www.facebook.com", "m.facebook.com"
            ):
                raise ValueError("Invalid Facebook Profile URL")
        return self


class AuthorUpdate(BaseModel):
    facebook_author_id: str | None = Field(default=None, max_length=255)
    profile_url: str | None = None
    display_name: str | None = Field(default=None, max_length=255)
    classification: str | None = None
    skip_enabled: bool | None = None
    reason: str | None = None


def register_author_routes(app, engine):

    @router.get("")
    def list_authors():
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT *
                FROM author_skip_list
                ORDER BY id DESC
            """))
            return {"authors": [dict(r) for r in rows.mappings()]}

    @router.post("", status_code=201)
    def create_author(data: AuthorCreate):
        try:
            with engine.begin() as conn:
                row = conn.execute(text("""
                    INSERT INTO author_skip_list (
                        facebook_author_id, profile_url, display_name,
                        classification, skip_enabled, reason
                    )
                    VALUES (
                        :facebook_author_id, :profile_url, :display_name,
                        :classification, :skip_enabled, :reason
                    )
                    RETURNING *
                """), data.model_dump()).mappings().one()
                return dict(row)
        except IntegrityError:
            raise HTTPException(409, "Author already exists or invalid")

    @router.patch("/{author_id}")
    def update_author(author_id: int, data: AuthorUpdate):
        changes = data.model_dump(exclude_unset=True)

        if not changes:
            raise HTTPException(400, "No fields provided")

        if changes.get("classification") not in (
            None, "seller", "individual", "unknown"
        ):
            raise HTTPException(422, "Invalid classification")

        if "classification" in changes and changes["classification"] is None:
            raise HTTPException(422, "Classification cannot be null")
        if "skip_enabled" in changes and changes["skip_enabled"] is None:
            raise HTTPException(422, "skip_enabled cannot be null")

        if changes.get("profile_url"):
            from urllib.parse import urlparse
            parsed = urlparse(changes["profile_url"])
            if parsed.scheme != "https" or parsed.hostname not in (
                "facebook.com", "www.facebook.com", "m.facebook.com"
            ):
                raise HTTPException(422, "Invalid Facebook Profile URL")

        assignments = ", ".join(f"{k} = :{k}" for k in changes)

        try:
            with engine.begin() as conn:
                row = conn.execute(text(f"""
                    UPDATE author_skip_list
                    SET {assignments}, updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                """), {**changes, "id": author_id}).mappings().first()

                if row is None:
                    raise HTTPException(404, "Author not found")

                return dict(row)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Duplicate author or invalid data. "
                    "Only authors classified as seller can have Skip enabled."
                ),
            ) from exc

    @router.delete("/{author_id}")
    def delete_author(author_id: int):
        with engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM author_skip_list WHERE id = :id"),
                {"id": author_id}
            )
            if result.rowcount == 0:
                raise HTTPException(404, "Author not found")
            return {"deleted": True, "id": author_id}

    app.include_router(router)
