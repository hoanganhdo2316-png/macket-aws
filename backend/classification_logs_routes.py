from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from admin_routes import verify_admin

router = APIRouter(
    prefix="/api/admin/classification-logs",
    tags=["AI Classification Logs"],
    dependencies=[Depends(verify_admin)]
)


def register_classification_logs_routes(app, engine):

    @router.get("")
    def list_classification_logs(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        seller_type: str | None = Query(None),
        post_id: int | None = Query(None),
    ):
        where = ["1=1"]
        params = {
            "limit": limit,
            "offset": offset,
        }

        if seller_type:
            where.append("c.seller_type = :seller_type")
            params["seller_type"] = seller_type

        if post_id is not None:
            where.append("c.post_id = :post_id")
            params["post_id"] = post_id

        condition = " AND ".join(where)

        with engine.connect() as conn:
            total = conn.execute(text(f"""
                SELECT COUNT(*)
                FROM post_classifications c
                WHERE {condition}
            """), params).scalar_one()

            rows = conn.execute(text(f"""
                SELECT
                    c.id,
                    c.post_id,
                    p.author_name,
                    p.author_id,
                    p.url AS post_url,
                    LEFT(p.content, 300) AS content_preview,
                    c.post_type,
                    c.seller_type,
                    c.confidence,
                    c.reason,
                    c.products,
                    c.location,
                    c.model,
                    c.input_tokens,
                    c.output_tokens,
                    c.total_tokens,
                    c.processing_ms,
                    c.estimated_cost_usd,
                    v.version AS prompt_version,
                    c.created_at
                FROM post_classifications c
                JOIN posts p ON p.id = c.post_id
                JOIN ai_prompt_versions v
                    ON v.id = c.prompt_version_id
                WHERE {condition}
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT :limit OFFSET :offset
            """), params).mappings().all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }

    @router.get("/stats")
    def get_classification_stats():
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT
                    COUNT(*) AS total_classifications,
                    COUNT(DISTINCT post_id) AS unique_posts,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0)
                        AS estimated_cost_usd,
                    COUNT(*) FILTER (
                        WHERE estimated_cost_usd IS NULL
                    ) AS unpriced_classifications
                FROM post_classifications
            """)).mappings().one()

        return {
            **dict(row),
            "estimated_cost_usd": float(
                row["estimated_cost_usd"]
            )
        }

    @router.get("/{classification_id}")
    def get_classification_log(classification_id: int):
        from fastapi import HTTPException

        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT
                    c.*,
                    p.author_name,
                    p.author_id,
                    p.url AS post_url,
                    p.content AS post_content,
                    v.version AS prompt_version
                FROM post_classifications c
                JOIN posts p ON p.id = c.post_id
                JOIN ai_prompt_versions v
                    ON v.id = c.prompt_version_id
                WHERE c.id = :id
            """), {"id": classification_id}).mappings().first()

        if not row:
            raise HTTPException(404, "Classification not found")

        return dict(row)

    app.include_router(router)
