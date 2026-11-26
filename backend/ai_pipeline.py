"""Run one bounded AI and media pass; disabled unless explicitly enabled."""

import json
import os
from decimal import Decimal, InvalidOperation
from batch_classification_worker_v2 import get_tasks
from batch_execute_v2 import execute_batch
from media_batch_worker import run_media_batch


def config():
    if os.getenv("MACKET_AI_PIPELINE_ENABLED", "false") != "true":
        return None
    try:
        limit = int(os.getenv("MACKET_AI_PIPELINE_REQUEST_LIMIT", "1"))
        budget = Decimal(os.getenv("MACKET_AI_PIPELINE_BUDGET_USD", "0.01"))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("Invalid AI pipeline limit or budget") from exc
    if limit != 1 or not (Decimal("0") < budget <= Decimal("0.01")):
        raise ValueError("AI pipeline permits exactly one request and at most $0.01 per pass")
    return limit, budget


def run_once():
    settings = config()
    if settings is None:
        return {"status": "disabled", "openai_requests": 0}
    limit, budget = settings
    from main import engine
    with engine.connect() as conn:
        stage2, stage1 = get_tasks(conn, limit)
    classification = "empty"
    if stage1 or stage2:
        execute_batch(limit, budget)
        classification = "submitted"
    media = run_media_batch(limit=1, execute=True)
    return {"status": "completed", "classification": classification,
            "openai_requests": 1 if classification == "submitted" else 0, "media": media}


if __name__ == "__main__":
    print(json.dumps(run_once(), sort_keys=True, default=str))
