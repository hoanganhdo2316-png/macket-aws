import argparse
from main import engine
from sqlalchemy import text


def recover_claim(claim_id, execute=False, worker_stopped=False):
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT
                sc.id,
                sc.post_id,
                sc.prompt_version_id,
                sc.status,
                sc.claimed_at,
                sc.classification_id,
                EXISTS (
                    SELECT 1
                    FROM post_classifications c
                    WHERE c.post_id = sc.post_id
                      AND c.prompt_version_id = sc.prompt_version_id
                ) AS has_classification,
                (
                    sc.status = 'failed'
                    OR (
                        sc.status = 'processing'
                        AND sc.claimed_at <
                            NOW() - INTERVAL '10 minutes'
                    )
                ) AS eligible
            FROM stage1_claims sc
            WHERE sc.id = :id
            FOR UPDATE OF sc
        """), {"id": claim_id}).mappings().first()

        if row is None:
            return {"status": "not_found"}

        if row["has_classification"] or row["classification_id"]:
            return {"status": "classification_exists"}

        if not row["eligible"]:
            return {
                "status": "not_eligible",
                "current_status": row["status"],
            }

        if not execute:
            return {
                "status": "would_recover",
                "claim_id": claim_id,
                "post_id": row["post_id"],
            }

        if not worker_stopped:
            return {"status": "worker_stop_confirmation_required"}

        # Preserve an audit record before deleting the claim.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stage1_claim_recovery_audit (
                id BIGSERIAL PRIMARY KEY,
                claim_id BIGINT NOT NULL,
                post_id BIGINT NOT NULL,
                prompt_version_id BIGINT NOT NULL,
                previous_status VARCHAR(20) NOT NULL,
                recovered_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))

        conn.execute(text("""
            INSERT INTO stage1_claim_recovery_audit (
                claim_id, post_id, prompt_version_id,
                previous_status
            )
            VALUES (
                :claim_id, :post_id, :prompt_id, :status
            )
        """), {
            "claim_id": claim_id,
            "post_id": row["post_id"],
            "prompt_id": row["prompt_version_id"],
            "status": row["status"],
        })

        conn.execute(text("""
            DELETE FROM stage1_claims
            WHERE id = :id
        """), {"id": claim_id})

        return {
            "status": "recovered",
            "claim_id": claim_id,
            "post_id": row["post_id"],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--claim-id", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--confirm-worker-stopped",
        action="store_true",
    )
    args = parser.parse_args()

    print(recover_claim(
        args.claim_id,
        execute=args.execute,
        worker_stopped=args.confirm_worker_stopped,
    ))
