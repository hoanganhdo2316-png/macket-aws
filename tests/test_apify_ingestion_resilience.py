import os
import unittest

from sqlalchemy import text


if (
    os.getenv("DB_HOST") != "staging-db"
    or os.getenv("DB_NAME") != "macket_staging"
    or os.getenv("AWS_EC2_METADATA_DISABLED") != "true"
):
    raise unittest.SkipTest("Ingestion integration requires the isolated staging project")

from apify_ingestion import ingest_items
from main import engine


def item(post_id, *, group_name, group_id, group_key):
    return {
        "postUrl": f"https://www.facebook.com/groups/{group_key}/posts/{post_id}/",
        "postId": str(post_id),
        "groupName": group_name,
        "groupId": group_id,
        "date": "2026-11-26T00:00:00Z",
        "text": "Synthetic listing",
    }


class IngestionResilienceTests(unittest.TestCase):
    def setUp(self):
        with engine.begin() as conn:
            self.group_id = conn.execute(text("""
                INSERT INTO facebook_groups(name, url)
                VALUES ('Resilience group', 'https://www.facebook.com/groups/configured-slug/')
                RETURNING id
            """)).scalar_one()

    def test_group_id_is_learned_and_invalid_item_is_skipped(self):
        result = ingest_items(engine, [
            item(800101, group_name="Resilience group", group_id="group-42", group_key="changed-url"),
            item(800102, group_name="Unknown group", group_id="unknown-9", group_key="unknown-url"),
            item(800103, group_name="Renamed group", group_id="group-42", group_key="another-url"),
        ])
        self.assertEqual(result, {
            "total_posts": 3, "inserted_posts": 2, "duplicate_posts": 0, "skipped_posts": 1,
        })
        with engine.connect() as conn:
            self.assertEqual(conn.execute(text("""
                SELECT facebook_group_external_id FROM facebook_groups WHERE id = :id
            """), {"id": self.group_id}).scalar_one(), "group-42")
            self.assertEqual(conn.execute(text("""
                SELECT count(*) FROM posts WHERE source_post_id IN ('800101', '800103')
            """)).scalar_one(), 2)


if __name__ == "__main__":
    unittest.main()
