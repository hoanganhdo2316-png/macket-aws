import os
import logging
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from apify_run_ingestion import ingest_run

router = APIRouter(prefix="/api/webhooks", tags=["Apify Webhook"])


class Resource(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=255)


class WebhookPayload(BaseModel):
    eventType: str
    resource: Resource | None = None


def register_apify_webhook_routes(app, engine):

    @router.post("/apify")
    def apify_webhook(
        payload: WebhookPayload,
        x_webhook_token: str | None = Header(default=None),
    ):
        expected = os.getenv("APIFY_WEBHOOK_TOKEN")

        if not expected:
            raise HTTPException(503, "Webhook unavailable")

        if not x_webhook_token or not secrets.compare_digest(
            x_webhook_token, expected
        ):
            raise HTTPException(401, "Unauthorized")

        if payload.eventType == "TEST":
            return {
                "status": "WEBHOOK_TEST_OK",
                "message": "Macket webhook connection verified"
            }

        if payload.eventType != "ACTOR.RUN.SUCCEEDED":
            raise HTTPException(400, "Unsupported event")

        if payload.resource is None or not payload.resource.id:
            raise HTTPException(422, "Missing Apify Run ID")

        try:
            return ingest_run(engine, payload.resource.id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    app.include_router(router)
