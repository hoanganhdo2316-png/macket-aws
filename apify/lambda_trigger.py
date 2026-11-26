import json
import logging
import os
from decimal import Decimal
from urllib.request import Request, urlopen

from apify_client import ApifyClient
from apify_client.errors import ApifyApiError

from app.collector import build_actor_input

LOG = logging.getLogger("macket.lambda")
LOG.setLevel(logging.INFO)
ACTOR_ID = "dGw5RQgZjVug05E1h"
ACTIVE_RUNS = ["READY", "RUNNING", "TIMING-OUT", "ABORTING"]


def collector_request(path, data=None):
    url = os.environ["COLLECTOR_CONFIG_URL"]
    if not url.startswith("https://") or not url.endswith("/config"):
        raise ValueError("Invalid collector config URL")

    request = Request(
        url.removesuffix("/config") + path,
        data=None if data is None else json.dumps(data).encode("utf-8"),
        headers={
            "X-Collector-Token": os.environ["COLLECTOR_CONFIG_TOKEN"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )

    with urlopen(request, timeout=15) as response:
        return None if response.status == 204 else json.load(response)


def fetch_config():
    config = collector_request("/config")

    groups = config["groups"]
    settings = config["settings"]
    blocked = config["exclude_authors"]

    if not isinstance(groups, list) or not groups:
        raise ValueError("No enabled Facebook groups")

    if not isinstance(blocked, list):
        raise ValueError("Invalid author skip list")

    urls = [group["url"] for group in groups]

    if len(urls) != len(set(urls)):
        raise ValueError("Duplicate Facebook group URL")

    # Current Apify Actor supports one shared limit.
    # Do not silently ignore per-group overrides.
    default_limit = int(settings["max_posts_per_group"])

    for group in groups:
        custom = group.get("max_posts")
        if custom is not None and int(custom) != default_limit:
            raise ValueError(
                "Per-group max_posts override is not yet supported"
            )

    return groups, settings, blocked


def report_scan(scan_id, state, run_id=None):
    payload = {"scan_id": scan_id, "state": state, "run_id": run_id}
    try:
        collector_request("/scan/report", payload)
    except OSError:
        # Reporting the same outcome is safe even if the first response was lost.
        collector_request("/scan/report", payload)


def lambda_handler(event, context):
    event = event or {}
    if event.get("dry_run"):
        groups, settings, blocked = fetch_config()
        return {
            "status": "DRY_RUN",
            "groups": len(groups),
            "blocked_sellers": len(blocked),
            "actor_input": build_actor_input(groups, settings, blocked),
            "config_source": "macket_api",
        }

    scan_id = collector_request("/scan/claim", {"scan_id": event.get("scan_id")})["scan_id"]
    if scan_id is None:
        return {"status": "SKIPPED", "reason": "active_or_expired_scan"}

    try:
        groups, settings, blocked = fetch_config()
        actor_input = build_actor_input(groups, settings, blocked)
        max_items = len(groups) * actor_input["maxPostsPerGroup"]
        charge_limit = Decimal(str(settings["max_total_charge_usd"]))
        token = collector_request("/apify-token").get("token")
        if not token:
            raise ValueError("Missing APIFY_TOKEN")
        actor = ApifyClient(token, max_retries=0, timeout_secs=15).actor(ACTOR_ID)
        active = actor.runs().list(status=ACTIVE_RUNS, limit=1, desc=True).items
    except Exception as exc:
        report_scan(scan_id, "FAILED")
        LOG.warning("Collector preparation failed (%s)", type(exc).__name__)
        return {"status": "FAILED", "reason": "preparation"}

    if active:
        report_scan(scan_id, "RUNNING", active[0]["id"])
        return {"status": "SKIPPED", "reason": "existing_apify_run", "run_id": active[0]["id"]}

    try:
        run = actor.start(
            run_input=actor_input, max_items=max_items, max_total_charge_usd=charge_limit,
        )
        run_id = run["id"]
        if not run_id:
            raise ValueError("Missing Apify run ID")
    except ApifyApiError as exc:
        state = "FAILED" if 400 <= exc.status_code < 500 and exc.status_code != 408 else "UNKNOWN"
        report_scan(scan_id, state)
        LOG.warning("Apify start returned HTTP %s", exc.status_code)
        return {"status": state, "reason": "apify_start"}
    except Exception as exc:
        # Never repeat a paid start when Apify might already have received it.
        report_scan(scan_id, "UNKNOWN")
        LOG.warning("Apify start could not be confirmed (%s)", type(exc).__name__)
        return {"status": "UNKNOWN", "reason": "apify_start"}

    report_scan(scan_id, "RUNNING", run_id)
    result = {
        "status": run.get("status"),
        "run_id": run_id,
        "actor_id": ACTOR_ID,
        "groups": len(groups),
        "config_source": "macket_api",
    }

    LOG.info("Apify run started: %s", json.dumps(result))
    return result
