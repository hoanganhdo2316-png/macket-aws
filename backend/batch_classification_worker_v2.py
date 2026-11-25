import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

import tiktoken
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(".env")

STAGE1_OUTPUT_LIMIT = 1000
STAGE2_OUTPUT_LIMIT = 4000

RATES = {
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-mini-2025-04-14": (
        Decimal("0.40"), Decimal("1.60")
    ),
}


def estimate_cost(prompt, payload, model, output_limit):
    encoding = tiktoken.encoding_for_model(model)

    payload_text = json.dumps(
        payload, ensure_ascii=False
    )

    input_tokens = (
        len(encoding.encode(prompt))
        + len(encoding.encode(payload_text))
        + 250
    )

    estimated_input = int(input_tokens * 1.20) + 1

    input_rate, output_rate = RATES[model]

    return (
        Decimal(estimated_input) * input_rate
        + Decimal(output_limit) * output_rate
    ) / Decimal(1_000_000)


def get_tasks(conn, limit):
    # Stage 2: existing individual classifications.
    stage2 = conn.execute(text("""
        SELECT
            c.id AS classification_id,
            c.post_id,
            p.author_name,
            p.content
        FROM post_classifications c
        JOIN posts p ON p.id = c.post_id
        JOIN ai_prompt_versions v
            ON v.id = c.prompt_version_id
        WHERE v.version = 7
          AND c.post_type = 'selling'
          AND c.seller_type = 'individual'
          AND c.extraction_status IN ('pending', 'failed')
          AND c.extraction_attempts < 3
        ORDER BY c.id
        LIMIT :limit
    """), {"limit": limit}).mappings().all()

    # Stage 1: posts not yet classified by v7.
    stage1 = conn.execute(text("""
        SELECT
            p.id AS post_id,
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
              JOIN ai_prompt_versions v
                ON v.id = c.prompt_version_id
              WHERE c.post_id = p.id
                AND v.version = 7
          )

          AND NOT EXISTS (
              SELECT 1
              FROM stage1_claims sc
              WHERE sc.post_id = p.id
                AND sc.prompt_version_id = 7
          )

          AND NOT EXISTS (
              SELECT 1
              FROM author_skip_list a
              WHERE a.skip_enabled = TRUE
                AND (
                    a.facebook_author_id = p.author_id
                    OR a.profile_url = p.author_url
                )
          )
        ORDER BY p.id
        LIMIT :limit
    """), {"limit": limit}).mappings().all()

    return stage2, stage1


def dry_run(limit, budget):
    from main import engine

    stage1_model = os.getenv(
        "MACKET_CLASSIFICATION_MODEL", "gpt-4.1-mini"
    )
    stage2_model = os.getenv(
        "MACKET_EXTRACTION_MODEL", "gpt-4.1-mini"
    )

    for model in (stage1_model, stage2_model):
        if model not in RATES:
            raise RuntimeError(
                f"NO PRICING CONFIGURED: {model}"
            )

    prompt_path = (
        Path(__file__).resolve().parent
        / "stage2_extraction_prompt.txt"
    )

    stage2_prompt = prompt_path.read_text(
        encoding="utf-8"
    )

    with engine.connect() as conn:
        prompt = conn.execute(text("""
            SELECT system_prompt
            FROM ai_prompt_versions
            WHERE version = 7
        """)).scalar_one()

        stage2, stage1 = get_tasks(conn, limit)

    reserved = Decimal("0")
    selected = 0

    print("=== MACKET BATCH V2 ===")
    print("MODE: DRY RUN")
    print("STAGE 1 MODEL:", stage1_model)
    print("STAGE 2 MODEL:", stage2_model)
    print("PROMPT VERSION: 7")
    print("BUDGET: $", budget)
    print("PENDING STAGE 2:", len(stage2))
    print("NEW STAGE 1:", len(stage1))

    for row in stage2:
        if selected >= limit:
            break

        estimated = estimate_cost(
            stage2_prompt,
            {"content": row["content"]},
            stage2_model,
            STAGE2_OUTPUT_LIMIT,
        )

        if reserved + estimated > budget:
            print("BUDGET LIMIT: STAGE 2")
            break

        reserved += estimated
        selected += 1

        print(
            f"[STAGE 2] CLASSIFICATION "
            f"#{row['classification_id']} | "
            f"POST #{row['post_id']} | "
            f"MAX EST. ${estimated:.8f}"
        )

    if selected < limit:
        for row in stage1:
            if selected >= limit:
                break

            estimated = estimate_cost(
                prompt,
                {
                    "content": row["content"],
                    "author_name": row["author_name"],
                    "author_id": row["author_id"],
                    "author_url": row["author_url"],
                },
                stage1_model,
                STAGE1_OUTPUT_LIMIT,
            )

            if reserved + estimated > budget:
                print("BUDGET LIMIT: STAGE 1")
                break

            reserved += estimated
            selected += 1

            print(
                f"[STAGE 1] POST #{row['post_id']} | "
                f"{row['author_name']} | "
                f"MAX EST. ${estimated:.8f}"
            )

    print("\n=== BATCH V2 SUMMARY ===")
    print("SELECTED REQUESTS:", selected)
    print("RESERVED BUDGET: $", reserved)
    print("REMAINING BUDGET: $", budget - reserved)
    print("OPENAI REQUESTS: 0")
    print("DATABASE WRITES: 0")
    print(
        "NOTE: Stage 2 for newly classified "
        "individuals is not included in this estimate."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--budget", default="0.02")
    args = parser.parse_args()

    if not 1 <= args.limit <= 10:
        raise SystemExit("LIMIT MUST BE 1..10")

    try:
        budget = Decimal(args.budget)
    except Exception:
        raise SystemExit("INVALID BUDGET")

    if not (
        budget.is_finite()
        and Decimal("0") < budget <= Decimal("1")
    ):
        raise SystemExit("INVALID BUDGET")

    dry_run(args.limit, budget)


if __name__ == "__main__":
    main()
