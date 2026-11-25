from main import engine
from sqlalchemy import text


def inspect_claims(minutes=10):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                sc.id AS claim_id,
                sc.post_id,
                p.author_name,
                sc.status,
                sc.claimed_at,
                sc.completed_at,
                sc.classification_id,
                sc.error_type,
                NOW() - sc.claimed_at AS elapsed
            FROM stage1_claims sc
            JOIN posts p ON p.id = sc.post_id
            WHERE
                sc.status = 'failed'
                OR (
                    sc.status = 'processing'
                    AND sc.claimed_at <
                        NOW() - (:minutes * INTERVAL '1 minute')
                )
            ORDER BY sc.claimed_at
        """), {"minutes": minutes}).mappings().all()

    print("=== STAGE 1 CLAIM RECOVERY SCAN ===")
    print("STALE THRESHOLD:", minutes, "minutes")
    print("CLAIMS REQUIRING REVIEW:", len(rows))

    for row in rows:
        print("\n" + "=" * 45)
        for key, value in row.items():
            print(f"{key}: {value}")

    return rows


if __name__ == "__main__":
    inspect_claims()
