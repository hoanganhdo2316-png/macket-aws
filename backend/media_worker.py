import argparse
import io
import socket
from urllib.parse import urlparse

import boto3
import requests
from PIL import Image, UnidentifiedImageError
from sqlalchemy import text

from main import engine

BUCKET = "macket-storage-393840684011-ap-southeast-1-an"
REGION = "ap-southeast-1"
MAX_IMAGES = 20
MAX_IMAGE_BYTES = 10 * 1024 * 1024

s3 = boto3.client("s3", region_name=REGION)


def valid_facebook_image_url(url):
    if not isinstance(url, str):
        return False

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and (
            host == "fbcdn.net"
            or host.endswith(".fbcdn.net")
        )
    )


def load_post(post_id):
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT
                p.id,
                p.author_name,
                p.raw_data,
                EXISTS (
                    SELECT 1
                    FROM post_classifications c
                    WHERE c.post_id = p.id
                      AND c.post_type = 'selling'
                      AND c.seller_type = 'individual'
                      AND c.extraction_status = 'completed'
                ) AS eligible
            FROM posts p
            WHERE p.id = :post_id
              AND p.source = 'facebook'
        """), {"post_id": post_id}).mappings().first()


def download_image(url):
    if not valid_facebook_image_url(url):
        raise ValueError("INVALID FACEBOOK IMAGE URL")

    with requests.get(
        url,
        timeout=(10, 30),
        stream=True,
        allow_redirects=False,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as response:
        response.raise_for_status()

        if response.is_redirect:
            raise ValueError("IMAGE REDIRECT NOT ALLOWED")

        content = bytearray()

        for chunk in response.iter_content(65536):
            content.extend(chunk)

            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError("IMAGE TOO LARGE")

    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()

        with Image.open(io.BytesIO(content)) as img:
            fmt = img.format
            width, height = img.size

        if width * height > 40_000_000:
            raise ValueError("IMAGE DIMENSIONS TOO LARGE")

    except UnidentifiedImageError:
        raise ValueError("INVALID IMAGE DATA")

    formats = {
        "JPEG": ("jpg", "image/jpeg"),
        "PNG": ("png", "image/png"),
        "WEBP": ("webp", "image/webp"),
    }

    if fmt not in formats:
        raise ValueError(f"UNSUPPORTED IMAGE FORMAT: {fmt}")

    extension, content_type = formats[fmt]

    return bytes(content), extension, content_type


def process_post(post_id, execute=False):
    post = load_post(post_id)

    if not post:
        return {"status": "post_not_found"}

    if not post["eligible"]:
        return {"status": "not_eligible"}

    raw = post["raw_data"] or {}
    urls = raw.get("imageUrls", [])

    if not isinstance(urls, list):
        urls = []

    urls = urls[:MAX_IMAGES]

    print("=== MACKET MEDIA WORKER ===")
    print("POST ID:", post_id)
    print("AUTHOR:", post["author_name"])
    print("IMAGE COUNT:", len(urls))
    print("MODE:", "EXECUTE" if execute else "DRY RUN")

    if not execute:
        for i, url in enumerate(urls):
            print(
                f"IMAGE {i}:",
                "VALID URL" if valid_facebook_image_url(url)
                else "INVALID URL"
            )

        print("OPENAI REQUESTS: 0")
        print("S3 UPLOADS: 0")
        print("DATABASE WRITES: 0")
        return {"status": "dry_run", "images": len(urls)}

    uploaded = 0
    skipped = 0
    failed = 0

    for index, url in enumerate(urls):
        try:
            with engine.connect() as conn:
                exists = conn.execute(text("""
                    SELECT id FROM post_images
                    WHERE post_id = :post_id
                      AND image_index = :image_index
                """), {
                    "post_id": post_id,
                    "image_index": index,
                }).scalar_one_or_none()

            if exists:
                skipped += 1
                continue

            image, extension, content_type = download_image(url)

            key = f"posts/{post_id}/{index}.{extension}"

            s3.put_object(
                Bucket=BUCKET,
                Key=key,
                Body=image,
                ContentType=content_type,
            )

            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO post_images (
                        post_id,
                        image_index,
                        s3_key,
                        content_type,
                        size_bytes
                    )
                    VALUES (
                        :post_id,
                        :image_index,
                        :s3_key,
                        :content_type,
                        :size_bytes
                    )
                    ON CONFLICT (post_id, image_index)
                    DO NOTHING
                """), {
                    "post_id": post_id,
                    "image_index": index,
                    "s3_key": key,
                    "content_type": content_type,
                    "size_bytes": len(image),
                })

            uploaded += 1
            print(f"UPLOADED: {key} ({len(image)} bytes)")

        except Exception as exc:
            failed += 1
            print(
                f"IMAGE {index} FAILED:",
                type(exc).__name__,
                str(exc)[:150],
            )

    result = {
        "status": "completed" if failed == 0 else "partial",
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
    }

    print("MEDIA SUMMARY:", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    process_post(args.post_id, args.execute)
