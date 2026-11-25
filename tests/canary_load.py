"""Small read-only, loopback-only comparison for the Macket EC2 web canary."""

import concurrent.futures
import http.client
import json
import math
import pathlib
import socket
import ssl
import subprocess
import threading
import time


PROJECT = ["sudo", "-n", "docker", "compose", "-p", "macket-canary-011",
           "-f", "/opt/macket-canary-011/compose.yaml"]
PATHS = ("/api/health", "/api/products?page=1&limit=5")
SERVICES = ("macket-api", "nginx")
HOSTS = ("macket.io.vn", "origin.macket.io.vn")
STOP = threading.Event()
REASON = []


def command(*args):
    return subprocess.check_output(args, text=True, timeout=5).strip()


def stats_file(path):
    return {line.split()[0].rstrip(":"): int(line.split()[1])
            for line in pathlib.Path(path).read_text().splitlines() if len(line.split()) > 1}


def pid(unit):
    return command("systemctl", "show", "-p", "MainPID", "--value", unit)


def docker_states(ids):
    rows = command("sudo", "-n", "docker", "inspect", "--format",
                   "{{.State.Health.Status}} {{.State.OOMKilled}} {{.RestartCount}} {{.State.Pid}}",
                   *ids).splitlines()
    return [row.split() for row in rows]


class OriginConnection(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(("127.0.0.1", 443), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def get(connection, path):
    start = time.perf_counter()
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return (time.perf_counter() - start) * 1000, response.status
    except (OSError, http.client.HTTPException):
        return (time.perf_counter() - start) * 1000, 0
    finally:
        connection.close()


def request_http(port, path):
    return get(http.client.HTTPConnection("127.0.0.1", port, timeout=2), path)


def sample_cpu():
    fields = [int(x) for x in pathlib.Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    return sum(fields), fields[3] + fields[4]


def main():
    ids = [command(*PROJECT, "ps", "-q", service) for service in ("backend-api", "frontend")]
    if not all(ids) or len(set(ids)) != 2:
        raise RuntimeError("Expected two canary web containers")
    initial = docker_states(ids)
    pids = [pid(service) for service in SERVICES]
    oom = stats_file("/proc/vmstat")["oom_kill"]
    group = command("systemctl", "show", "-p", "ControlGroup", "--value", SERVICES[0])
    root = pathlib.Path("/sys/fs/cgroup")
    cg = {"legacy": root / group.lstrip("/")}
    for name, state in zip(("backend", "frontend"), initial, strict=True):
        path = pathlib.Path(f"/proc/{state[3]}/cgroup").read_text().strip().split(":", 2)[-1]
        cg[name] = root / path.lstrip("/")

    def check():
        ram = stats_file("/proc/meminfo")["MemAvailable"] / 1024
        if ram < 150 or stats_file("/proc/vmstat")["oom_kill"] != oom:
            raise RuntimeError(f"RAM/OOM stop gate, available={ram:.1f} MiB")
        return ram

    def check_services():
        if [pid(service) for service in SERVICES] != pids or any(v == "0" for v in pids):
            raise RuntimeError("Legacy process changed")
        states = docker_states(ids)
        if states != initial or any(s[:2] != ["healthy", "false"] for s in states):
            raise RuntimeError("Canary health, restart count or OOM state changed")
        for host in HOSTS:
            latency, status = get(OriginConnection(host, timeout=2, context=ssl.create_default_context()), PATHS[0])
            if status != 200 or latency > 500:
                raise RuntimeError(f"Origin health gate: {host}, HTTP {status}, {latency:.1f} ms")

    def watch():
        try:
            tick = 0
            while not STOP.is_set():
                check()
                if tick % 3 == 0:
                    check_services()
                tick += 1
                STOP.wait(1)
        except Exception as exc:
            REASON.append(str(exc))
            STOP.set()

    def snapshot():
        cpu = sample_cpu()
        usage = {name: stats_file(path / "cpu.stat")["usage_usec"] for name, path in cg.items()}
        return time.monotonic(), cpu, usage

    def phase(label, port, rate):
        before = snapshot()
        memory = {name: 0 for name in cg}
        lowest = float("inf")
        pending, submitted = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for index in range(12 * rate):
                deadline = before[0] + index / rate
                if STOP.wait(max(0, deadline - time.monotonic())):
                    break
                lowest = min(lowest, check())
                for name, path in cg.items():
                    memory[name] = max(memory[name], int((path / "memory.current").read_text()))
                pending = [f for f in pending if not f.done()]
                if len(pending) >= 3:
                    raise RuntimeError("Three concurrent requests still pending; stop load")
                path = PATHS[index % len(PATHS)]
                future = pool.submit(request_http, port, path)
                pending.append(future)
                submitted.append((path, future))
            STOP.wait(max(0, before[0] + 12 - time.monotonic()))
        after = snapshot()
        elapsed = after[0] - before[0]
        total = after[1][0] - before[1][0]

        def result(rows):
            if not rows:
                return dict(n=0, errors=0, p50=None, p95=None)
            success = sorted(ms for ms, code in rows if code == 200)
            def percentile(p):
                return round(success[math.ceil(p * len(success)) - 1], 2) if success else None
            return dict(n=len(rows), errors=len(rows) - len(success), p50=percentile(.5), p95=percentile(.95))

        rows = [(path, future.result()) for path, future in submitted]
        summary = result([row for _, row in rows])
        print(json.dumps(dict(target=label, rps=rate, seconds=round(elapsed, 2), **summary,
                              products=result([row for path, row in rows if path == PATHS[1]]),
                              mem_min_mib=round(lowest, 1) if rows else None,
                              host_cpu_pct=round(100 * (1 - (after[1][1] - before[1][1]) / total), 2),
                              cpu_pct_one_core={name: round((after[2][name] - before[2][name]) / elapsed / 10000, 2) for name in cg},
                              mem_peak_mib={name: round(value / 1048576, 1) for name, value in memory.items()})), flush=True)
        if summary["errors"]:
            raise RuntimeError("Request errors observed; stop load")

    check()
    check_services()
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        for rate in (1, 3, 6):
            order = (("legacy-direct", 8000), ("canary-via-nginx", 8080))
            if rate == 3:
                order = tuple(reversed(order))
            for target, port in order:
                if STOP.is_set():
                    raise RuntimeError(REASON[0])
                phase(target, port, rate)
        check()
        check_services()
    finally:
        STOP.set()
        watcher.join(timeout=5)
    if REASON:
        raise RuntimeError(REASON[0])
    print(json.dumps({"status": "PASS", "initial_restart_counts": [s[2] for s in initial],
                      "final_restart_counts": [s[2] for s in docker_states(ids)], "oom_kill": oom}), flush=True)


if __name__ == "__main__":
    main()
