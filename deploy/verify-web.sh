#!/usr/bin/env bash
# Read-only verification for EC2, usable before or after an approved vhost reload.
set -euo pipefail

project=macket-canary-011
manifest=/opt/macket-canary-011/compose.yaml
compose=(sudo -n docker compose -p "$project" -f "$manifest")

systemctl is-active --quiet nginx
if [[ "${1:-}" == '--legacy' ]]; then
  systemctl is-active --quiet macket-api
fi
awk '/^MemAvailable:/ { print "MemAvailableKiB=" $2; if ($2 < 150 * 1024) exit 1 }' /proc/meminfo
grep '^oom_kill ' /proc/vmstat

for service in backend-api frontend; do
  id=$("${compose[@]}" ps -q "$service")
  test -n "$id"
  health=$(sudo -n docker inspect --format '{{.State.Health.Status}} {{.State.OOMKilled}} {{.RestartCount}}' "$id")
  printf '%s %s\n' "$service" "$health"
  test "$health" = 'healthy false 0'
done

for path in / /admin/ /api/health /api/db-health '/api/products?page=1&limit=1'; do
  curl --fail --silent --show-error --max-time 5 --output /dev/null \
    --write-out "loopback $path %{http_code}\n" "http://127.0.0.1:8080$path"
done

for host in macket.io.vn origin.macket.io.vn; do
  for path in / /admin/ /api/health; do
    curl --fail --silent --show-error --max-time 5 --output /dev/null \
      --resolve "$host:443:127.0.0.1" --write-out "$host $path %{http_code}\n" "https://$host$path"
  done
done
