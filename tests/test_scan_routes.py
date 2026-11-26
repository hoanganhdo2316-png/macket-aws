import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, ReadTimeoutError
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text


if (
    os.getenv("DB_HOST") != "staging-db"
    or os.getenv("DB_NAME") != "macket_staging"
    or os.getenv("AWS_EC2_METADATA_DISABLED") != "true"
):
    raise unittest.SkipTest("Scan integration requires the isolated staging project")

import apify_run_ingestion
import apify_webhook_routes
import scan_routes
from main import app, engine


ADMIN = {"X-Admin-Token": os.environ["ADMIN_API_TOKEN"]}
COLLECTOR = {"X-Collector-Token": os.environ["COLLECTOR_CONFIG_TOKEN"]}
WEBHOOK = {"X-Webhook-Token": os.environ["APIFY_WEBHOOK_TOKEN"]}
RUN_ID = "fixture-scan-run"


class ScanRoutesTests(unittest.TestCase):
    def setUp(self):
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE collector_scan
                SET revision = 0, scan_id = NULL, source = NULL, state = 'IDLE',
                    apify_run_id = NULL, updated_at = now()
                WHERE id = 1
            """))
            conn.execute(text("DELETE FROM crawl_runs WHERE apify_run_id = :run_id"), {"run_id": RUN_ID})
            key = os.environ["CREDENTIALS_ENCRYPTION_KEY"].encode()
            token = Fernet(key).encrypt(b"isolated-apify-token").decode()
            conn.execute(text("""
                INSERT INTO api_credentials(service, encrypted_token) VALUES ('apify', :token)
                ON CONFLICT (service) DO UPDATE SET encrypted_token = EXCLUDED.encrypted_token
            """), {"token": token})
        config = patch.dict(os.environ, {"MACKET_MANUAL_SCAN_ENABLED": "true"})
        config.start()
        self.addCleanup(config.stop)
        self.lambda_mock = Mock()
        self.lambda_mock.invoke.return_value = {"StatusCode": 202}
        client_patch = patch.object(scan_routes, "lambda_client", return_value=self.lambda_mock)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def status(self):
        response = self.client.get("/api/scan/status", headers=ADMIN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    def claim(self, scan_id=None):
        response = self.client.post("/api/collector/scan/claim", json={"scan_id": scan_id}, headers=COLLECTOR)
        self.assertEqual(response.status_code, 200)
        return response.json()["scan_id"]

    def report(self, scan_id, state, run_id=None):
        return self.client.post("/api/collector/scan/report", headers=COLLECTOR, json={
            "scan_id": scan_id, "state": state, "run_id": run_id,
        })

    def test_admin_and_collector_auth_and_explicit_enable_switch(self):
        self.assertEqual(self.client.post("/api/scan/trigger").status_code, 401)
        self.assertEqual(self.client.get("/api/scan/status").status_code, 401)
        self.assertEqual(self.client.post("/api/collector/scan/claim", json={}, headers=ADMIN).status_code, 401)
        self.assertEqual(self.client.post("/api/collector/scan/report", json={}, headers=ADMIN).status_code, 401)
        credentials = self.client.get("/api/collector/apify-token", headers=COLLECTOR)
        self.assertEqual(credentials.status_code, 200)
        self.assertEqual(credentials.json(), {"token": "isolated-apify-token"})
        self.assertEqual(credentials.headers["cache-control"], "no-store")
        with patch.dict(os.environ, {"MACKET_MANUAL_SCAN_ENABLED": "false"}):
            self.assertFalse(self.status()["can_trigger"])
            self.assertEqual(self.client.post("/api/scan/trigger", headers=ADMIN).status_code, 503)
        self.lambda_mock.invoke.assert_not_called()

    def test_manual_scan_can_only_be_claimed_once_and_status_tracks_webhook(self):
        response = self.client.post("/api/scan/trigger", headers=ADMIN)
        self.assertEqual(response.status_code, 202)
        scan_id = response.json()["scan_id"]
        self.lambda_mock.invoke.assert_called_once()
        invoke = self.lambda_mock.invoke.call_args.kwargs
        self.assertEqual(invoke["FunctionName"], "macket-apify-trigger")
        self.assertEqual(invoke["InvocationType"], "Event")
        self.assertEqual(json.loads(invoke["Payload"]), {"scan_id": scan_id})
        self.assertEqual(self.status()["status"], "QUEUED")
        self.assertEqual(self.client.post("/api/scan/trigger", headers=ADMIN).status_code, 409)
        self.assertIsNone(self.claim())
        self.assertEqual(self.claim(scan_id), scan_id)
        self.assertIsNone(self.claim(scan_id))
        self.assertIsNone(self.claim())
        self.assertEqual(self.status()["status"], "STARTING")
        for _ in range(2):
            self.assertEqual(self.report(scan_id, "RUNNING", RUN_ID).status_code, 204)

        with patch.object(scan_routes, "apify_get") as api:
            api.return_value = {"actId": scan_routes.ACTOR_ID, "status": "RUNNING"}
            status = self.status()
            self.assertFalse(status["can_trigger"])
            self.assertEqual(status["status"], "RUNNING")
            api.assert_called_once_with(f"actor-runs/{RUN_ID}", token="isolated-apify-token", timeout=8)
            api.side_effect = TimeoutError
            self.assertEqual(self.status()["status"], "STATUS_UNAVAILABLE")
            self.assertIsNone(self.claim())
            api.side_effect = None
            api.return_value["status"] = "SUCCEEDED"
            self.assertEqual(self.status()["status"], "AWAITING_INGESTION")

        run = {"actId": scan_routes.ACTOR_ID, "status": "SUCCEEDED", "defaultDatasetId": "fixture-dataset"}
        with (
            patch.object(apify_run_ingestion, "apify_get", side_effect=[run, {"itemCount": 0}]),
            patch.object(apify_run_ingestion, "fetch_dataset", return_value=[]),
        ):
            response = self.client.post("/api/webhooks/apify", headers=WEBHOOK, json={
                "eventType": "ACTOR.RUN.SUCCEEDED", "resource": {"id": RUN_ID},
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.status()["status"], "INGESTED")
        self.assertTrue(self.status()["can_trigger"])

    def test_manual_and_scheduler_contention_reserves_only_one_scan(self):
        simultaneous = Barrier(8)

        def request(i):
            simultaneous.wait()
            with TestClient(app) as client:
                if i % 2:
                    return client.post("/api/scan/trigger", headers=ADMIN).status_code == 202
                return client.post("/api/collector/scan/claim", headers=COLLECTOR, json={}).json()["scan_id"] is not None

        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(request, range(8)))
        self.assertEqual(sum(claimed), 1)
        self.assertLessEqual(self.lambda_mock.invoke.call_count, 1)

    def test_lambda_rejection_and_timeout_do_not_allow_delayed_duplicate(self):
        self.lambda_mock.invoke.side_effect = ClientError({
            "Error": {"Code": "AccessDeniedException"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }, "Invoke")
        self.assertEqual(self.client.post("/api/scan/trigger", headers=ADMIN).status_code, 502)
        self.assertEqual(self.status()["status"], "FAILED")

        self.lambda_mock.invoke.side_effect = ReadTimeoutError(endpoint_url="https://example.invalid")
        self.assertEqual(self.client.post("/api/scan/trigger", headers=ADMIN).status_code, 502)
        scan_id = self.status()["scan_id"]
        self.assertEqual(self.status()["status"], "QUEUED")
        self.assertIsNone(self.claim())
        with engine.begin() as conn:
            conn.execute(text("UPDATE collector_scan SET updated_at = now() - interval '6 minutes' WHERE id = 1"))
        self.assertEqual(self.status()["status"], "EXPIRED")
        self.assertIsNone(self.claim(scan_id))
        self.assertIsNotNone(self.claim())

    def test_uncertain_paid_start_keeps_both_paths_locked(self):
        scan_id = self.claim()
        self.assertIsNotNone(scan_id)
        self.assertEqual(self.report(scan_id, "UNKNOWN").status_code, 204)
        self.assertEqual(self.status()["status"], "UNKNOWN")
        self.assertIsNone(self.claim())
        self.assertEqual(self.client.post("/api/scan/trigger", headers=ADMIN).status_code, 409)
        self.lambda_mock.invoke.assert_not_called()

    def test_failed_ingestion_marks_only_the_matching_scan_failed(self):
        scan_id = self.claim()
        self.assertEqual(self.report(scan_id, "RUNNING", RUN_ID).status_code, 204)
        with patch.object(apify_webhook_routes, "ingest_run", return_value={
            "run_id": RUN_ID, "status": "FAILED", "total_posts": 2,
            "inserted_posts": 0, "duplicate_posts": 0, "skipped_posts": 2,
        }):
            response = self.client.post("/api/webhooks/apify", headers=WEBHOOK, json={
                "eventType": "ACTOR.RUN.SUCCEEDED", "resource": {"id": RUN_ID},
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.status()["status"], "FAILED")

        with patch.object(apify_webhook_routes, "ingest_run", return_value={
            "run_id": RUN_ID, "status": "ALREADY_FAILED", "total_posts": 2,
            "inserted_posts": 0, "duplicate_posts": 0, "skipped_posts": 2,
        }):
            self.assertEqual(self.client.post("/api/webhooks/apify", headers=WEBHOOK, json={
                "eventType": "ACTOR.RUN.SUCCEEDED", "resource": {"id": RUN_ID},
            }).status_code, 200)
        self.assertEqual(self.status()["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
