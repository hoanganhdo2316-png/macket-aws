from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from admin_routes import verify_admin

router = APIRouter(
    prefix="/api/admin/crawler-settings",
    tags=["Crawler Settings"],
    dependencies=[Depends(verify_admin)]
)


class SettingsUpdate(BaseModel):
    max_posts_per_group: int | None = Field(
        default=None, ge=1, le=100
    )
    only_new_posts: bool | None = None
    max_total_charge_usd: Decimal | None = Field(
        default=None, ge=Decimal("0.01"), le=Decimal("10.00")
    )


def register_settings_routes(app, engine):

    def serialize(row):
        data = dict(row)
        data["max_total_charge_usd"] = str(
            data["max_total_charge_usd"]
        )
        return data

    @router.get("")
    def get_settings():
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT *
                FROM crawler_settings
                WHERE id = 1
            """)).mappings().one()

            return serialize(row)

    @router.patch("")
    def update_settings(data: SettingsUpdate):
        changes = data.model_dump(exclude_unset=True)

        if not changes:
            raise HTTPException(400, "No settings provided")

        if any(value is None for value in changes.values()):
            raise HTTPException(422, "Settings cannot be null")

        assignments = ", ".join(
            f"{key} = :{key}" for key in changes
        )

        with engine.begin() as conn:
            row = conn.execute(text(f"""
                UPDATE crawler_settings
                SET {assignments}, updated_at = NOW()
                WHERE id = 1
                RETURNING *
            """), changes).mappings().one()

            return serialize(row)

    app.include_router(router)
