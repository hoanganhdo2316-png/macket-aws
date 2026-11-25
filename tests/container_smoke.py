"""Run on the isolated Compose network with tests/container.env.example."""

import io
import json
import os
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from openai import OpenAI
from PIL import Image

import classification_worker_v2 as classification
import extraction_worker as extraction
import main
import media_worker as media
import scheduler_routes as scheduler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(path, expected=200, *, method="GET", headers=None, body=None, follow=True):
    headers = dict(headers or {})
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body).encode()
    req = Request("http://frontend" + path, data=body, headers=headers, method=method)
    try:
        opener = urlopen if follow else build_opener(NoRedirect()).open
        response = opener(req, timeout=8)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (path, response.status, expected)
        return response.read()


def fake_engine(*results):
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.side_effect = results
    return engine


def row(value):
    result = MagicMock()
    result.mappings.return_value.first.return_value = value
    return result


assert json.loads(request("/api/health"))["status"] == "ok"
request("/admin", 301, follow=False)
assert request("/macket-container-audit-nonexistent") == request("/")
for page in ("/", "/admin", "/admin/"):
    html = request(page).decode()
    asset = html.split('src="/assets/', 1)[1].split('"', 1)[0]
    assert request("/assets/" + asset)
request("/api/admin/scheduler", 401)
admin = {"X-Admin-Token": os.environ["ADMIN_API_TOKEN"]}
request("/api/admin/scheduler", 409, method="PATCH", headers=admin, body={"enabled": True})
request("/api/webhooks/apify", 401, method="POST", body={"eventType": "TEST"})
webhook = {"X-Webhook-Token": os.environ["APIFY_WEBHOOK_TOKEN"]}
result = request("/api/webhooks/apify", method="POST", headers=webhook, body={"eventType": "TEST"})
assert json.loads(result)["status"] == "WEBHOOK_TEST_OK"
schedule = {"State": "DISABLED", "Target": {}, "FlexibleTimeWindow": {"Mode": "OFF"},
            "ScheduleExpression": "rate(60 minutes)"}
with TestClient(main.app) as client, \
        patch.object(main.engine, "connect") as connect, \
        patch.object(main.engine, "begin") as begin, \
        patch.object(scheduler.client, "get_schedule", return_value=schedule), \
        patch.object(scheduler.client, "update_schedule") as update:
    connect.return_value.__enter__.return_value.execute.return_value.mappings.return_value.one.return_value = {
        "enabled": False, "interval_minutes": 60,
    }
    begin.return_value.__enter__.return_value.execute.return_value.mappings.return_value.one.return_value = {
        "enabled": False, "interval_minutes": 30,
    }
    read = client.get("/api/admin/scheduler", headers=admin)
    assert read.status_code == 200 and read.json()["aws_sync_status"] == "synced"
    changed = client.patch("/api/admin/scheduler", headers=admin, json={"interval_minutes": 30})
    assert changed.status_code == 200 and changed.json()["aws_expression"] == "rate(30 minutes)"
    assert update.call_args.kwargs["State"] == "DISABLED"
print("PASS: HTTP routing, Client/Admin assets, admin/webhook auth, scheduler lock and AWS mock")

key = {"encrypted_token": "fixture"}
post = {"content": "Fixture post"}
prompt = {"id": 7, "version": 7}
existing = MagicMock()
existing.scalar_one_or_none.return_value = None
engine = fake_engine(row(post), row(prompt), row(key), existing)
with patch.object(main, "engine", engine), patch.object(classification, "OpenAI") as llm:
    assert classification.classify_stage1(1, execute=False)["status"] == "dry_run"
    llm.assert_not_called()

post = {"post_type": "selling", "seller_type": "individual", "post_id": 1,
        "extraction_status": "pending", "content": "Fixture post"}
with patch.object(main, "engine", fake_engine(row(post), row(key))), patch.object(extraction, "OpenAI") as llm:
    assert extraction.extract_products(1, execute=False)["status"] == "dry_run"
    llm.assert_not_called()
assert callable(OpenAI(api_key="fixture").chat.completions.parse)
assert main.engine.url.query["sslmode"] == "require"
print("PASS: classification/extraction dry-run mocks, OpenAI method and PostgreSQL TLS setting")

image = io.BytesIO()
Image.new("RGB", (1, 1)).save(image, "PNG")
response = MagicMock()
response.is_redirect = False
response.iter_content.return_value = [image.getvalue()]
request_context = MagicMock()
request_context.__enter__.return_value = response
with patch.object(media.requests, "get", return_value=request_context):
    _, extension, mime = media.download_image("https://fixture.fbcdn.net/image.png")
    assert (extension, mime) == ("png", "image/png")
print("PASS: media download/decode fixture")
