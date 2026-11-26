import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import lambda_trigger


CONFIG = {
    "groups": [{"url": "https://www.facebook.com/groups/fixture"}],
    "settings": {
        "max_posts_per_group": 3,
        "only_new_posts": True,
        "max_total_charge_usd": "0.30",
    },
    "exclude_authors": [],
}


class LambdaScanTests(unittest.TestCase):
    def setUp(self):
        self.actor = Mock()
        self.actor.runs.return_value.list.return_value = SimpleNamespace(items=[])
        self.actor.start.return_value = {"id": "fixture-run", "status": "RUNNING"}
        self.reports = []
        self.claim_id = "fixture-scan"
        self.request = Mock(side_effect=self.collector_request)
        request_patch = patch.object(lambda_trigger, "collector_request", self.request)
        client_patch = patch.object(lambda_trigger, "ApifyClient")
        request_patch.start()
        self.addCleanup(request_patch.stop)
        self.client = client_patch.start()
        self.addCleanup(client_patch.stop)
        self.client.return_value.actor.return_value = self.actor

    def collector_request(self, path, data=None):
        match path:
            case "/config":
                return CONFIG
            case "/scan/claim":
                return {"scan_id": self.claim_id}
            case "/apify-token":
                return {"token": "fixture"}
            case "/scan/report":
                self.reports.append(data)
            case _:
                raise AssertionError(path)

    def test_manual_and_scheduler_use_the_same_gate(self):
        for event, expected_id in [({"scan_id": "manual-id"}, "manual-id"), ({}, None)]:
            with self.subTest(event=event):
                self.request.reset_mock()
                self.actor.start.reset_mock()
                result = lambda_trigger.lambda_handler(event, None)
                self.assertEqual(result["status"], "RUNNING")
                self.assertEqual(self.request.call_args_list[0], call("/scan/claim", {"scan_id": expected_id}))
                self.actor.start.assert_called_once()
                self.assertEqual(self.actor.start.call_args.kwargs["max_items"], 3)
                self.assertEqual(self.actor.start.call_args.kwargs["max_total_charge_usd"], Decimal("0.30"))
                self.client.assert_called_with("fixture", max_retries=0, timeout_secs=15)
                self.assertEqual(self.reports[-1], {"scan_id": self.claim_id, "state": "RUNNING", "run_id": "fixture-run"})

    def test_busy_or_existing_apify_run_never_starts_actor(self):
        self.claim_id = None
        self.assertEqual(lambda_trigger.lambda_handler({}, None)["status"], "SKIPPED")
        self.client.assert_not_called()
        self.claim_id = "fixture-scan"
        self.actor.runs.return_value.list.return_value.items = [{"id": "already-active"}]
        result = lambda_trigger.lambda_handler({}, None)
        self.assertEqual(result["reason"], "existing_apify_run")
        self.assertEqual(self.reports[-1]["run_id"], "already-active")
        self.actor.runs.return_value.list.assert_called_once_with(
            status=["READY", "RUNNING", "TIMING-OUT", "ABORTING"], limit=1, desc=True,
        )
        self.actor.start.assert_not_called()

    def test_uncertain_start_is_reported_once_without_resubmitting(self):
        self.actor.start.side_effect = TimeoutError
        result = lambda_trigger.lambda_handler({}, None)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(self.reports, [{"scan_id": self.claim_id, "state": "UNKNOWN", "run_id": None}])
        self.actor.start.assert_called_once()

    def test_dry_run_reads_config_without_claim_or_apify(self):
        result = lambda_trigger.lambda_handler({"dry_run": True}, None)
        self.assertEqual(result["status"], "DRY_RUN")
        self.request.assert_called_once_with("/config")
        self.client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
