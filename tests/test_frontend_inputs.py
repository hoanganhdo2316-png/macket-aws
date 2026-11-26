"""Regression tests for the automatic Frontend release selection."""

from contextlib import chdir
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci import frontend_inputs


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def commit(path, contents):
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(contents, encoding="utf-8")
    git("add", "--", path)
    git("-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture", "commit", "-qm", path)
    return git("rev-parse", "HEAD")


class FrontendInputsTests(unittest.TestCase):
    def test_docs_and_backend_changes_preserve_frontend_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            git("init", "-q")
            base = commit("frontend/index.html", "v1")
            commit("README.md", "documentation")
            head = commit("backend/main.py", "backend")
            self.assertEqual(frontend_inputs.plan(head, base), (frontend_inputs.fingerprint(base), False))

            candidate = commit("frontend/index.html", "v2")
            key, changed = frontend_inputs.plan(candidate, base)
            self.assertTrue(changed)
            self.assertEqual(frontend_inputs.plan(commit("README.md", "next"), candidate), (key, False))
            smoke = commit("ci/frontend-smoke.sh", "updated check")
            self.assertNotEqual(frontend_inputs.fingerprint(smoke), key)

    def test_failed_and_pending_deployments_do_not_advance_base(self):
        deployments = [{"id": 3, "sha": "new"}, {"id": 2, "sha": "healthy"}, {"id": 1, "sha": "old"}]
        statuses = {
            3: [{"state": "failure"}, {"state": "in_progress"}],
            2: [{"state": "inactive"}, {"state": "success"}],
            1: [{"state": "success"}],
        }
        self.assertEqual(
            frontend_inputs.last_healthy_deployment(deployments, statuses.__getitem__, "bootstrap"), "healthy"
        )
        self.assertEqual(
            frontend_inputs.last_healthy_deployment(deployments[:1], statuses.__getitem__, "bootstrap"), "bootstrap"
        )

    def test_stale_candidate_is_rejected_before_release(self):
        with patch.object(frontend_inputs, "current_main_fingerprint", return_value="current"):
            frontend_inputs.require_current("current")
            with self.assertRaisesRegex(SystemExit, "stale"):
                frontend_inputs.require_current("older")
