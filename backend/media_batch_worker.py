"""Bounded, idempotent media runner for the existing per-post media worker."""

import argparse
import json
from sqlalchemy import text
from media_worker import process_post

LOCK_KEY_1, LOCK_KEY_2 = 20261120, 3


def pending_posts(conn, limit):
    return conn.execute(text("""
        SELECT p.id FROM posts p
        WHERE p.source = 'facebook'
          AND COALESCE(jsonb_array_length(p.raw_data->'imageUrls'), 0) > 0
          AND EXISTS (SELECT 1 FROM post_classifications c WHERE c.post_id = p.id
                      AND c.post_type = 'selling' AND c.seller_type = 'individual'
                      AND c.extraction_status = 'completed')
          AND (SELECT COUNT(*) FROM post_images i WHERE i.post_id = p.id)
              < COALESCE(jsonb_array_length(p.raw_data->'imageUrls'), 0)
        ORDER BY p.collected_at DESC, p.id DESC LIMIT :limit
    """), {"limit": limit}).scalars().all()


def run_media_batch(limit=1, execute=False):
    if not 1 <= limit <= 10:
        raise ValueError("limit must be 1..10")
    from main import engine
    with engine.connect() as lock_conn:
        locked = lock_conn.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), {"a": LOCK_KEY_1, "b": LOCK_KEY_2}).scalar_one()
        lock_conn.commit()
        if not locked:
            return {"status": "already_running", "selected": 0}
        try:
            post_ids = pending_posts(lock_conn, limit)
            if not execute:
                return {"status": "dry_run", "selected": len(post_ids)}
            results = [process_post(post_id, execute=True) for post_id in post_ids]
            return {"status": "completed", "selected": len(post_ids),
                    "uploaded": sum(row.get("uploaded", 0) for row in results),
                    "failed": sum(row.get("failed", 0) for row in results)}
        finally:
            lock_conn.rollback()
            lock_conn.execute(text("SELECT pg_advisory_unlock(:a, :b)"), {"a": LOCK_KEY_1, "b": LOCK_KEY_2})
            lock_conn.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_media_batch(args.limit, args.execute), sort_keys=True))
