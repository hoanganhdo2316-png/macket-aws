import os

import boto3
from fastapi import HTTPException, Query, Response
from sqlalchemy import text
from botocore.exceptions import ClientError, BotoCoreError

BUCKET = os.getenv(
    "MACKET_MEDIA_BUCKET",
    "macket-storage-393840684011-ap-southeast-1-an"
)
s3 = boto3.client("s3", region_name="ap-southeast-1")

BASE_QUERY = """
    FROM posts p
    JOIN LATERAL (
        SELECT c.*
        FROM post_classifications c
        WHERE c.post_id = p.id
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    ) c ON TRUE
    WHERE p.source = 'facebook'
      AND c.post_type = 'selling'
      AND c.seller_type = 'individual'
      AND c.extraction_status = 'completed'
      AND jsonb_typeof(c.products) = 'array'
      AND jsonb_array_length(c.products) > 0
      AND NOT EXISTS (
          SELECT 1 FROM post_moderation m
          WHERE m.post_id = p.id AND m.is_hidden = TRUE
      )
"""


def signed_image_url(key):
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": key},
            ExpiresIn=900,
        )
    except (ClientError, BotoCoreError):
        raise HTTPException(
            status_code=503,
            detail="Image service unavailable"
        )


def get_images(conn, post_ids):
    if not post_ids:
        return {}

    rows = conn.execute(text("""
        SELECT post_id, image_index, s3_key
        FROM post_images
        WHERE post_id = ANY(:post_ids)
        ORDER BY post_id, image_index
    """), {"post_ids": post_ids}).mappings().all()

    images = {post_id: [] for post_id in post_ids}

    for row in rows:
        images[row["post_id"]].append({
            "image_index": row["image_index"],
            "url": signed_image_url(row["s3_key"]),
        })

    return images


def serialize_post(row, images):
    return {
        "id": row["id"],
        "author_name": row["author_name"],
        "facebook_url": row["url"],
        "content": row["content"],
        "published_at": row["published_at"],
        "location": row["location"],
        "products": row["products"],
        "image_count": len(images),
        "thumbnail_url": images[0]["url"] if images else None,
        "images": images,
    }


def register_client_routes(app, engine):

    @app.get("/api/products")
    def list_products(
        response: Response,
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=50),
    ):
        response.headers["Cache-Control"] = "no-store"
        offset = (page - 1) * limit

        with engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) " + BASE_QUERY)
            ).scalar_one()

            rows = conn.execute(text("""
                SELECT p.id, p.author_name, p.url,
                       p.content, p.published_at,
                       c.location, c.products
            """ + BASE_QUERY + """
                ORDER BY p.published_at DESC NULLS LAST, p.id DESC
                LIMIT :limit OFFSET :offset
            """), {
                "limit": limit,
                "offset": offset,
            }).mappings().all()

            ids = [row["id"] for row in rows]
            images = get_images(conn, ids)

        return {
            "page": page,
            "limit": limit,
            "total": total,
            "items": [
                serialize_post(row, images.get(row["id"], []))
                for row in rows
            ],
        }

    @app.get("/api/products/{post_id}")
    def product_detail(post_id: int, response: Response):
        response.headers["Cache-Control"] = "no-store"

        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT p.id, p.author_name, p.url,
                       p.content, p.published_at,
                       c.location, c.products
            """ + BASE_QUERY + """
                AND p.id = :post_id
            """), {"post_id": post_id}).mappings().first()

            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail="Product not found"
                )

            images = get_images(conn, [post_id])

        return serialize_post(row, images.get(post_id, []))
