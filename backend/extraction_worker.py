import argparse
import json
import os
import time
from decimal import Decimal
from contextlib import nullcontext
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text, bindparam
from sqlalchemy.dialects.postgresql import JSONB

from ai_schemas import Stage2Extraction
from credentials_routes import get_cipher

load_dotenv(".env")

MODEL = os.getenv(
    "MACKET_EXTRACTION_MODEL",
    "gpt-4.1-mini"
)

PROMPT_FILE = (
    Path(__file__).resolve().parent
    / "stage2_extraction_prompt.txt"
)



def calculate_cost(usage, model):
    if usage is None:
        return None

    rates = {
        "gpt-4.1-mini": ("0.40", "0.10", "1.60"),
        "gpt-4.1-mini-2025-04-14": ("0.40", "0.10", "1.60"),
    }

    if model not in rates:
        return None

    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens

    if input_tokens is None or output_tokens is None:
        return None

    cached = 0
    if usage.prompt_tokens_details:
        cached = usage.prompt_tokens_details.cached_tokens or 0

    if not 0 <= cached <= input_tokens:
        return None

    input_rate, cached_rate, output_rate = map(
        Decimal, rates[model]
    )

    return (
        (
            Decimal(input_tokens - cached) * input_rate
            + Decimal(cached) * cached_rate
            + Decimal(output_tokens) * output_rate
        ) / Decimal(1_000_000)
    ).quantize(Decimal("0.00000001"))


def save_extraction_log(
    engine,
    classification_id,
    post_id,
    status,
    usage,
    processing_ms,
    product_count=None,
    error_type=None,
    conn=None,
):
    cost = calculate_cost(usage, MODEL)

    context = engine.begin() if conn is None else nullcontext(conn)

    with context as conn:
        log_id = conn.execute(text("""
            INSERT INTO post_extraction_logs (
                classification_id,
                post_id,
                model,
                status,
                product_count,
                input_tokens,
                output_tokens,
                total_tokens,
                processing_ms,
                estimated_cost_usd,
                error_type
            )
            VALUES (
                :classification_id,
                :post_id,
                :model,
                :status,
                :product_count,
                :input_tokens,
                :output_tokens,
                :total_tokens,
                :processing_ms,
                :cost,
                :error_type
            )
            RETURNING id
        """), {
            "classification_id": classification_id,
            "post_id": post_id,
            "model": MODEL,
            "status": status,
            "product_count": product_count,
            "input_tokens": (
                usage.prompt_tokens if usage else None
            ),
            "output_tokens": (
                usage.completion_tokens if usage else None
            ),
            "total_tokens": (
                usage.total_tokens if usage else None
            ),
            "processing_ms": processing_ms,
            "cost": cost,
            "error_type": error_type,
        }).scalar_one()

    return {"log_id": log_id, "estimated_cost_usd": cost}


