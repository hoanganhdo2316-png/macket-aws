import json
import logging
import os
from functools import lru_cache
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from admin_routes import verify_admin
from apify_run_ingestion import apify_get
from collector_config_routes import verify_collector
from collector_credentials_routes import load_apify_token


LOG = logging.getLogger(__name__)
FUNCTION_NAME = "macket-apify-trigger"
ACTOR_ID = "dGw5RQgZjVug05E1h"
TERMINAL = {"IDLE", "EXPIRED", "FAILED", "ABORTED", "TIMED-OUT", "AWAITING_INGESTION", "INGESTED"}


@lru_cache(maxsize=1)
def lambda_client():
    return boto3.client(
        "lambda", region_name="ap-southeast-1",
        config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}),
    )


class ClaimScan(BaseModel):
    scan_id: UUID | None = None


class ScanReport(BaseModel):
    scan_id: UUID
    state: Literal["RUNNING", "FAILED", "UNKNOWN"]
    run_id: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def check_run_id(self):
        if (self.run_id is not None) != (self.state == "RUNNING"):
            raise ValueError("A run ID is required only for RUNNING")
        return self


def scan_snapshot(engine):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT s.*, s.updated_at <= now() - interval '5 minutes' AS stale,
                   EXISTS (
                       SELECT 1 FROM crawl_runs r
                       WHERE r.apify_run_id = s.apify_run_id AND r.status = 'INGESTED'
                   ) AS ingested
            FROM collector_scan s WHERE s.id = 1
        """)).mappings().one()

    status = row["state"]
    if status == "QUEUED" and row["stale"]:
        status = "EXPIRED"
    elif status == "STARTING" and row["stale"]:
        status = "UNKNOWN"
    elif status == "RUNNING":
        if row["ingested"]:
            status = "INGESTED"
        else:
            try:
                run = apify_get(
                    f"actor-runs/{quote(row['apify_run_id'], safe='')}",
                    token=load_apify_token(engine), timeout=8,
                )
                if run.get("actId") != ACTOR_ID:
                    raise ValueError("Unexpected Apify Actor")
                status = run["status"]
                if status == "SUCCEEDED":
                    status = "AWAITING_INGESTION"
                elif status not in {"READY", "RUNNING", "ABORTING", "TIMING-OUT", "FAILED", "ABORTED", "TIMED-OUT"}:
                    status = "STATUS_UNAVAILABLE"
            except (OSError, ValueError, KeyError, HTTPException, AttributeError):
                status = "STATUS_UNAVAILABLE"
    return row, status


def reserve_scan(engine, source, state):
    row, status = scan_snapshot(engine)
    if status not in TERMINAL:
        return None

    scan_id = uuid4()
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE collector_scan
            SET scan_id = :scan_id, source = :source, state = :state,
                apify_run_id = NULL, updated_at = now(), revision = revision + 1
            WHERE id = 1 AND revision = :revision
            RETURNING scan_id
        """), {"scan_id": scan_id, "source": source, "state": state, "revision": row["revision"]})
        return result.scalar_one_or_none()


def claim_manual_scan(engine, scan_id):
    with engine.begin() as conn:
        return conn.execute(text("""
            UPDATE collector_scan SET state = 'STARTING', updated_at = now(), revision = revision + 1
            WHERE id = 1 AND scan_id = :scan_id AND state = 'QUEUED'
              AND updated_at > now() - interval '5 minutes'
            RETURNING scan_id
        """), {"scan_id": scan_id}).scalar_one_or_none()


def complete_scan_from_ingestion(engine, run_id, succeeded):
    state = "RUNNING" if succeeded else "FAILED"
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE collector_scan
            SET state = :state, updated_at = now(), revision = revision + 1
            WHERE id = 1 AND state = 'RUNNING' AND apify_run_id = :run_id
        """), {"state": state, "run_id": run_id})


def register_scan_routes(app, engine):
    admin = APIRouter(prefix="/api/scan", dependencies=[Depends(verify_admin)])
    collector = APIRouter(prefix="/api/collector/scan", dependencies=[Depends(verify_collector)])

    @admin.get("/status")
    def scan_status(response: Response):
        row, status = scan_snapshot(engine)
        enabled = os.getenv("MACKET_MANUAL_SCAN_ENABLED") == "true"
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": status, "scan_id": row["scan_id"], "source": row["source"],
            "run_id": row["apify_run_id"], "enabled": enabled,
            "can_trigger": enabled and status in TERMINAL,
        }

    @admin.post("/trigger", status_code=202)
    def trigger_scan():
        if os.getenv("MACKET_MANUAL_SCAN_ENABLED") != "true":
            raise HTTPException(503, "Quét thủ công chưa được bật.")
        scan_id = reserve_scan(engine, "manual", "QUEUED")
        if scan_id is None:
            raise HTTPException(409, "Đang có lượt quét hoặc chưa xác minh được trạng thái.")

        try:
            result = lambda_client().invoke(
                FunctionName=FUNCTION_NAME, InvocationType="Event",
                Payload=json.dumps({"scan_id": str(scan_id)}).encode("utf-8"),
            )
            if result.get("StatusCode") != 202:
                raise HTTPException(502, "Chưa xác nhận Lambda nhận yêu cầu. Kiểm tra trạng thái quét.")
        except ClientError as exc:
            http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if 400 <= http_status < 500:
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE collector_scan
                        SET state = 'FAILED', updated_at = now(), revision = revision + 1
                        WHERE id = 1 AND scan_id = :scan_id AND state = 'QUEUED'
                    """), {"scan_id": scan_id})
                raise HTTPException(502, "Lambda từ chối yêu cầu quét.") from exc
            LOG.warning("Lambda invoke did not confirm acceptance for scan %s", scan_id)
            raise HTTPException(502, "Chưa xác nhận Lambda nhận yêu cầu. Kiểm tra trạng thái quét.") from exc
        except BotoCoreError as exc:
            LOG.warning("Lambda invoke did not confirm acceptance for scan %s", scan_id)
            raise HTTPException(502, "Chưa xác nhận Lambda nhận yêu cầu. Kiểm tra trạng thái quét.") from exc
        return {"status": "QUEUED", "scan_id": scan_id}

    @collector.post("/claim")
    def claim_scan(data: ClaimScan):
        scan_id = (
            claim_manual_scan(engine, data.scan_id)
            if data.scan_id is not None
            else reserve_scan(engine, "scheduler", "STARTING")
        )
        return {"scan_id": scan_id}

    @collector.post("/report", status_code=204)
    def report_scan(data: ScanReport):
        with engine.begin() as conn:
            result = conn.execute(text("""
                UPDATE collector_scan
                SET state = :state, apify_run_id = :run_id,
                    updated_at = now(), revision = revision + 1
                WHERE id = 1 AND scan_id = :scan_id
                  AND (state = 'STARTING' OR (state = :state AND apify_run_id IS NOT DISTINCT FROM :run_id))
            """), data.model_dump())
            if not result.rowcount:
                raise HTTPException(409, "Scan is no longer current")

    app.include_router(admin)
    app.include_router(collector)
