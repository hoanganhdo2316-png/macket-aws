import json
from contextlib import nullcontext
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import text

SOURCE = "facebook"
POST_PATTERN = re.compile(r"^/groups/([^/]+)/posts/(\d+)/?$")


def parse_post_url(url):
    parsed = urlparse(url or "")

    if parsed.hostname not in (
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
    ):
        raise ValueError("Invalid Facebook hostname")

    match = POST_PATTERN.fullmatch(parsed.path)

    if not match:
        raise ValueError(f"Invalid Facebook post URL: {url}")

    return match.group(1), match.group(2)


def parse_date(value):
    if not value:
        return None

    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        raise ValueError("Post date must include timezone")

    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def ingest_items(engine, items, conn=None):
    if not isinstance(items, list):
        raise ValueError("Dataset must be a list")

    inserted = 0
    duplicates = 0

    transaction = engine.begin() if conn is None else nullcontext(conn)

    with transaction as conn:
        groups = conn.execute(text("""
            SELECT id, name, url
            FROM facebook_groups
        """)).mappings().all()

        group_by_name = {
            group["name"]: group for group in groups
        }

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Invalid item at index {index}")

            url = item.get("postUrl")
            group_name = item.get("groupName")

            if not url or not group_name:
                raise ValueError(f"Missing URL/group at index {index}")

            url_group, url_post_id = parse_post_url(url)

            post_id = str(item.get("postId") or url_post_id)

            if post_id != url_post_id:
                raise ValueError(
                    f"Post ID mismatch at index {index}"
                )

            group = group_by_name.get(group_name)

            if group is None:
                raise ValueError(
                    f"Unknown Facebook group: {group_name}"
                )

            configured_path = (
                urlparse(group["url"]).path.strip("/").split("/")
            )

            if (
                len(configured_path) < 2
                or configured_path[0] != "groups"
                or configured_path[1].lower() != url_group.lower()
            ):
                raise ValueError(
                    f"Group URL mismatch at index {index}"
                )

            image_urls = item.get("imageUrls")
            listing = item.get("listing")

            if image_urls is not None and not isinstance(image_urls, list):
                raise ValueError(f"Invalid imageUrls at index {index}")

            if listing is not None and not isinstance(listing, dict):
                raise ValueError(f"Invalid listing at index {index}")

            result = conn.execute(text("""
                INSERT INTO posts (
                    source,
                    source_post_id,
                    url,
                    content,
                    published_at,
                    collected_at,
                    facebook_group_id,
                    facebook_group_external_id,
                    author_name,
                    author_id,
                    author_url,
                    reaction_count,
                    comment_count,
                    share_count,
                    image_urls,
                    listing,
                    raw_data
                )
                VALUES (
                    :source,
                    :post_id,
                    :url,
                    :content,
                    :published_at,
                    NOW(),
                    :group_id,
                    :group_external_id,
                    :author_name,
                    :author_id,
                    :author_url,
                    :reactions,
                    :comments,
                    :shares,
                    CAST(:image_urls AS JSONB),
                    CAST(:listing AS JSONB),
                    CAST(:raw_data AS JSONB)
                )
                ON CONFLICT (source, source_post_id)
                DO NOTHING
                RETURNING id
            """), {
                "source": SOURCE,
                "post_id": post_id,
                "url": url,
                "content": item.get("text"),
                "published_at": parse_date(item.get("date")),
                "group_id": group["id"],
                "group_external_id": (
                    str(item["groupId"])
                    if item.get("groupId") is not None
                    else None
                ),
                "author_name": item.get("authorName"),
                "author_id": (
                    str(item["authorId"])
                    if item.get("authorId") is not None
                    else None
                ),
                "author_url": item.get("authorUrl"),
                "reactions": item.get("reactionCount"),
                "comments": item.get("commentCount"),
                "shares": item.get("shareCount"),
                "image_urls": json.dumps(
                    image_urls, ensure_ascii=False
                ) if image_urls is not None else None,
                "listing": json.dumps(
                    listing, ensure_ascii=False
                ) if listing is not None else None,
                "raw_data": json.dumps(
                    item, ensure_ascii=False
                ),
            }).scalar_one_or_none()

            if result is None:
                duplicates += 1
            else:
                inserted += 1

    return {
        "total_posts": len(items),
        "inserted_posts": inserted,
        "duplicate_posts": duplicates,
    }
