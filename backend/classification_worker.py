import argparse
import json
import os
import time
from decimal import Decimal
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from credentials_routes import get_cipher

load_dotenv(".env")


class Specification(BaseModel):
    name: str
    value: str


class Product(BaseModel):
    category: str | None
    brand: str | None
    model: str | None
    specifications: list[Specification]
    price_vnd: int | None
    condition: Literal["new", "used", "unknown"]


class Classification(BaseModel):
    post_type: Literal["selling", "buying", "other"]
    seller_type: Literal["individual", "seller", "unknown"]
    confidence: float = Field(ge=0, le=1)
    products: list[Product]
    location: str | None
    reason: str


def classify_post(post_id: int, execute: bool = False):
    from main import engine

    with engine.connect() as conn:
        post = conn.execute(text("""
            SELECT id, content, author_name, author_id,
                   author_url, url
            FROM posts
            WHERE id = :id
        """), {"id": post_id}).mappings().first()

        prompt = conn.execute(text("""
            SELECT id, version, system_prompt, description
            FROM ai_prompt_versions
            WHERE is_active = TRUE
        """)).mappings().first()

        credential = conn.execute(text("""
            SELECT encrypted_token
            FROM api_credentials
            WHERE service = 'openai'
        """)).mappings().first()

    if not post:
        raise SystemExit("POST NOT FOUND")

    if not prompt:
        raise SystemExit("NO ACTIVE SYSTEM PROMPT")

    if not credential:
        raise SystemExit("OPENAI KEY NOT CONFIGURED")

    if not (post["content"] or "").strip():
        raise SystemExit("POST HAS NO TEXT CONTENT")

    print("POST ID:", post["id"])
    print("PROMPT VERSION:", prompt["version"])
    print("CONTENT LENGTH:", len(post["content"]))
    print("OPENAI CREDENTIAL: CONFIGURED")

    # Reject the temporary test prompts used during API verification.
    if (
        "test prompt" in prompt["system_prompt"].lower()
        or "initial api verification" in
        (prompt["description"] or "").lower()
    ):
        raise SystemExit(
            "TEST PROMPT ACTIVE - CREATE A REAL CLASSIFICATION PROMPT"
        )

    if not execute:
        print("DRY RUN PASSED - NO OPENAI REQUEST")
        return

    api_key = get_cipher().decrypt(
        credential["encrypted_token"].encode()
    ).decode()

    input_data = {
        "content": post["content"],
        "author_name": post["author_name"],
        "author_id": post["author_id"],
        "author_url": post["author_url"],
    }

    model = os.getenv(
        "MACKET_CLASSIFICATION_MODEL",
        "gpt-4.1-mini"
    )

    client = OpenAI(api_key=api_key, timeout=45, max_retries=1)

    started = time.perf_counter()
    result = client.chat.completions.parse(
        model=model,
        max_completion_tokens=4000,
        messages=[
            {
                "role": "system",
                "content": prompt["system_prompt"],
            },
            {
                "role": "user",
                "content": json.dumps(
                    input_data, ensure_ascii=False
                ),
            },
        ],
        response_format=Classification,
    )

    processing_ms = round(
        (time.perf_counter() - started) * 1000
    )

    usage = result.usage
    input_tokens = usage.prompt_tokens if usage else None
    output_tokens = usage.completion_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None

    # Standard API rates in USD per 1 million tokens.
    # Unsupported models remain unpriced.
    rates = {
        "gpt-4.1-mini": ("0.40", "0.10", "1.60"),
        "gpt-4.1-mini-2025-04-14": ("0.40", "0.10", "1.60"),
    }

    cached_tokens = 0
    if usage and usage.prompt_tokens_details:
        cached_tokens = (
            usage.prompt_tokens_details.cached_tokens or 0
        )

    estimated_cost_usd = None

    if (
        model in rates
        and input_tokens is not None
        and output_tokens is not None
        and 0 <= cached_tokens <= input_tokens
    ):
        input_rate, cached_rate, output_rate = map(
            Decimal, rates[model]
        )

        cost = (
            Decimal(input_tokens - cached_tokens) * input_rate
            + Decimal(cached_tokens) * cached_rate
            + Decimal(output_tokens) * output_rate
        ) / Decimal(1_000_000)

        estimated_cost_usd = cost.quantize(
            Decimal("0.00000001")
        )

    message = result.choices[0].message

    if message.refusal:
        raise RuntimeError("MODEL REFUSED CLASSIFICATION")

    classification = message.parsed

    if classification is None:
        raise RuntimeError("NO PARSED CLASSIFICATION")

    data = classification.model_dump()

    with engine.begin() as conn:
        classification_id = conn.execute(text("""
            INSERT INTO post_classifications (
                post_id, prompt_version_id, model,
                post_type, seller_type, confidence,
                products, location, reason, raw_result,
                input_tokens, output_tokens, total_tokens,
                processing_ms, estimated_cost_usd
            )
            VALUES (
                :post_id, :prompt_id, :model,
                :post_type, :seller_type, :confidence,
                :products, :location, :reason, :raw_result,
                :input_tokens, :output_tokens, :total_tokens,
                :processing_ms, :estimated_cost_usd
            )
            RETURNING id
        """).bindparams(
            __import__("sqlalchemy").bindparam(
                "products", type_=JSONB
            ),
            __import__("sqlalchemy").bindparam(
                "raw_result", type_=JSONB
            ),
        ), {
            "post_id": post["id"],
            "prompt_id": prompt["id"],
            "model": model,
            "post_type": data["post_type"],
            "seller_type": data["seller_type"],
            "confidence": data["confidence"],
            "products": data["products"],
            "location": data["location"],
            "reason": data["reason"],
            "raw_result": data,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "processing_ms": processing_ms,
            "estimated_cost_usd": estimated_cost_usd,
        }).scalar_one()

    print("CLASSIFICATION SAVED:", classification_id)

    # Auto-block confirmed sellers after classification is committed.
    # A block failure must not mark a saved classification as failed.
    block_status = "not_seller"

    if data["seller_type"] == "seller":
        try:
            from seller_block_service import block_seller

            block_result = block_seller(
                engine=engine,
                post_id=post["id"],
                classification_id=classification_id,
                execute=True,
            )

            block_status = block_result["status"]
            print("AUTO BLOCK:", block_result)

        except Exception as exc:
            block_status = "error"
            print(
                "AUTO BLOCK ERROR:",
                type(exc).__name__,
                str(exc),
            )

    print("INPUT TOKENS:", input_tokens)
    print("OUTPUT TOKENS:", output_tokens)
    print("TOTAL TOKENS:", total_tokens)
    print("PROCESSING MS:", processing_ms)
    print("CACHED INPUT TOKENS:", cached_tokens)
    print("ESTIMATED COST USD:", estimated_cost_usd)
    print(json.dumps(data, ensure_ascii=False, indent=2))

    return {
        "status": "success",
        "post_id": post["id"],
        "classification_id": classification_id,
        "auto_block_status": block_status,
        "prompt_version": prompt["version"],
        "model": model,
        "post_type": data["post_type"],
        "seller_type": data["seller_type"],
        "confidence": data["confidence"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "processing_ms": processing_ms,
        "estimated_cost_usd": (
            float(estimated_cost_usd)
            if estimated_cost_usd is not None else None
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    return classify_post(
        post_id=args.post_id,
        execute=args.execute
    )


if __name__ == "__main__":
    main()
