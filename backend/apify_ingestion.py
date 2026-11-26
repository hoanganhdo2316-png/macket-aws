import json
import logging
from contextlib import nullcontext
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import text

SOURCE = "facebook"
POST_PATTERN = re.compile(r"^/groups/([^/]+)/posts/(\d+)/?$")
GROUP_PATTERN = re.compile(r"^/groups/([^/]+)/?$")
LOG = logging.getLogger(__name__)


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


def configured_group_key(url):
    parsed = urlparse(url or "")
    if parsed.hostname not in ("facebook.com", "www.facebook.com", "m.facebook.com"):
        raise ValueError("Invalid configured Facebook group URL")
    match = GROUP_PATTERN.fullmatch(parsed.path)
    if not match:
        raise ValueError("Invalid configured Facebook group URL")
    return match.group(1).lower()


def resolve_group(item, groups_by_external_id, groups_by_name, groups_by_key):
    external_id = item.get("groupId")
    external_id = str(external_id) if external_id is not None else None
    if external_id and external_id in groups_by_external_id:
        return groups_by_external_id[external_id], external_id

    group = groups_by_name.get(item.get("groupName"))
    if group is None:
        url_group, _ = parse_post_url(item.get("postUrl"))
        group = groups_by_key.get(url_group.lower())
    if group is None:
        raise ValueError("Unknown Facebook group")
    if group["facebook_group_external_id"] not in (None, external_id):
        raise ValueError("Facebook group ID does not match configured group")
    return group, external_id


def ingest_items(engine, items, conn=None):
    if not isinstance(items, list):
        raise ValueError("Dataset must be a list")

    inserted = 0
    duplicates = 0

    transaction = engine.begin() if conn is None else nullcontext(conn)

    with transaction as conn:
        groups = [dict(row) for row in conn.execute(text("""
            SELECT id, name, url, facebook_group_external_id
            FROM facebook_groups
        """)).mappings().all()]

        group_by_external_id = {
            group["facebook_group_external_id"]: group
            for group in groups if group["facebook_group_external_id"]
        }
        group_by_name = {group["name"]: group for group in groups}
        group_by_key = {configured_group_key(group["url"]): group for group in groups}
        skipped = 0

        for index, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    raise ValueError("Invalid item")
                url = item.get("postUrl")
                if not url or not item.get("groupName"):
                    raise ValueError("Missing URL/group")
                _, url_post_id = parse_post_url(url)
                post_id = str(item.get("postId") or url_post_id)
                if post_id != url_post_id:
                    raise ValueError("Post ID mismatch")
                group, external_id = resolve_group(
                    item, group_by_external_id, group_by_name, group_by_key,
                )
                image_urls = item.get("imageUrls")
                listing = item.get("listing")
                if image_urls is not None and not isinstance(image_urls, list):
                    raise ValueError("Invalid imageUrls")
                if listing is not None and not isinstance(listing, dict):
                    raise ValueError("Invalid listing")
                published_at = parse_date(item.get("date"))
            except (AttributeError, TypeError, ValueError) as exc:
                skipped += 1
                LOG.warning("Skipping Apify item index=%d reason=%s", index, exc)
                continue

            if external_id and group["facebook_group_external_id"] is None:
                conn.execute(text("""
                    UPDATE facebook_groups
                    SET facebook_group_external_id = :external_id, updated_at = NOW()
                    WHERE id = :group_id AND facebook_group_external_id IS NULL
                """), {"external_id": external_id, "group_id": group["id"]})
                group["facebook_group_external_id"] = external_id
                group_by_external_id[external_id] = group

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
                "published_at": published_at,
                "group_id": group["id"],
                "group_external_id": (
                    external_id
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
        "skipped_posts": skipped,
    }
