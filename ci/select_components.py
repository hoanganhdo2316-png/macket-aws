"""Select image builds from paths in the release diff."""

import json
import subprocess
import sys


def components(paths):
    changed = set()
    for path in paths:
        if path.startswith((".github/workflows/web-ci.", "ci/")) or path == "compose.yaml":
            changed.update(("backend", "frontend"))
        elif path.startswith(("backend/", "tests/staging_", "tests/compose.writes", "tests/container")):
            changed.add("backend")
        elif path.startswith("frontend/"):
            changed.add("frontend")
    return sorted(changed)


if __name__ == "__main__":
    base, head = sys.argv[1:]
    names = subprocess.check_output(["git", "diff", "--name-only", "-z", base, head, "--"])
    print(json.dumps(components(names.decode().split("\0"))))
