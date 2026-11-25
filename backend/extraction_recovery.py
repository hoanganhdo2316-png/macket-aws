import argparse

from main import engine
from sqlalchemy import text


def recover_extraction(classification_id, execute=False):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, post_id, extraction_status,
                   extraction_started_at, extraction_attempts
            FROM post_classifications
            WHERE id = :id
        """), {"id": classification_id}).mappings().first()

    if row is None:
        return {"status": "not_found"}

    if row["extraction_status"] != "processing":
        return {
            "status": "not_processing",
            "current_status": row["extraction_status"],
        }

    with engine.connect() as conn:
        stale = conn.execute(text("""
            SELECT (
                extraction_started_at IS NULL
                OR extraction_started_at < NOW() - INTERVAL '10 minutes'
            )
            FROM post_classifications
            WHERE id = :id
        """), {"id": classification_id}).scalar_one()

    if not stale:
        return {"status": "still_processing"}

    if not execute:
        return {
            "status": "would_recover",
            "classification_id": classification_id,
            "post_id": row["post_id"],
        }

    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE post_classifications
            SET extraction_status = 'failed',
                extraction_started_at = NULL,
                extraction_error = 'Recovered stale processing task'
            WHERE id = :id
              AND extraction_status = 'processing'
              AND (
                  extraction_started_at IS NULL
                  OR extraction_started_at <
                      NOW() - INTERVAL '10 minutes'
              )
            RETURNING id
        """), {"id": classification_id}).scalar_one_or_none()

    return {
        "status": "recovered" if result else "state_changed",
        "classification_id": classification_id,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--classification-id", type=int, required=True)
    parser.add_argument("--execute", action="store_true")

    args = parser.parse_args()

    print(recover_extraction(
        args.classification_id,
        execute=args.execute,
    ))
