"""Select changed Frontend inputs and reject superseded releases."""

import hashlib
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


INPUTS = ("frontend", "ci/frontend-smoke.sh")
ENVIRONMENT = "frontend-production-auto"


def fingerprint(commit):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Expected a full Git commit SHA")
    tree = subprocess.check_output(["git", "ls-tree", "-r", "-z", commit, "--", *INPUTS])
    if not tree:
        raise ValueError("Frontend source tree is missing")
    return hashlib.sha256(tree).hexdigest()


def current_main_fingerprint():
    subprocess.run(
        ["git", "fetch", "--no-tags", "origin", "refs/heads/main"],
        check=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], text=True).strip()
    return fingerprint(head)


def github_pages(path, **filters):
    endpoint = f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}"
    page = 1
    while True:
        query = urlencode(dict(filters, per_page=100, page=page))
        request = Request(
            f"{endpoint}?{query}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            },
        )
        with urlopen(request, timeout=15) as response:
            items = json.load(response)
        yield from items
        if len(items) < 100:
            return
        page += 1


def last_healthy_deployment(deployments, statuses, baseline):
    for deployment in deployments:
        if any(status["state"] == "success" for status in statuses(deployment["id"])):
            return deployment["sha"]
    return baseline


def release_base():
    deployments = github_pages("deployments", environment=ENVIRONMENT)

    def statuses(deployment_id):
        return github_pages(f"deployments/{deployment_id}/statuses")

    return last_healthy_deployment(deployments, statuses, os.environ["BASELINE_SHA"])


def plan(head, base):
    head_key = fingerprint(head)
    base_key = fingerprint(base)
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], check=True)
    return head_key, head_key != base_key


def require_current(expected):
    if current_main_fingerprint() != expected:
        raise SystemExit("Frontend inputs have changed on main. This release is stale.")


def main():
    if sys.argv[1] == "require-current":
        require_current(os.environ["EXPECTED_INPUTS"])
        return

    head = os.environ["GITHUB_SHA"]
    if os.environ["GITHUB_EVENT_NAME"] == "pull_request":
        base = os.environ["PR_BASE_SHA"]
    else:
        base = release_base()
        require_current(fingerprint(head))
    key, changed = plan(head, base)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        print(f"inputs={key}\nchanged={str(changed).lower()}", file=output)


if __name__ == "__main__":
    main()
