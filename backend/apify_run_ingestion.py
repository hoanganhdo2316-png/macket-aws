import json
import os
from urllib.request import Request, urlopen

from sqlalchemy import text

from apify_dataset import fetch_dataset
from apify_ingestion import ingest_items


def apify_get(path, *, token=None, timeout=30):
    if token is None:
        token = os.environ["APIFY_TOKEN"]

    request = Request(
        "https://api.apify.com/v2/" + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        return json.load(response)["data"]


def ingest_run(engine, run_id):
    if not run_id or not isinstance(run_id, str):
        raise ValueError("Invalid Apify Run ID")

    # Check whether this run has already been imported.
    with engine.connect() as conn:
        existing = conn.execute(text("""
            SELECT status, total_posts, inserted_posts, duplicate_posts, skipped_posts
            FROM crawl_runs
            WHERE apify_run_id = :run_id
        """), {"run_id": run_id}).mappings().first()

    if existing and existing["status"] in ("INGESTED", "FAILED"):
        return {
            "run_id": run_id,
            "status": "ALREADY_" + existing["status"],
            **{
                key: existing[key]
                for key in (
                    "total_posts",
                    "inserted_posts",
                    "duplicate_posts",
                    "skipped_posts",
                )
            },
        }

    run = apify_get(f"actor-runs/{run_id}")

    expected_actor_id = "dGw5RQgZjVug05E1h"

    if run.get("actId") != expected_actor_id:
        raise ValueError(
            "Apify Run belongs to an unauthorized Actor"
        )

    if run["status"] != "SUCCEEDED":
        raise ValueError(
            f"Run is not successful: {run['status']}"
        )

    dataset_id = run.get("defaultDatasetId")

    if not dataset_id:
        raise ValueError("Run has no dataset")

    dataset = apify_get(f"datasets/{dataset_id}")
    item_count = dataset.get("itemCount", 0)

    # Current fetch_dataset() supports a maximum of 100 items.
    # Reject larger datasets instead of silently losing posts.
    if item_count > 100:
        raise ValueError(
            "Dataset exceeds 100 items; pagination is required"
        )

    items = fetch_dataset(dataset_id, limit=100)

    if len(items) != item_count:
        raise ValueError(
            f"Dataset count mismatch: expected {item_count}, "
            f"received {len(items)}"
        )

    # Posts and crawl history commit or roll back together.
    with engine.begin() as conn:
        scan = conn.execute(text("""
            SELECT scan_id, source FROM collector_scan
            WHERE id = 1 AND apify_run_id = :run_id
        """), {"run_id": run_id}).mappings().first()
        claim = conn.execute(text("""
            INSERT INTO crawl_runs (
                apify_run_id,
                apify_dataset_id,
                scan_id,
                source,
                status
            )
            VALUES (:run_id, :dataset_id, :scan_id, :source, 'PROCESSING')
            ON CONFLICT (apify_run_id) DO NOTHING
            RETURNING id
        """), {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "scan_id": scan["scan_id"] if scan else None,
            "source": scan["source"] if scan else None,
        }).scalar_one_or_none()

        if claim is None:
            raise ValueError(
                "Run already exists in crawl_runs; "
                "manual reconciliation required"
            )

        result = ingest_items(engine, items, conn=conn, crawl_run_id=claim)

        status = "FAILED" if result["total_posts"] and result["skipped_posts"] == result["total_posts"] else "INGESTED"
        conn.execute(text("""
            UPDATE crawl_runs
            SET status = :status,
                total_posts = :total,
                inserted_posts = :inserted,
                duplicate_posts = :duplicates,
                skipped_posts = :skipped,
                finished_at = NOW()
            WHERE id = :id
        """), {
            "status": status,
            "total": result["total_posts"],
            "inserted": result["inserted_posts"],
            "duplicates": result["duplicate_posts"],
            "skipped": result["skipped_posts"],
            "id": claim,
        })

    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "status": status,
        **result,
    }
