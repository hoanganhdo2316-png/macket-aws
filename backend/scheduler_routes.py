import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from admin_routes import verify_admin

SCHEDULE_NAME = "macket-apify-hourly"
SCHEDULE_GROUP = "default"

client = boto3.client("scheduler", region_name="ap-southeast-1")

router = APIRouter(
    prefix="/api/admin/scheduler",
    tags=["Scheduler"],
    dependencies=[Depends(verify_admin)]
)


class SchedulerUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(
        default=None, ge=1, le=1440
    )


def aws_schedule():
    try:
        return client.get_schedule(
            Name=SCHEDULE_NAME,
            GroupName=SCHEDULE_GROUP
        )
    except (ClientError, BotoCoreError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Cannot read AWS EventBridge Scheduler"
        ) from exc


def update_payload(schedule, minutes):
    expression = (
        f"rate({minutes} minute)"
        if minutes == 1
        else f"rate({minutes} minutes)"
    )

    payload = {
        "Name": SCHEDULE_NAME,
        "GroupName": SCHEDULE_GROUP,
        "ScheduleExpression": expression,
        "FlexibleTimeWindow": schedule["FlexibleTimeWindow"],
        "Target": schedule["Target"],
        "State": "DISABLED",
    }

    # Giữ những cấu hình tùy chọn đã tồn tại trên AWS.
    optional = (
        "ActionAfterCompletion",
        "Description",
        "StartDate",
        "EndDate",
        "ScheduleExpressionTimezone",
        "KmsKeyArn",
    )

    for key in optional:
        if key in schedule:
            payload[key] = schedule[key]

    return payload


def register_scheduler_routes(app, engine):

    @router.get("")
    def get_scheduler():
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT *
                FROM scheduler_settings
                WHERE id = 1
            """)).mappings().one()

        aws = aws_schedule()

        return {
            **dict(row),
            "aws_state": aws["State"],
            "aws_expression": aws["ScheduleExpression"],
            "aws_sync_status": (
                "synced"
                if aws["State"] == (
                    "ENABLED" if row["enabled"] else "DISABLED"
                )
                and aws["ScheduleExpression"] ==
                    update_payload(
                        aws, row["interval_minutes"]
                    )["ScheduleExpression"]
                else "mismatch"
            ),
        }

    @router.patch("")
    def update_scheduler(data: SchedulerUpdate):
        changes = data.model_dump(exclude_unset=True)

        if not changes:
            raise HTTPException(400, "No settings provided")

        if any(value is None for value in changes.values()):
            raise HTTPException(422, "Settings cannot be null")

        # Chưa cho phép bật lịch cho đến khi
        # hoàn thiện pipeline nhận kết quả Apify.
        if changes.get("enabled") is True:
            raise HTTPException(
                409,
                "Scheduler activation is locked until "
                "Apify result ingestion is ready"
            )

        with engine.connect() as conn:
            current = dict(conn.execute(text("""
                SELECT * FROM scheduler_settings
                WHERE id = 1
            """)).mappings().one())

        minutes = changes.get(
            "interval_minutes",
            current["interval_minutes"]
        )

        original_aws = aws_schedule()

        # Tuyệt đối không vô tình bật lịch.
        if original_aws["State"] != "DISABLED":
            raise HTTPException(
                409,
                "AWS schedule must be disabled before editing"
            )

        desired = update_payload(original_aws, minutes)

        try:
            client.update_schedule(**desired)
        except (ClientError, BotoCoreError) as exc:
            raise HTTPException(
                502,
                "Failed to update AWS EventBridge Scheduler"
            ) from exc

        # Chỉ ghi RDS sau khi cập nhật AWS thành công.
        try:
            with engine.begin() as conn:
                row = conn.execute(text("""
                    UPDATE scheduler_settings
                    SET enabled = FALSE,
                        interval_minutes = :minutes,
                        updated_at = NOW()
                    WHERE id = 1
                    RETURNING *
                """), {"minutes": minutes}).mappings().one()

                result = dict(row)
        except Exception:
            # Cố gắng trả AWS về cấu hình ban đầu.
            try:
                rollback = update_payload(
                    original_aws,
                    current["interval_minutes"]
                )
                rollback["ScheduleExpression"] = (
                    original_aws["ScheduleExpression"]
                )
                client.update_schedule(**rollback)
            except Exception:
                raise HTTPException(
                    500,
                    "RDS update failed and AWS rollback failed; "
                    "manual reconciliation required"
                )
            raise HTTPException(
                500,
                "RDS update failed; AWS rollback attempted"
            )

        return {
            **result,
            "aws_state": "DISABLED",
            "aws_expression": desired["ScheduleExpression"],
            "aws_sync_status": "synced"
        }

    app.include_router(router)
