import os

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text

from collector_config_routes import verify_collector

router = APIRouter(
    prefix="/api/collector",
    tags=["Collector Credentials"],
    dependencies=[Depends(verify_collector)]
)


def register_collector_credentials_routes(app, engine):

    @router.get("/apify-token")
    def get_apify_token(response: Response):
        response.headers["Cache-Control"] = "no-store"

        encryption_key = os.getenv("CREDENTIALS_ENCRYPTION_KEY")

        if not encryption_key:
            raise HTTPException(
                503, "Credentials encryption unavailable"
            )

        with engine.connect() as conn:
            encrypted = conn.execute(text("""
                SELECT encrypted_token
                FROM api_credentials
                WHERE service = 'apify'
            """)).scalar_one_or_none()

        if not encrypted:
            raise HTTPException(
                503, "Apify Token not configured"
            )

        try:
            token = Fernet(
                encryption_key.encode()
            ).decrypt(encrypted.encode()).decode()
        except (InvalidToken, ValueError):
            raise HTTPException(
                503, "Cannot decrypt Apify Token"
            )

        return {"token": token}

    app.include_router(router)