def extract_products(classification_id: int, execute=False):
    from main import engine

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
                c.id AS classification_id,
                c.post_id,
                c.post_type,
                c.seller_type,
                c.extraction_status,
                c.extraction_attempts,
                p.content
            FROM post_classifications c
            JOIN posts p ON p.id = c.post_id
            WHERE c.id = :id
        """), {"id": classification_id}).mappings().first()

        credential = conn.execute(text("""
            SELECT encrypted_token
            FROM api_credentials
            WHERE service = 'openai'
        """)).mappings().first()

    if row is None:
        raise RuntimeError("CLASSIFICATION NOT FOUND")

    if not (
        row["post_type"] == "selling"
        and row["seller_type"] == "individual"
    ):
        raise RuntimeError(
            "STAGE 2 ONLY ACCEPTS INDIVIDUAL + SELLING"
        )

    if row["extraction_status"] == "completed":
        return {"status": "already_completed"}

    if row["extraction_status"] not in ("pending", "failed"):
        raise RuntimeError("INVALID EXTRACTION STATUS")

    if not (row["content"] or "").strip():
        raise RuntimeError("EMPTY POST CONTENT")

    if not PROMPT_FILE.is_file():
        raise RuntimeError("STAGE 2 PROMPT NOT FOUND")

    if credential is None:
        raise RuntimeError("OPENAI CREDENTIAL NOT FOUND")

    prompt = PROMPT_FILE.read_text(encoding="utf-8")

    print("=== MACKET STAGE 2 EXTRACTION ===")
    print("CLASSIFICATION ID:", classification_id)
    print("POST ID:", row["post_id"])
    print("MODEL:", MODEL)
    print("EXTRACTION STATUS:", row["extraction_status"])
    print("PROMPT LENGTH:", len(prompt))
    print("EXECUTE:", execute)

    if not execute:
        print("DRY RUN PASSED - NO OPENAI REQUEST")
        return {
            "status": "dry_run",
            "classification_id": classification_id,
        }

    api_key = get_cipher().decrypt(
        credential["encrypted_token"].encode()
    ).decode()

    client = OpenAI(
        api_key=api_key,
        timeout=60,
        max_retries=1,
    )

    with engine.begin() as conn:
        updated = conn.execute(text("""
            UPDATE post_classifications
            SET extraction_status = 'processing',
                extraction_started_at = NOW(),
                extraction_attempts = extraction_attempts + 1,
                extraction_error = NULL
            WHERE id = :id
              AND extraction_status IN ('pending', 'failed')
            RETURNING id
        """), {"id": classification_id}).scalar_one_or_none()

    if updated is None:
        raise RuntimeError("CLASSIFICATION ALREADY CLAIMED")

    started = time.perf_counter()
    result = None

    try:
        result = client.chat.completions.parse(
            model=MODEL,
            max_completion_tokens=4000,
            messages=[
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "content": row["content"],
                    }, ensure_ascii=False),
                },
            ],
            response_format=Stage2Extraction,
        )

        message = result.choices[0].message

        if message.refusal or message.parsed is None:
            raise RuntimeError("EXTRACTION NOT PARSED")

        data = message.parsed.model_dump()

        usage = result.usage

        processing_ms = round(
            (time.perf_counter() - started) * 1000
        )

        # Save products and extraction log atomically.
        # Both operations commit or roll back together.
        with engine.begin() as conn:
            saved = conn.execute(
                text("""
                    UPDATE post_classifications
                    SET products = :products,
                        location = :location,
                        extraction_status = 'completed',
                        extraction_started_at = NULL,
                        extraction_error = NULL
                    WHERE id = :id
                      AND extraction_status = 'processing'
                """).bindparams(
                    bindparam("products", type_=JSONB)
                ),
                {
                    "id": classification_id,
                    "products": data["products"],
                    "location": data["location"],
                },
            )

            if saved.rowcount != 1:
                raise RuntimeError("EXTRACTION FINALIZE CONFLICT")

            log = save_extraction_log(
                engine=engine,
                classification_id=classification_id,
                post_id=row["post_id"],
                status="completed",
                usage=usage,
                processing_ms=processing_ms,
                product_count=len(data["products"]),
                conn=conn,
            )

        print("ATOMIC EXTRACTION SAVE: COMMITTED")

        response = {
            "status": "completed",
            "classification_id": classification_id,
            "post_id": row["post_id"],
            "product_count": len(data["products"]),
            "extraction_log_id": log["log_id"] if log else None,
            "estimated_cost_usd": (
                float(log["estimated_cost_usd"])
                if log and log["estimated_cost_usd"] is not None
                else None
            ),
            "location": data["location"],
            "input_tokens": (
                usage.prompt_tokens if usage else None
            ),
            "output_tokens": (
                usage.completion_tokens if usage else None
            ),
            "processing_ms": processing_ms,
        }

        print(json.dumps(
            response,
            ensure_ascii=False,
            indent=2,
        ))

        print("\n=== EXTRACTED PRODUCTS ===")
        print(json.dumps(
            data["products"],
            ensure_ascii=False,
            indent=2,
        ))

        return response

    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE post_classifications
                SET extraction_status = 'failed',
                    extraction_started_at = NULL,
                    extraction_error = :error
                WHERE id = :id
                  AND extraction_status = 'processing'
            """), {
                "id": classification_id,
                "error": type(exc).__name__,
            })

        try:
            failure_log = save_extraction_log(
                engine=engine,
                classification_id=classification_id,
                post_id=row["post_id"],
                status="failed",
                usage=result.usage if result is not None else None,
                processing_ms=round(
                    (time.perf_counter() - started) * 1000
                ),
                error_type=type(exc).__name__,
            )
            print("EXTRACTION FAILURE LOG:", failure_log["log_id"])
        except Exception as log_exc:
            print("EXTRACTION LOG ERROR:", type(log_exc).__name__)

        print("STAGE 2 FAILED:", type(exc).__name__)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--classification-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
    )

    args = parser.parse_args()

    extract_products(
        classification_id=args.classification_id,
        execute=args.execute,
    )
