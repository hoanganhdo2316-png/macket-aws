import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text

router = APIRouter(
    prefix="/api/collector",
    tags=["Collector"]
)


def verify_collector(
    x_collector_token: str | None = Header(default=None)
):
    expected = os.getenv("COLLECTOR_CONFIG_TOKEN")

    if not expected:
        raise HTTPException(503, "Collector config unavailable")

    if not x_collector_token or not secrets.compare_digest(
        x_collector_token, expected
    ):
        raise HTTPException(401, "Unauthorized")


def register_collector_config_routes(app, engine):

    @router.get("/config", dependencies=[Depends(verify_collector)])
    def get_collector_config():

        with engine.connect() as conn:

            groups = conn.execute(text("""
                SELECT id, name, url, max_posts
                FROM facebook_groups
                WHERE enabled = TRUE
                ORDER BY id
            """)).mappings().all()

            settings = conn.execute(text("""
                SELECT max_posts_per_group,
                       only_new_posts,
                       max_total_charge_usd
                FROM crawler_settings
                WHERE id = 1
            """)).mappings().one()

            authors = conn.execute(text("""
                SELECT facebook_author_id, profile_url
                FROM author_skip_list
                WHERE skip_enabled = TRUE
                  AND (
                      facebook_author_id IS NOT NULL
                      OR profile_url IS NOT NULL
                  )
                ORDER BY id
            """)).mappings().all()

        exclude_authors = []

        for author in authors:
            identifier = (
                author["facebook_author_id"]
                or author["profile_url"]
            )
            if identifier and identifier not in exclude_authors:
                exclude_authors.append(identifier)

        return {
            "groups": [dict(group) for group in groups],
            "settings": {
                "max_posts_per_group": settings["max_posts_per_group"],
                "only_new_posts": settings["only_new_posts"],
                "max_total_charge_usd": str(
                    settings["max_total_charge_usd"]
                ),
            },
            "exclude_authors": exclude_authors,
        }

    app.include_router(router)
