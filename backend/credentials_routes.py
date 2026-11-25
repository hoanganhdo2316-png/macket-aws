import os
from datetime import datetime

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import text

from admin_routes import verify_admin

router = APIRouter(
    prefix="/api/admin/credentials",
    tags=["Admin Credentials"],
    dependencies=[Depends(verify_admin)]
)

SERVICES = ("openai", "apify")


class CredentialUpdate(BaseModel):
    token: SecretStr = Field(min_length=1)


def get_cipher():
    key = os.getenv("CREDENTIALS_ENCRYPTION_KEY")
    if not key:
        raise HTTPException(503, "Encryption key is not configured")
    return Fernet(key.encode())


def register_credentials_routes(app, engine):

    @router.get("")
    def list_credentials():
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT service, updated_at
                FROM api_credentials
            """)).mappings().all()

        existing = {
            row["service"]: row["updated_at"]
            for row in rows
        }

        return {
            "credentials": [
                {
                    "service": service,
                    "configured": service in existing,
                    "updated_at": existing.get(service)
                }
                for service in SERVICES
            ]
        }

    @router.put("/{service}")
    def save_credential(service: str, data: CredentialUpdate):
        if service not in SERVICES:
            raise HTTPException(404, "Unsupported service")

        token = data.token.get_secret_value().strip()

        if not token:
            raise HTTPException(422, "Token cannot be empty")

        encrypted = get_cipher().encrypt(
            token.encode()
        ).decode()

        with engine.begin() as conn:
            row = conn.execute(text("""
                INSERT INTO api_credentials (
                    service, encrypted_token, updated_at
                )
                VALUES (
                    :service, :encrypted, NOW()
                )
                ON CONFLICT (service)
                DO UPDATE SET
                    encrypted_token = EXCLUDED.encrypted_token,
                    updated_at = NOW()
                RETURNING service, updated_at
            """), {
                "service": service,
                "encrypted": encrypted
            }).mappings().one()

        return {
            "service": row["service"],
            "configured": True,
            "updated_at": row["updated_at"]
        }

    app.include_router(router)
