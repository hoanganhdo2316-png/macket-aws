import json
import logging
import os
from decimal import Decimal
from urllib.request import Request, urlopen

from app.collector import build_actor_input

LOG = logging.getLogger("macket.lambda")
LOG.setLevel(logging.INFO)


def fetch_config():
    url = os.environ["COLLECTOR_CONFIG_URL"]
    token = os.environ["COLLECTOR_CONFIG_TOKEN"]

    if not url.startswith("https://"):
        raise ValueError("Collector config URL must use HTTPS")

    request = Request(
        url,
        headers={"X-Collector-Token": token},
    )

    with urlopen(request, timeout=15) as response:
        config = json.load(response)

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


def lambda_handler(event, context):
    event = event or {}

    # Always load latest configuration from FastAPI/RDS.
    groups, settings, blocked = fetch_config()

    actor_input = build_actor_input(
        groups,
        settings,
        blocked,
    )

    if event.get("dry_run"):
        return {
            "status": "DRY_RUN",
            "groups": len(groups),
            "blocked_sellers": len(blocked),
            "actor_input": actor_input,
            "config_source": "macket_api",
        }

    # Fetch the latest Apify Token from Macket Admin/RDS.
    config_url = os.environ["COLLECTOR_CONFIG_URL"]

    if not config_url.startswith("https://") or not config_url.endswith("/config"):
        raise ValueError("Invalid collector config URL")

    token_url = config_url.removesuffix("/config") + "/apify-token"

    token_request = Request(
        token_url,
        headers={
            "X-Collector-Token": os.environ["COLLECTOR_CONFIG_TOKEN"],
            "Accept": "application/json",
        },
    )

    with urlopen(token_request, timeout=15) as response:
        credentials = json.load(response)

    token = credentials.get("token")

    if not token:
        raise ValueError("Missing APIFY_TOKEN")

    from apify_client import ApifyClient

    actor_id = "dGw5RQgZjVug05E1h"
    client = ApifyClient(token)

    max_items = (
        len(groups) * actor_input["maxPostsPerGroup"]
    )

    run = client.actor(actor_id).start(
        run_input=actor_input,
        max_items=max_items,
        max_total_charge_usd=Decimal(
            str(settings["max_total_charge_usd"])
        ),
    )

    result = {
        "status": run.get("status"),
        "run_id": run.get("id"),
        "actor_id": actor_id,
        "groups": len(groups),
        "config_source": "macket_api",
    }

    LOG.info("Apify run started: %s", json.dumps(result))
    return result
