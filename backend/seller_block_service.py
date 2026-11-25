from sqlalchemy import text

CONFIDENCE_THRESHOLD = 0.90


def block_seller(
    engine,
    post_id: int,
    classification_id: int,
    execute: bool = False,
):
    """
    Default: dry run.
    Existing Admin decisions are never overwritten.
    """

    with engine.begin() as conn:

        row = conn.execute(text("""
            SELECT
                p.author_id,
                p.author_url,
                p.author_name,
                c.seller_type,
                c.confidence
            FROM post_classifications c
            JOIN posts p ON p.id = c.post_id
            WHERE c.id = :classification_id
              AND c.post_id = :post_id
        """), {
            "classification_id": classification_id,
            "post_id": post_id,
        }).mappings().first()

        if not row:
            return {"status": "classification_not_found"}

        if row["seller_type"] != "seller":
            return {"status": "not_seller"}

        confidence = row["confidence"]

        if confidence is None or confidence < CONFIDENCE_THRESHOLD:
            return {"status": "low_confidence"}

        author_id = (row["author_id"] or "").strip() or None
        author_url = (row["author_url"] or "").strip() or None
        author_name = (row["author_name"] or "").strip() or None

        if not author_id and not author_url:
            return {"status": "missing_author_identity"}

        # Check both identifiers. Do not overwrite existing records
        # or previously disabled authors.
        existing = conn.execute(text("""
            SELECT id, skip_enabled
            FROM author_skip_list
            WHERE (
                facebook_author_id = CAST(:author_id AS VARCHAR)
            )
            OR (
                profile_url = CAST(:author_url AS TEXT)
            )
        """), {
            "author_id": author_id,
            "author_url": author_url,
        }).mappings().all()

        if existing:
            return {
                "status": "already_exists",
                "existing_ids": [r["id"] for r in existing],
            }

        if not execute:
            return {
                "status": "would_block",
                "post_id": post_id,
                "classification_id": classification_id,
                "author_name": author_name,
                "confidence": confidence,
            }

        # ON CONFLICT handles concurrent insert races
        # without overwriting any Admin decisions.
        inserted = conn.execute(text("""
            INSERT INTO author_skip_list (
                facebook_author_id,
                profile_url,
                display_name,
                classification,
                skip_enabled,
                reason,
                created_at,
                updated_at
            )
            VALUES (
                :author_id,
                :author_url,
                :author_name,
                'seller',
                TRUE,
                :reason,
                NOW(),
                NOW()
            )
            ON CONFLICT DO NOTHING
            RETURNING id
        """), {
            "author_id": author_id,
            "author_url": author_url,
            "author_name": author_name,
            "reason": (
                f"AI Classification #{classification_id}; "
                f"confidence={confidence:.2f}"
            ),
        }).scalar_one_or_none()

        if inserted is None:
            return {"status": "already_exists_or_conflict"}

        return {
            "status": "blocked",
            "author_skip_id": inserted,
            "post_id": post_id,
            "classification_id": classification_id,
        }
