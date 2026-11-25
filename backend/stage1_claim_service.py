from sqlalchemy import text


def acquire_claim(engine, post_id, prompt_version_id):
    with engine.begin() as conn:
        # Avoid reclassifying posts already processed.
        existing = conn.execute(text("""
            SELECT id
            FROM post_classifications
            WHERE post_id = :post_id
              AND prompt_version_id = :prompt_id
            ORDER BY id DESC
            LIMIT 1
        """), {
            "post_id": post_id,
            "prompt_id": prompt_version_id,
        }).scalar_one_or_none()

        if existing is not None:
            return {
                "status": "already_classified",
                "classification_id": existing,
            }

        # UNIQUE(post_id, prompt_version_id) guarantees
        # only one worker can acquire this claim.
        claim_id = conn.execute(text("""
            INSERT INTO stage1_claims (
                post_id,
                prompt_version_id,
                status,
                claimed_at
            )
            VALUES (
                :post_id,
                :prompt_id,
                'processing',
                NOW()
            )
            ON CONFLICT (post_id, prompt_version_id)
            DO NOTHING
            RETURNING id
        """), {
            "post_id": post_id,
            "prompt_id": prompt_version_id,
        }).scalar_one_or_none()

        if claim_id is None:
            return {"status": "already_claimed"}

        return {
            "status": "acquired",
            "claim_id": claim_id,
        }


def complete_claim(conn, claim_id, classification_id):
    result = conn.execute(text("""
        UPDATE stage1_claims
        SET status = 'completed',
            completed_at = NOW(),
            classification_id = :classification_id,
            error_type = NULL
        WHERE id = :claim_id
          AND status = 'processing'
        RETURNING id
    """), {
        "claim_id": claim_id,
        "classification_id": classification_id,
    }).scalar_one_or_none()

    if result is None:
        raise RuntimeError("STAGE 1 CLAIM FINALIZE CONFLICT")


def fail_claim(engine, claim_id, error_type):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE stage1_claims
            SET status = 'failed',
                completed_at = NOW(),
                error_type = :error_type
            WHERE id = :claim_id
              AND status = 'processing'
        """), {
            "claim_id": claim_id,
            "error_type": error_type[:150],
        })
