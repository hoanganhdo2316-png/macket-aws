import argparse
import json
import os
from decimal import Decimal

import tiktoken
from dotenv import load_dotenv
from sqlalchemy import text

from classification_worker import classify_post

load_dotenv(".env")

LOCK_KEY_1 = 20261120
LOCK_KEY_2 = 2

MAX_OUTPUT_TOKENS = 4000

# USD / 1 million tokens. Conservative: no caching discount.
MODEL_RATES = {
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-mini-2025-04-14": (
        Decimal("0.40"), Decimal("1.60")
    ),
}


def estimate_cost(prompt, row, model):
    encoding = tiktoken.encoding_for_model(model)

    payload = json.dumps({
        "content": row["content"],
        "author_name": row["author_name"],
        "author_id": row["author_id"],
        "author_url": row["author_url"],
    }, ensure_ascii=False)

    tokens = (
        len(encoding.encode(prompt))
        + len(encoding.encode(payload))
        + 250
    )

    # Extra margin for token-count differences and message overhead.
    estimated_input = int(tokens * 1.20) + 1

    input_rate, output_rate = MODEL_RATES[model]

    cost = (
        Decimal(estimated_input) * input_rate
        + Decimal(MAX_OUTPUT_TOKENS) * output_rate
    ) / Decimal(1_000_000)

    return cost


def select_posts(conn, prompt_id, limit):
    return conn.execute(text("""
        SELECT
            p.id,
            p.author_name,
            p.author_id,
            p.author_url,
            p.content
        FROM posts p
        WHERE p.source = 'facebook'
          AND p.content IS NOT NULL
          AND LENGTH(TRIM(p.content)) >= 10

          AND NOT EXISTS (
              SELECT 1
              FROM post_classifications c
              WHERE c.post_id = p.id
                AND c.prompt_version_id = :prompt_id
          )

          AND NOT EXISTS (
              SELECT 1
              FROM author_skip_list a
              WHERE a.skip_enabled = TRUE
                AND (
                    (
                        p.author_id IS NOT NULL
                        AND a.facebook_author_id = p.author_id
                    )
                    OR (
                        p.author_url IS NOT NULL
                        AND a.profile_url = p.author_url
                    )
                )
          )

        ORDER BY p.id ASC
        LIMIT :limit
    """), {
        "prompt_id": prompt_id,
        "limit": limit
    }).mappings().all()


def run_batch(conn, engine, args):
    active = conn.execute(text("""
        SELECT id, version, system_prompt
        FROM ai_prompt_versions
        WHERE is_active = TRUE
    """)).mappings().first()

    if not active:
        raise RuntimeError("NO ACTIVE SYSTEM PROMPT")

    if "test prompt" in active["system_prompt"].lower():
        raise RuntimeError("TEST PROMPT IS ACTIVE")

    model = os.getenv(
        "MACKET_CLASSIFICATION_MODEL",
        "gpt-4.1-mini"
    )

    if model not in MODEL_RATES:
        raise RuntimeError(
            f"NO PRICING CONFIGURED FOR MODEL: {model}"
        )

    rows = select_posts(conn, active["id"], args.limit)

    budget = Decimal(args.budget)
    reserved = Decimal("0")
    spent = Decimal("0")
    success = 0
    failed = 0

    print("=== MACKET BATCH CLASSIFICATION ===")
    print("MODE:", "EXECUTE" if args.execute else "DRY RUN")
    print("PROMPT VERSION:", active["version"])
    print("MODEL:", model)
    print("BUDGET: $", budget)
    print("SELECTED POSTS:", len(rows))

    for index, row in enumerate(rows, 1):
        post_id = row["id"]

        estimated = estimate_cost(
            active["system_prompt"],
            row,
            model
        )

        # Reserve the conservative per-request estimate.
        if reserved + estimated > budget:
            print(
                "BUDGET LIMIT REACHED BEFORE POST:",
                post_id
            )
            break

        if not args.execute:
            print(
                f"[{index}] POST #{post_id} | "
                f"{row['author_name']} | "
                f"EST. MAX ${estimated:.8f}"
            )
            reserved += estimated
            continue

        # Recheck the live database before each request.
        with engine.connect() as check_conn:
            eligible = select_posts(
                check_conn, active["id"], args.limit
            )
            eligible_ids = {p["id"] for p in eligible}

            current_prompt_id = check_conn.execute(text("""
                SELECT id FROM ai_prompt_versions
                WHERE is_active = TRUE
            """)).scalar_one_or_none()

        if current_prompt_id != active["id"]:
            print("ACTIVE PROMPT CHANGED - STOPPING")
            break

        if post_id not in eligible_ids:
            print("SKIPPED - NO LONGER ELIGIBLE:", post_id)
            continue

        print(f"\nPROCESSING POST #{post_id}")

        # Reserve before calling the external API.
        reserved += estimated

        try:
            result = classify_post(
                post_id=post_id,
                execute=True
            )

            actual = result.get("estimated_cost_usd")

            if actual is None:
                print("COST UNKNOWN - STOPPING")
                success += 1
                break

            spent += Decimal(str(actual))
            success += 1

            print(
                "BATCH PROGRESS:",
                f"success={success}",
                f"spent=${spent:.8f}"
            )

        except Exception as error:
            failed += 1
            print(
                f"FAILED POST #{post_id}: "
                f"{type(error).__name__}"
            )
            # Unknown external API cost after failure.
            # Stop rather than risk additional charges.
            print("STOPPING DUE TO UNKNOWN REQUEST COST")
            break

    print("\n=== BATCH SUMMARY ===")
    print("SUCCESS:", success)
    print("FAILED:", failed)
    print("ACTUAL ESTIMATED COST: $", spent)
    print("RESERVED BUDGET: $", reserved)

    if not args.execute:
        print("DRY RUN COMPLETED")
        print("OPENAI REQUESTS: 0")
        print("DATABASE WRITES: 0")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--budget", default="0.02")
    parser.add_argument("--execute", action="store_true")

    args = parser.parse_args()

    if not 1 <= args.limit <= 10:
        raise SystemExit("LIMIT MUST BE BETWEEN 1 AND 10")

    try:
        budget = Decimal(args.budget)
    except Exception:
        raise SystemExit("INVALID BUDGET")

    if not budget.is_finite() or not Decimal("0") < budget <= Decimal("1"):
        raise SystemExit("BUDGET MUST BE BETWEEN 0 AND 1 USD")

    from main import engine

    with engine.connect() as conn:
        acquired = conn.execute(text("""
            SELECT pg_try_advisory_lock(:a, :b)
        """), {
            "a": LOCK_KEY_1,
            "b": LOCK_KEY_2
        }).scalar_one()

        if not acquired:
            raise SystemExit("ANOTHER BATCH IS RUNNING")

        try:
            run_batch(conn, engine, args)
        finally:
            conn.execute(text("""
                SELECT pg_advisory_unlock(:a, :b)
            """), {
                "a": LOCK_KEY_1,
                "b": LOCK_KEY_2
            })


if __name__ == "__main__":
    main()
