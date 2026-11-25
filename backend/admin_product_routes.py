from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from admin_routes import verify_admin
from client_routes import get_images

router = APIRouter(
    prefix="/api/admin/products",
    tags=["Admin Products"],
    dependencies=[Depends(verify_admin)],
)

class HideRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


BASE = """
FROM posts p
JOIN LATERAL (
    SELECT c.*
    FROM post_classifications c
    WHERE c.post_id = p.id
    ORDER BY c.created_at DESC, c.id DESC
    LIMIT 1
) c ON TRUE
LEFT JOIN post_moderation m ON m.post_id = p.id
WHERE p.source = 'facebook'
  AND c.post_type = 'selling'
  AND c.seller_type = 'individual'
  AND c.extraction_status = 'completed'
  AND jsonb_typeof(c.products) = 'array'
  AND jsonb_array_length(c.products) > 0
"""

def register_admin_product_routes(app, engine):

    @router.get("")
    def list_admin_products(
        status: str = Query("all", pattern="^(all|visible|hidden)$"),
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=50),
    ):
        condition = {
            "all": "",
            "visible": "AND COALESCE(m.is_hidden, FALSE) = FALSE",
            "hidden": "AND COALESCE(m.is_hidden, FALSE) = TRUE",
        }[status]

        with engine.connect() as conn:
            total = conn.execute(text(
                "SELECT COUNT(*) " + BASE + condition
            )).scalar_one()

            rows = conn.execute(text("""
                SELECT p.id, p.author_name, p.url AS facebook_url,
                       p.published_at, c.products, c.location,
                       COALESCE(m.is_hidden, FALSE) AS is_hidden,
                       m.reason AS moderation_reason,
                       m.updated_at AS moderation_updated_at
            """ + BASE + condition + """
                ORDER BY p.published_at DESC NULLS LAST, p.id DESC
                LIMIT :limit OFFSET :offset
            """), {
                "limit": limit,
                "offset": (page - 1) * limit,
            }).mappings().all()

            images = get_images(conn, [r["id"] for r in rows])

        items = []
        for row in rows:
            item = dict(row)
            gallery = images.get(row["id"], [])
            item["thumbnail_url"] = (
                gallery[0]["url"] if gallery else None
            )
            item["image_count"] = len(gallery)
            items.append(item)

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        }

    @router.post("/{post_id}/hide")
    def hide_product(post_id: int, data: HideRequest):
        with engine.begin() as conn:
            exists = conn.execute(text("""
                SELECT id FROM posts WHERE id = :id
                FOR UPDATE
            """), {"id": post_id}).scalar_one_or_none()

            if exists is None:
                raise HTTPException(404, "Post not found")

            conn.execute(text("""
                INSERT INTO post_moderation
                    (post_id, is_hidden, reason, updated_at)
                VALUES (:id, TRUE, :reason, NOW())
                ON CONFLICT (post_id) DO UPDATE
                SET is_hidden = TRUE,
                    reason = EXCLUDED.reason,
                    updated_at = NOW()
            """), {"id": post_id, "reason": data.reason})

            conn.execute(text("""
                INSERT INTO post_moderation_events
                    (post_id, action, reason)
                VALUES (:id, 'hide', :reason)
            """), {"id": post_id, "reason": data.reason})

        return {"post_id": post_id, "is_hidden": True}

    @router.post("/{post_id}/restore")
    def restore_product(post_id: int):
        with engine.begin() as conn:
            exists = conn.execute(text("""
                SELECT id FROM posts WHERE id = :id
                FOR UPDATE
            """), {"id": post_id}).scalar_one_or_none()

            if exists is None:
                raise HTTPException(404, "Post not found")

            conn.execute(text("""
                INSERT INTO post_moderation
                    (post_id, is_hidden, reason, updated_at)
                VALUES (:id, FALSE, NULL, NOW())
                ON CONFLICT (post_id) DO UPDATE
                SET is_hidden = FALSE,
                    reason = NULL,
                    updated_at = NOW()
            """), {"id": post_id})

            conn.execute(text("""
                INSERT INTO post_moderation_events
                    (post_id, action)
                VALUES (:id, 'restore')
            """), {"id": post_id})

        return {"post_id": post_id, "is_hidden": False}

    app.include_router(router)
