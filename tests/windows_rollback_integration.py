"""Run the isolated Windows Docker Desktop rollback fixture manually."""

import os
import pathlib
import subprocess
import tempfile
import uuid
from unittest import TestCase
from unittest.mock import patch

import yaml

from deploy import deploy_web as release


def docker(*args, timeout=60):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(f"docker {args[0]}: {result.stderr or result.stdout}")
    return result.stdout.strip()


def cached_reference(component, tag):
    repository = f"{release.REGISTRY}/macket-{component}"
    references = docker(
        "image", "inspect", "--format", "{{range .RepoDigests}}{{println .}}{{end}}",
        f"{repository}:{tag}",
    )
    return next(ref for ref in references.splitlines() if ref.startswith(repository + "@sha256:"))


def verify(root):
    project = "macket-rollback-" + uuid.uuid4().hex[:10]
    manifest = root / "compose.yaml"
    dc = ["docker", "compose", "-p", project, "-f", str(manifest)]
    known = {
        component: [cached_reference(component, tag) for tag in
                    ("0.1.0-6a3fa44-ec2-parity", "0.1.1-ec2-parity")]
        for component in release.SERVICES
    }
    start = {
        "backend-api": (
            "mkdir -p /tmp/fixture-web; printf fixture > /tmp/fixture-web/index.html; "
            "exec python -m http.server 8080 --directory /tmp/fixture-web"
        ),
        "frontend": (
            """printf '%s' 'pid /tmp/fixture-nginx.pid; events {} http { server { listen 8080; """
            """location / { return 200 "fixture"; } } }' > /tmp/fixture-nginx.conf; """
            "exec nginx -c /tmp/fixture-nginx.conf -g 'daemon off;'"
        ),
    }
    requests = {
        "backend-api": [
            "python", "-c", 'from urllib.request import urlopen; '
            'print(urlopen("http://127.0.0.1:8080/",timeout=2).read().decode())',
        ],
        "frontend": ["wget", "-q", "-O", "-", "http://127.0.0.1:8080/"],
    }
    services = {
        service: {
            "image": known[component][0],
            "platform": "linux/amd64",
            "pull_policy": "never",
            "restart": "unless-stopped",
            "entrypoint": ["/bin/sh", "-ec"],
            "command": [start[service]],
            "healthcheck": {
                "test": ["CMD", *requests[service]],
                "interval": "1s",
                "timeout": "3s",
                "retries": 3,
            },
            "networks": ["fixture"],
        }
        for component, service in release.SERVICES.items()
    }
    manifest.write_text(
        yaml.safe_dump({"services": services, "networks": {"fixture": {"internal": True}}}),
        encoding="utf-8",
    )
    real_command = release.command
    health_failures = []
    fault_for = None

    def fixture_command(args, *, stdin=None, timeout=30):
        if args[0] == "aws":
            if "get-caller-identity" in args:
                return "arn:aws:sts::393840684011:assumed-role/MacketEC2Role/windows-fixture"
            if "get-login-password" in args:
                return "fixture"
            raise AssertionError("Unexpected AWS command")
        if args[:2] == ["docker", "--config"]:
            if args[3] == "login" and args[-1] == release.REGISTRY:
                return "local fixture"
            assert args[3] == "pull" and any(args[-1] in refs for refs in known.values())
            assert docker("image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", args[-1]) == "linux/amd64"
            return ""
        if (fault_for and args[:len(dc)] == dc and args[len(dc)] == "up"
                and args[-1] == fault_for[0] and fault_for[1] in manifest.read_text()):
            fault = root / "fault.yaml"
            override = {"services": {fault_for[0]: {"healthcheck": {"test": ["CMD", "sh", "-c", "exit 1"]}}}}
            fault.write_text(yaml.safe_dump(override), encoding="utf-8")
            try:
                return real_command(dc + ["-f", str(fault)] + args[len(dc):], timeout=timeout)
            except RuntimeError:
                cid = docker(*dc[1:], "ps", "-q", fault_for[0])
                health_failures.append(
                    docker("inspect", "--format", "{{.State.Health.Status}} {{.Config.Image}}", cid)
                )
                raise
        return real_command(args, stdin=stdin, timeout=timeout)

    def fixture_smoke():
        for service, request in requests.items():
            assert docker(*dc[1:], "exec", "-T", service, *request) == "fixture"

    try:
        docker(*dc[1:], "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "30")
        with (
            patch.multiple(release, ROOT=root, MANIFEST=manifest, DC=dc, command=fixture_command,
                           smoke=fixture_smoke, host_resources=lambda: (512, 0)),
            patch.object(release.os, "geteuid", return_value=0, create=True),
        ):
            for component, service in release.SERVICES.items():
                previous, promoted = known[component]
                peer = next(name for name in services if name != service)
                peer_before = release.container(peer)
                before = release.container(service)
                assert before[1] == previous
                release.deploy(component, promoted.split("@")[1])
                updated = release.container(service)
                assert updated[0] != before[0] and updated[1] == promoted
                assert release.container(peer) == peer_before
                print("PASS replace", component, promoted, "peer unchanged", peer_before[0], flush=True)

                manifest_before = manifest.read_bytes()
                fault_for = (service, previous)
                try:
                    release.deploy(component, previous.split("@")[1])
                except RuntimeError as exc:
                    assert str(exc).startswith("docker compose failed"), str(exc)
                else:
                    raise AssertionError("Expected Docker to reject the unhealthy replacement")
                finally:
                    fault_for = None
                assert health_failures[-1] == "unhealthy " + previous
                restored = release.container(service)
                assert restored[0] != updated[0] and restored[1] == promoted
                assert release.container(peer) == peer_before and manifest.read_bytes() == manifest_before
                print("PASS rollback", component, promoted, "peer unchanged", peer_before[0], flush=True)
    finally:
        docker(*dc[1:], "down", "--remove-orphans", "--timeout", "5", timeout=30)
        label = "label=com.docker.compose.project=" + project
        assert not docker("ps", "-a", "--filter", label, "--format", "{{.Names}}")
        assert not docker("network", "ls", "--filter", label, "--format", "{{.Name}}")
        print("Fixture cleaned:", project)


class WindowsRollbackIntegration(TestCase):
    def test_replace_and_rollback_each_service(self):
        if not __debug__ or os.name != "nt" or os.environ.get("DOCKER_HOST"):
            self.skipTest("Use Windows Docker Desktop with assertions enabled and DOCKER_HOST unset")
        context = docker("context", "show")
        endpoint = docker("context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}")
        self.assertEqual(endpoint, "npipe:////./pipe/dockerDesktopLinuxEngine")
        with tempfile.TemporaryDirectory(prefix="macket-rollback-") as directory:
            verify(pathlib.Path(directory))
