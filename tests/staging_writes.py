"""Staging-only integration checks with real PostgreSQL and mocked external services."""

import json
import os
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from urllib.request import Request, urlopen

assert (os.environ.get("DB_HOST"), os.environ.get("DB_NAME"), os.environ.get("DB_USER")) == (
    "staging-db", "macket_staging", "staging",
), "Refusing to run writes outside the staging Compose project"
assert os.environ.get("AWS_EC2_METADATA_DISABLED") == "true"

from fastapi.testclient import TestClient
from sqlalchemy import text

import apify_run_ingestion as ingestion
import batch_classification_worker as batch_v1
import batch_execute_v2 as batch_v2
import classification_worker as v1
import classification_worker_v2 as v2
import extraction_recovery
import extraction_worker as extraction
import main
import media_worker as media
import scheduler_routes as scheduler
import stage1_claim_reset
from ai_schemas import Stage1Classification, Stage2Extraction


def one(sql, **params):
    with main.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def write(sql, **params):
    with main.engine.begin() as conn:
        return conn.execute(text(sql), params).rowcount


def checked(response, expected=200):
    assert response.status_code == expected, (response.request.url.path, response.status_code, response.text)
    return response.json()


def llm_result(parsed):
    usage = NS(prompt_tokens=20, completion_tokens=10, total_tokens=30, prompt_tokens_details=None)
    return NS(choices=[NS(message=NS(parsed=parsed, refusal=None))], usage=usage)


def item(number):
    return dict(postUrl=f"https://www.facebook.com/groups/stagingfixture/posts/{number}/", postId=str(number),
                groupName="Staging Fixture", text="Synthetic MacBook listing", authorId=str(number + 1000),
                authorName="Fixture Author", imageUrls=["https://fixture.fbcdn.net/image.png"])


