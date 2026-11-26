#!/usr/bin/env bash
set -euo pipefail

prefix="macket-ci-frontend-$$"
cleanup() {
  for name in "$prefix-web" "$prefix-api"; do
    docker container rm -f "$name" >/dev/null 2>&1 || true
  done
  docker network rm "$prefix" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create --internal "$prefix" >/dev/null
docker run -d --name "$prefix-api" --network "$prefix" --network-alias backend-api \
  python:3.12-slim-trixie python -c 'from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path == "/api/health?fixture=1"
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"macket-fixture")
HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()' >/dev/null
docker run -d --name "$prefix-web" --network "$prefix" macket-frontend:ci >/dev/null
docker exec "$prefix-web" nginx -t
for attempt in {1..12}; do
  if docker exec "$prefix-web" wget -q -O /dev/null http://127.0.0.1/healthz; then break; fi
  sleep 1
done
docker exec "$prefix-web" sh -ec '
  wget -q -O /tmp/public.html http://127.0.0.1/
  wget -q -O /tmp/admin.html http://127.0.0.1/admin/
  grep -q "/assets/" /tmp/public.html
  grep -q "/assets/" /tmp/admin.html
  test "$(wget -qO- "http://127.0.0.1/api/health?fixture=1")" = macket-fixture
'
docker run --rm --network none -v "$PWD/frontend:/src:ro" -w /src node:24-bookworm-slim \
  sh -ec 'for file in vite.config.js src/*.js; do node --check "$file"; done'
