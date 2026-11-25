import argparse
import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from batch_classification_worker_v2 import (
    get_tasks,
    estimate_cost,
    RATES,
    STAGE1_OUTPUT_LIMIT,
    STAGE2_OUTPUT_LIMIT,
)
from classification_worker_v2 import classify_stage1
from extraction_worker import extract_products

LOCK_KEY_1 = 20261120
LOCK_KEY_2 = 2


def execute_batch(limit, budget):
    from main import engine

    stage1_model = os.getenv(
        "MACKET_CLASSIFICATION_MODEL", "gpt-4.1-mini"
    )
    stage2_model = os.getenv(
        "MACKET_EXTRACTION_MODEL", "gpt-4.1-mini"
    )

    for model in (stage1_model, stage2_model):
        if model not in RATES:
            raise RuntimeError(f"UNKNOWN MODEL PRICING: {model}")

    with engine.connect() as conn:
        prompt = conn.execute(text("""
            SELECT system_prompt
            FROM ai_prompt_versions
            WHERE version = 7
        """)).scalar_one()

        conn.commit()

    stage2_prompt = (
        Path(__file__).resolve().parent
        / "stage2_extraction_prompt.txt"
    ).read_text(encoding="utf-8")

    reserved = Decimal("0")
    actual = Decimal("0")
    success = 0
    failed = 0
    requests = 0

    # Session-level advisory lock shared with Batch v1.
    with engine.connect() as lock_conn:
        acquired = lock_conn.execute(text("""
            SELECT pg_try_advisory_lock(:a, :b)
        """), {
            "a": LOCK_KEY_1,
            "b": LOCK_KEY_2,
        }).scalar_one()

        lock_conn.commit()

        if not acquired:
            raise RuntimeError("ANOTHER BATCH IS RUNNING")

        try:
            print("=== MACKET BATCH V2 EXECUTE ===")
            print("BUDGET: $", budget)
            print("REQUEST LIMIT:", limit)
            print("ADVISORY LOCK: ACQUIRED")

            while requests < limit:
                with engine.connect() as conn:
                    stage2, stage1 = get_tasks(conn, 1)

                if stage2:
                    task_type = "stage2"
                    row = stage2[0]
                    target_id = row["classification_id"]
                    post_id = row["post_id"]

                    estimated = estimate_cost(
                        stage2_prompt,
                        {"content": row["content"]},
                        stage2_model,
                        STAGE2_OUTPUT_LIMIT,
                    )

                elif stage1:
                    task_type = "stage1"
                    row = stage1[0]
                    target_id = row["post_id"]
                    post_id = row["post_id"]

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

                else:
                    print("NO MORE ELIGIBLE TASKS")
                    break

                # Use known actual costs for completed requests.
                # Reserve the full estimate only for the next request.
                if actual + estimated > budget:
                    print(
                        "BUDGET LIMIT BEFORE:",
                        task_type,
                        target_id,
                    )
                    break

                print(
                    f"\n[{task_type.upper()}] "
                    f"POST #{post_id} | "
                    f"RESERVE ${estimated:.8f}"
                )

                reserved += estimated
                requests += 1

                try:
                    if task_type == "stage1":
                        result = classify_stage1(
                            post_id=target_id,
                            execute=True,
                        )

                        if result["status"] != "success":
                            print("SKIPPED:", result["status"])
                            continue

                    else:
                        result = extract_products(
                            classification_id=target_id,
                            execute=True,
                        )

                        if result["status"] != "completed":
                            print("SKIPPED:", result["status"])
                            continue

                    cost = result.get("estimated_cost_usd")

                    success += 1

                    if cost is None:
                        print("COST UNKNOWN - STOPPING")
                        break

                    actual += Decimal(str(cost))

                    print(
                        "REQUEST COMPLETE | "
                        f"ACTUAL EST. ${Decimal(str(cost)):.8f}"
                    )

                except Exception as exc:
                    failed += 1
                    print(
                        "REQUEST FAILED:",
                        type(exc).__name__,
                    )
                    print(
                        "STOPPING: FAILED REQUEST "
                        "MAY STILL INCUR COST"
                    )
                    break

        finally:
            lock_conn.rollback()
            lock_conn.execute(text("""
                SELECT pg_advisory_unlock(:a, :b)
            """), {
                "a": LOCK_KEY_1,
                "b": LOCK_KEY_2,
            })
            lock_conn.commit()

            print("\n=== BATCH V2 SUMMARY ===")
            print("REQUESTS:", requests)
            print("SUCCESS:", success)
            print("FAILED:", failed)
            print("ACTUAL ESTIMATED COST: $", actual)
            print("RESERVED BUDGET: $", reserved)
            print("ADVISORY LOCK: RELEASED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--budget", default="0.01")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        raise SystemExit(
            "Execution requires --execute. "
            "Use batch_classification_worker_v2.py for dry run."
        )

    if not 1 <= args.limit <= 10:
        raise SystemExit("LIMIT MUST BE 1..10")

    try:
        budget = Decimal(args.budget)
    except Exception:
        raise SystemExit("INVALID BUDGET")

    if not budget.is_finite() or not (
        Decimal("0") < budget <= Decimal("1")
    ):
        raise SystemExit("INVALID BUDGET")

    execute_batch(args.limit, budget)


if __name__ == "__main__":
    main()
