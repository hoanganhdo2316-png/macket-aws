import os
import json
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def fetch_dataset(dataset_id, limit=100):
    if not dataset_id or not isinstance(dataset_id, str):
        raise ValueError("Invalid dataset ID")

    token = os.environ.get("APIFY_TOKEN")

    if not token:
        raise ValueError("APIFY_TOKEN is not configured")

    params = urlencode({
        "limit": limit,
        "clean": "true"
    })

    url = (
        "https://api.apify.com/v2/datasets/"
        f"{dataset_id}/items?{params}"
    )

    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
    )

    with urlopen(request, timeout=30) as response:
        data = json.load(response)

    if not isinstance(data, list):
        raise ValueError("Unexpected Apify dataset response")

    return data
