from main import engine
from sqlalchemy import text


def scan_extractions(minutes=10):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                id AS classification_id,
                post_id,
                extraction_status,
                extraction_attempts,
                extraction_started_at,
                extraction_error
            FROM post_classifications
            WHERE extraction_status = 'failed'
               OR (
                   extraction_status = 'processing'
                   AND (
                       extraction_started_at IS NULL
                       OR extraction_started_at <
                           NOW() - (:minutes * INTERVAL '1 minute')
                   )
               )
            ORDER BY id
        """), {"minutes": minutes}).mappings().all()

    print("=== STAGE 2 RECOVERY SCAN ===")
    print("THRESHOLD:", minutes, "minutes")
    print("TASKS REQUIRING REVIEW:", len(rows))

    for row in rows:
        print(dict(row))

    return rows


if __name__ == "__main__":
    scan_extractions()