def main_test():
    assert one("SELECT current_database()") == "macket_staging"
    assert one("SHOW transaction_read_only") == "off"
    assert one("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()") is True
    write("INSERT INTO crawler_settings(id) VALUES (1)")
    write("INSERT INTO scheduler_settings(id) VALUES (1)")
    write("INSERT INTO ai_prompt_versions(version, system_prompt) VALUES (6, 'Classify listings')")

    admin = {"X-Admin-Token": os.environ["ADMIN_API_TOKEN"]}
    hook = {"X-Webhook-Token": os.environ["APIFY_WEBHOOK_TOKEN"]}
    group = {"name": "Staging Fixture", "url": "https://www.facebook.com/groups/stagingfixture/"}
    req = Request("http://frontend/api/admin/groups", json.dumps(group).encode(),
                  {**admin, "Content-Type": "application/json"})
    with urlopen(req, timeout=8) as response:
        assert response.status == 201
        group_id = json.load(response)["id"]
    assert one("SELECT name FROM facebook_groups WHERE id=:id", id=group_id) == group["name"]

    with TestClient(main.app, headers=admin) as client:
        checked(client.patch(f"/api/admin/groups/{group_id}", json={"max_posts": 4}))
        temp = checked(client.post("/api/admin/groups", json={"name": "Temporary", "url": group["url"] + "tmp/"}), 201)
        checked(client.delete(f"/api/admin/groups/{temp['id']}"))
        author = checked(client.post("/api/admin/authors", json={"facebook_author_id": "fixture-author"}), 201)
        checked(client.patch(f"/api/admin/authors/{author['id']}", json={"classification": "seller", "skip_enabled": True}))
        checked(client.delete(f"/api/admin/authors/{author['id']}"))
        assert checked(client.patch("/api/admin/crawler-settings", json={"max_posts_per_group": 4}))["max_posts_per_group"] == 4
        for service in ("openai", "apify"):
            checked(client.put(f"/api/admin/credentials/{service}", json={"token": "staging-fake-credential"}))
        assert one("SELECT count(*) FROM api_credentials WHERE encrypted_token != 'staging-fake-credential'") == 2
        collector = {"X-Collector-Token": os.environ["COLLECTOR_CONFIG_TOKEN"]}
        assert checked(client.get("/api/collector/apify-token", headers=collector))["token"] == "staging-fake-credential"
        prompt = checked(client.post("/api/admin/ai-prompts", json={"system_prompt": "Classify the synthetic listings."}), 201)
        checked(client.post(f"/api/admin/ai-prompts/{prompt['id']}/activate"))
        assert one("SELECT version FROM ai_prompt_versions WHERE is_active") == 7
        schedule = dict(State="DISABLED", Target={}, FlexibleTimeWindow={"Mode": "OFF"}, ScheduleExpression="rate(60 minutes)")
        with patch.object(scheduler.client, "get_schedule", return_value=schedule), patch.object(scheduler.client, "update_schedule") as change:
            checked(client.patch("/api/admin/scheduler", json={"interval_minutes": 30}))
            assert change.call_args.kwargs["State"] == "DISABLED"
            checked(client.patch("/api/admin/scheduler", json={"enabled": True}), 409)
            assert change.call_count == 1
        assert one("SELECT interval_minutes FROM scheduler_settings WHERE id=1") == 30
        print("PASS admin write routes, encrypted credentials and Scheduler DB write with mock")

        def run(dataset, action):
            def apify(path):
                if path.startswith("actor-runs/"):
                    return dict(actId="dGw5RQgZjVug05E1h", status="SUCCEEDED", defaultDatasetId="fixture-dataset")
                return dict(itemCount=len(dataset))
            with patch.object(ingestion, "apify_get", side_effect=apify), patch.object(ingestion, "fetch_dataset", return_value=dataset):
                return action()

        def webhook(run_id, code=200):
            return checked(client.post("/api/webhooks/apify", headers=hook,
                           json={"eventType": "ACTOR.RUN.SUCCEEDED", "resource": {"id": run_id}}), code)

        assert run([item(101), item(102), item(103), item(104)], lambda: webhook("fixture-webhook"))["inserted_posts"] == 4
        assert webhook("fixture-webhook")["status"] == "ALREADY_INGESTED"
        run([item(999), {}], lambda: webhook("fixture-rollback", 409))
        assert one("SELECT count(*) FROM posts WHERE source_post_id='999'") == 0
        assert one("SELECT count(*) FROM crawl_runs WHERE apify_run_id='fixture-rollback'") == 0
        manual = lambda: checked(client.post("/api/admin/ingest-run", json={"run_id": "fixture-manual"}))
        assert run([item(101), item(105)], manual)["duplicate_posts"] == 1
        assert one("SELECT count(*) FROM posts") == 5
        print("PASS webhook and manual ingestion, deduplication and atomic rollback")

        def post(number):
            return one("SELECT id FROM posts WHERE source_post_id=:n", n=str(number))

        individual = dict(post_type="selling", seller_type="individual", confidence=.99, reason="Fixture")
        with patch.object(v2, "OpenAI") as model:
            model.return_value.chat.completions.parse.return_value = llm_result(Stage1Classification(**individual))
            classified = v2.classify_stage1(post(101), execute=True)
            assert v2.classify_stage1(post(101), execute=True)["status"] == "already_classified"
            model.return_value.chat.completions.parse.return_value = llm_result(Stage1Classification(**{**individual, "seller_type": "seller"}))
            assert v2.classify_stage1(post(102), execute=True)["status"] == "success"
            model.return_value.chat.completions.parse.side_effect = RuntimeError("fixture provider rejected request")
            try:
                v2.classify_stage1(post(103), execute=True)
            except RuntimeError as error:
                assert str(error) == "fixture provider rejected request"
        assert one("SELECT skip_enabled FROM author_skip_list WHERE facebook_author_id='1102'") is True
        failed = one("SELECT id FROM stage1_claims WHERE status='failed'")
        assert stage1_claim_reset.recover_claim(failed, execute=True, worker_stopped=True)["status"] == "recovered"
        assert one("SELECT count(*) FROM stage1_claim_recovery_audit") == 1

        ext = Stage2Extraction(products=[dict(category="Laptop", brand="Apple", model="Fixture", specifications=[],
                               price_vnd=1000, condition="used")], location="Fixture")
        classification_id = classified["classification_id"]
        with patch.object(extraction, "OpenAI") as model:
            model.return_value.chat.completions.parse.return_value = llm_result(ext)
            assert extraction.extract_products(classification_id, execute=True)["status"] == "completed"
        assert one("SELECT status FROM post_extraction_logs WHERE classification_id=:id", id=classification_id) == "completed"
        with patch.object(media, "download_image", return_value=(b"synthetic image", "png", "image/png")), patch.object(media.s3, "put_object") as upload:
            assert media.process_post(post(101), execute=True)["uploaded"] == 1
            assert media.process_post(post(101), execute=True)["skipped"] == 1
            upload.assert_called_once()
        assert one("SELECT count(*) FROM post_images WHERE post_id=:id", id=post(101)) == 1

        product = f"/api/admin/products/{post(101)}"
        checked(client.post(product + "/hide", json={"reason": "Fixture moderation"}))
        checked(client.get(f"/api/products/{post(101)}"), 404)
        checked(client.post(product + "/restore"))
        assert one("SELECT count(*) FROM post_moderation_events") == 2

        with patch.object(v1, "OpenAI") as model:
            model.return_value.chat.completions.parse.return_value = llm_result(v1.Classification(**individual, **ext.model_dump()))
            v1.classify_post(post(104), execute=True)
        legacy = one("SELECT id FROM post_classifications WHERE post_id=:id", id=post(104))
        write("UPDATE post_classifications SET extraction_status='processing', extraction_started_at=now()-interval '11 minutes' WHERE id=:id", id=legacy)
        assert extraction_recovery.recover_extraction(legacy, execute=True)["status"] == "recovered"
        print("PASS v1/v2 classification writes, seller block, claim recovery, extraction, media and moderation")

        with patch.object(extraction, "OpenAI") as model:
            model.return_value.chat.completions.parse.side_effect = RuntimeError("fixture extraction failure")
            try:
                extraction.extract_products(legacy, execute=True)
            except RuntimeError as error:
                assert str(error) == "fixture extraction failure"
            else:
                raise AssertionError("Expected the synthetic extraction failure")
        assert one("SELECT extraction_status FROM post_classifications WHERE id=:id", id=legacy) == "failed"
        assert one("SELECT status FROM post_extraction_logs WHERE classification_id=:id", id=legacy) == "failed"
        with patch.object(batch_v1, "estimate_cost", return_value=Decimal("0.001")), patch.object(v1, "OpenAI") as model:
            model.return_value.chat.completions.parse.return_value = llm_result(v1.Classification(**individual, **ext.model_dump()))
            with main.engine.connect() as conn:
                batch_v1.run_batch(conn, main.engine, NS(limit=1, budget="0.01", execute=True))
            model.return_value.chat.completions.parse.assert_called_once()
        assert one("SELECT count(*) FROM post_classifications WHERE post_id=:id", id=post(103)) == 1
        with patch.object(batch_v2, "estimate_cost", return_value=Decimal("0.001")), patch.object(extraction, "OpenAI") as model:
            model.return_value.chat.completions.parse.return_value = llm_result(ext)
            batch_v2.execute_batch(1, Decimal("0.01"))
            model.return_value.chat.completions.parse.assert_called_once()
        assert one("SELECT extraction_status FROM post_classifications WHERE id=:id", id=legacy) == "completed"
        print("PASS failed extraction audit and v1/v2 batch writes with mocked providers/token estimate")


if __name__ == "__main__":
    main_test()
