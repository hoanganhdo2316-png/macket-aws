import argparse
import json
import os
import time
from decimal import Decimal

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import bindparam

from ai_schemas import Stage1Classification
from credentials_routes import get_cipher
from seller_block_service import block_seller
from stage1_claim_service import (
    acquire_claim,
    complete_claim,
    fail_claim,
)

load_dotenv(".env")

MODEL = os.getenv("MACKET_CLASSIFICATION_MODEL", "gpt-4.1-mini")

RATES = {
    "gpt-4.1-mini": ("0.40", "0.10", "1.60"),
    "gpt-4.1-mini-2025-04-14": ("0.40", "0.10", "1.60"),
}


def _classify_stage1_unclaimed(post_id: int, execute: bool = False, claim_id=None):
    from main import engine

    with engine.connect() as conn:
        post = conn.execute(text("""
            SELECT id, content, author_name, author_id, author_url
            FROM posts WHERE id = :id
        """), {"id": post_id}).mappings().first()

        prompt = conn.execute(text("""
            SELECT id, version, system_prompt
            FROM ai_prompt_versions
            WHERE version = 7
        """)).mappings().first()

        credential = conn.execute(text("""
            SELECT encrypted_token
            FROM api_credentials
            WHERE service = 'openai'
        """)).mappings().first()

        existing = conn.execute(text("""
            SELECT id
            FROM post_classifications
            WHERE post_id = :post_id
              AND prompt_version_id = :prompt_id
            ORDER BY id DESC LIMIT 1
        """), {
            "post_id": post_id,
            "prompt_id": prompt["id"] if prompt else -1,
        }).scalar_one_or_none()

    if not post:
        raise RuntimeError("POST NOT FOUND")
    if not prompt:
        raise RuntimeError("PROMPT V7 NOT FOUND")
    if not credential:
        raise RuntimeError("OPENAI CREDENTIAL NOT FOUND")
    if not (post["content"] or "").strip():
        raise RuntimeError("EMPTY POST CONTENT")
    if existing:
        return {
            "status": "already_classified",
            "classification_id": existing,
        }

    print("=== STAGE 1 CLASSIFICATION ===")
    print("POST ID:", post_id)
    print("PROMPT VERSION:", prompt["version"])
    print("MODEL:", MODEL)
    print("EXECUTE:", execute)

    if not execute:
        return {"status": "dry_run", "post_id": post_id}

    api_key = get_cipher().decrypt(
        credential["encrypted_token"].encode()
    ).decode()

    client = OpenAI(api_key=api_key, timeout=45, max_retries=1)

    started = time.perf_counter()

    result = client.chat.completions.parse(
        model=MODEL,
        max_completion_tokens=1000,
        messages=[
            {
                "role": "system",
                "content": prompt["system_prompt"],
            },
            {
                "role": "user",
                "content": json.dumps({
                    "content": post["content"],
                    "author_name": post["author_name"],
                    "author_id": post["author_id"],
                    "author_url": post["author_url"],
                }, ensure_ascii=False),
            },
        ],
        response_format=Stage1Classification,
    )

    processing_ms = round(
        (time.perf_counter() - started) * 1000
    )

    message = result.choices[0].message

    if message.refusal or message.parsed is None:
        raise RuntimeError("STAGE 1 CLASSIFICATION FAILED")

    data = message.parsed.model_dump()
    usage = result.usage

    input_tokens = usage.prompt_tokens if usage else None
    output_tokens = usage.completion_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None

    cached_tokens = 0
    if usage and usage.prompt_tokens_details:
        cached_tokens = (
            usage.prompt_tokens_details.cached_tokens or 0
        )

    estimated_cost = None

    if (
        MODEL in RATES
        and input_tokens is not None
        and output_tokens is not None
        and 0 <= cached_tokens <= input_tokens
    ):
        input_rate, cached_rate, output_rate = map(
            Decimal, RATES[MODEL]
        )

        estimated_cost = (
            (
                Decimal(input_tokens - cached_tokens) * input_rate
                + Decimal(cached_tokens) * cached_rate
                + Decimal(output_tokens) * output_rate
            ) / Decimal(1_000_000)
        ).quantize(Decimal("0.00000001"))

    needs_extraction = (
        data["post_type"] == "selling"
        and data["seller_type"] == "individual"
    )

    extraction_status = (
        "pending" if needs_extraction else "not_required"
    )

    with engine.begin() as conn:
        classification_id = conn.execute(
            text("""
                INSERT INTO post_classifications (
                    post_id, prompt_version_id, model,
                    post_type, seller_type, confidence,
                    products, location, reason, raw_result,
                    input_tokens, output_tokens, total_tokens,
                    processing_ms, estimated_cost_usd,
                    extraction_status, extraction_attempts
                )
                VALUES (
                    :post_id, :prompt_id, :model,
                    :post_type, :seller_type, :confidence,
                    :products, NULL, :reason, :raw_result,
                    :input_tokens, :output_tokens, :total_tokens,
                    :processing_ms, :estimated_cost,
                    :extraction_status, 0
                )
                RETURNING id
            """).bindparams(
                bindparam("products", type_=JSONB),
                bindparam("raw_result", type_=JSONB),
            ),
            {
                "post_id": post_id,
                "prompt_id": prompt["id"],
                "model": MODEL,
                "post_type": data["post_type"],
                "seller_type": data["seller_type"],
                "confidence": data["confidence"],
                "products": [],
                "reason": data["reason"],
                "raw_result": data,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "processing_ms": processing_ms,
                "estimated_cost": estimated_cost,
                "extraction_status": extraction_status,
            },
        ).scalar_one()

        if claim_id is not None:
            complete_claim(conn, claim_id, classification_id)

    block_status = "not_seller"

    if data["seller_type"] == "seller":
        try:
            block_result = block_seller(
                engine=engine,
                post_id=post_id,
                classification_id=classification_id,
                execute=True,
            )
            block_status = block_result["status"]
        except Exception as exc:
            block_status = "error"
            print("AUTO BLOCK ERROR:", type(exc).__name__)

    response = {
        "status": "success",
        "post_id": post_id,
        "classification_id": classification_id,
        "prompt_version": prompt["version"],
        "post_type": data["post_type"],
        "seller_type": data["seller_type"],
        "confidence": data["confidence"],
        "reason": data["reason"],
        "extraction_status": extraction_status,
        "auto_block_status": block_status,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "processing_ms": processing_ms,
        "estimated_cost_usd": (
            float(estimated_cost)
            if estimated_cost is not None else None
        ),
    }

    print(json.dumps(response, ensure_ascii=False, indent=2))
    return response



def classify_stage1(post_id: int, execute: bool = False):
    if not execute:
        return _classify_stage1_unclaimed(
            post_id, execute=False
        )

    from main import engine

    with engine.connect() as conn:
        prompt_id = conn.execute(text("""
            SELECT id
            FROM ai_prompt_versions
            WHERE version = 7
        """)).scalar_one()

    claim = acquire_claim(
        engine=engine,
        post_id=post_id,
        prompt_version_id=prompt_id,
    )

    if claim["status"] != "acquired":
        print("STAGE 1 CLAIM:", claim)
        return claim

    claim_id = claim["claim_id"]
    print("STAGE 1 CLAIM ACQUIRED:", claim_id)

    try:
        result = _classify_stage1_unclaimed(
            post_id,
            execute=True,
            claim_id=claim_id,
        )

        if result.get("status") != "success":
            fail_claim(
                engine,
                claim_id,
                "UnexpectedClassificationStatus",
            )

        return result

    except Exception as exc:
        try:
            fail_claim(
                engine,
                claim_id,
                type(exc).__name__,
            )
        except Exception as claim_error:
            print(
                "CLAIM UPDATE ERROR:",
                type(claim_error).__name__,
            )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    classify_stage1(args.post_id, execute=args.execute)
