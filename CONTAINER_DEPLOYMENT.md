# Macket container deployment

## Current production

The web cutover passed on 2026-11-26. Host Nginx terminates HTTPS for `macket.io.vn` and `origin.macket.io.vn`; both forward web and `/api/` traffic to `127.0.0.1:8080`. The live Compose project is `macket-canary-011` at `/opt/macket-canary-011/compose.yaml`, with only `backend-api` and `frontend`. Both have `restart: unless-stopped`. The API uses RDS PostgreSQL through TLS in read-write mode. Runtime variables are read from the existing protected file outside the image. The legacy systemd API is inactive/disabled and its unit, source, venv and static release are retained.

| ECR repository | Tag | Deployed digest |
|---|---|---|
| `macket-backend` | `0.1.1-ec2-parity` | `sha256:a47c1f2649a866abe6b3aac45767bd675ce63eaa755ef1ea86662cb2adbd5fb1` |
| `macket-frontend` | `0.1.2-publish-test-467a3f41e51d77cf79d703176a4908affe10ca06` | `sha256:8e2f4ea7b6718fb861e14ba31e856aeff1e9d52b8ce401b1328cd501811f5ec8` |

The Frontend-only CD trial deployed the digest above on 2026-11-26. GitHub Actions run `45764577467` completed successfully and the service passed the 10-minute observation. The Backend container ID and digest stayed the same. The last healthy Frontend digest before this change was `sha256:7ca48780b2463e79c3bf63c142e4dd1980754311496eb704dd804cb4708b523f`. See the trial and rollback details in [CI/CD](CI_CD.md#first-frontend-cd-trial-on-production-ec2).

The cutover rollback files and checksums are under `/var/backups/macket-cutover-20261126`. To roll back the original cutover, start and enable `macket-api.service`, verify port 8000, restore the saved host Nginx site, run `nginx -t`, reload and verify both HTTPS vhosts before stopping the containers. Routine web image rollback restores the previous Compose digest for the affected component and leaves host Nginx and the other component unchanged. In this release the operator confirmed RDS backup/PITR readiness, the available manual snapshot and the S3 route. AWS resources remain outside the web release workflow. See [CI/CD preparation](CI_CD.md).

## Local candidate and production prerequisites

The Compose project runs Uvicorn and Nginx on a private bridge between services. Only Nginx is published, on host loopback. Keep the existing EC2 Nginx in front for HTTPS. Route the existing virtual host to `127.0.0.1:8080` (or the approved free port) and preserve the URI, host, HTTPS scheme, and client forwarding headers. Confirm existing limits, timeouts, access rules and webhook behavior before switching. The bridge requires outbound access for the API and jobs. RDS, S3, EventBridge Scheduler and Lambda remain external.

The EC2 audit on 2026-11-25 verified a t3.micro (`linux/amd64`, 2 vCPU, 909 MiB RAM, no swap), Python 3.12.3 and Uvicorn bound to `127.0.0.1:8000` under `macket-api.service`. The candidate uses the same Python feature release with a newer patch version and pins the production venv's runtime packages. The web-service limits in Compose start at 256 MiB / 1 CPU for API and 64 MiB / 0.25 CPU for Frontend. Check peak memory and CPU on a canary before changing traffic. The audit found no running worker, worker unit/timer, or cron trigger. Historical database records show the Stage 1 v2 claim path, extraction and media output. Preserve the current execution model and leave jobs inactive during web cutover.

The two HTTPS vhosts, `macket.io.vn` and `origin.macket.io.vn`, serve `/var/www/macket` and currently proxy `/api/` to the systemd API. Keep both certificates and Certbot renewal settings. Port 8080 was unused during the audit. PostgreSQL 18.3 was inspected in a read-only TLS session. Lambda is independent of this web release, and its image reconciliation applies to any future Lambda release. The container candidate must be tied to an approved source commit before publishing.

On EC2, IMDSv1 returned 401, IMDSv2 token acquisition succeeded with response TTL 2, and the instance role authenticated an S3 `HeadObject`. Verify IMDSv2, role access, actual S3 Gateway Endpoint routing and RDS TLS from the container during an approved canary. Any required AWS changes need their own approval.

## Runtime configuration

Set `MACKET_RUNTIME_ENV` to an absolute file path outside the checkout, with access restricted to the operator running Compose. Supply only the existing, approved runtime values. Treat Docker access as privileged because container environment is visible to users with that access.

| Variable | Use |
|---|---|
| `DB_HOST`, `DB_NAME`, `DB_PORT` (default `5432`), `DB_USER`, `DB_PASSWORD` | PostgreSQL, using the existing `sslmode=require` |
| `ADMIN_API_TOKEN`, `COLLECTOR_CONFIG_TOKEN`, `APIFY_WEBHOOK_TOKEN` | Admin API, Lambda config/credentials API, webhook authentication |
| `CREDENTIALS_ENCRYPTION_KEY` | Existing Fernet key for credentials in PostgreSQL |
| `APIFY_TOKEN` | Webhook and backend ingestion requests |
| `MACKET_CLASSIFICATION_MODEL`, `MACKET_EXTRACTION_MODEL` | Optional model overrides used by the existing workers |
| `MACKET_MEDIA_BUCKET` | Public API's S3 read/presign setting. The media worker has a separate existing hardcoded bucket, so verify alignment. |
| `MACKET_FRONTEND_PORT`, `MACKET_BACKEND_IMAGE`, `MACKET_FRONTEND_IMAGE` | Host loopback port and image references (use digest references on EC2) |
| `COLLECTOR_CONFIG_URL`, `COLLECTOR_CONFIG_TOKEN` | Existing Lambda environment, separate from Compose |

The backend reads the OpenAI key from encrypted PostgreSQL credentials. Use the EC2 instance role for AWS SDK access and ECR pull, without passing an AWS credential file or AWS access keys into containers.

## Worker handoff

`docker compose up backend-api frontend` starts the web services only. The three `jobs` services share the backend image and fail closed unless given an explicit command. For an approved one-shot invocation, use `docker compose run --rm --no-deps <worker-service> python <verified-script> <verified-args>`. Use the currently deployed classification script/version and preserve the current trigger and arguments. If an existing timer or cron is responsible, migrate that same caller after confirming job drain and exclusive ownership. Resolve daemon supervision separately if production uses a daemon. Worker exit codes and the existing DB/job logs are the appropriate checks for one-shot commands.

## Build and publish after approval

Example shell commands for release operators. Set `EC2_PLATFORM`, `LAMBDA_PLATFORM` and `ACCOUNT_ID` from verified production metadata. ECR inventory at audit time exposed `macket-lambda-collector`; verify or provision `macket-backend` and `macket-frontend` after approval.

```sh
REGION=ap-southeast-1
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
TAG="0.1.0-$(git rev-parse --short=12 HEAD)"
docker buildx build --platform "$EC2_PLATFORM" --load -t "macket-backend:$TAG" backend
docker buildx build --platform "$EC2_PLATFORM" --load -t "macket-frontend:$TAG" frontend
# Independent Lambda release, only after source and live digest are reconciled:
# docker buildx build --platform "$LAMBDA_PLATFORM" --provenance=false --load \
#   -f apify/Dockerfile.lambda -t "macket-lambda-collector:$TAG" apify
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
for image in macket-backend macket-frontend; do
  docker tag "$image:$TAG" "$REGISTRY/$image:$TAG"
  docker push "$REGISTRY/$image:$TAG" || exit 1
  aws ecr describe-images --region "$REGION" --repository-name "$image" --image-ids "imageTag=$TAG" || exit 1
done
```

Use a new version/SHA tag and record the digest. Verify push principal permissions (`GetAuthorizationToken`, `BatchCheckLayerAvailability`, `InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`, `PutImage`, `BatchGetImage`) and EC2 pull permissions (`GetAuthorizationToken`, `BatchCheckLayerAvailability`, `GetDownloadUrlForLayer`, `BatchGetImage`). Read access to ECR alone does not establish these permissions. A Lambda release needs its own approval and a compatible single-architecture image, with the existing digest kept for rollback.

## Original EC2 cutover procedure (historical)

The initial canary used project `macket-canary-011`, `/opt/macket-canary-011/compose.yaml`, TCP `127.0.0.1:8080` and both approved `0.1.1-ec2-parity` digests. The source-controlled image-only equivalent is `deploy/compose.web.yaml`. The checks against the old systemd service below are part of the historical cutover, not prerequisites for routine image updates.

1. Close the release gates. Confirm the effective subnet route table has an active `com.amazonaws.ap-southeast-1.s3` prefix-list route to the intended Gateway Endpoint, obtain five-minute CPU credit balance/usage around representative traffic, review remaining CVEs, and verify normal write contracts in isolated staging. Record the old API/Nginx PIDs, OOM counter, available RAM, current port bindings, ECR digests, host HTTPS results and the production latency baseline. Keep the existing static release, venv and `macket-api.service` online.
2. When authorized, prepare an operator-only release manifest using `deploy/compose.web.yaml` with verified `@sha256:` references and the existing external runtime env file. Preserve the current read-only manifest. Set `MACKET_DB_READ_ONLY=off` and `MACKET_WEB_RESTART_POLICY=unless-stopped` for the release, then validate with `docker compose config --quiet` without printing resolved environment. Replace the canary in the **same** project/port using `docker compose up -d --no-build --pull never --wait backend-api frontend`. Check the database setting via SELECT and run loopback smoke checks. Leave production traffic on the systemd stack during this step. Avoid running three API instances simultaneously on the t3.micro.
3. Confirm `readlink -f /etc/nginx/sites-enabled/default` still identifies the audited site. Back up that file with ownership/mode intact to a root-only dated directory. Prepare and review a diff for both HTTPS vhosts. Send `/` and `/api/` through `proxy_pass http://127.0.0.1:8080;` with no appended URI, preserving the vhost values, TLS settings, redirect/certbot config, `Host`, `X-Real-IP`, `X-Forwarded-For` and `X-Forwarded-Proto`. Preserve any challenge or operational locations. Apply the reviewed config, run `sudo nginx -t` and execute `sudo systemctl reload nginx` only after syntax validation. Restore the backup immediately if syntax validation fails.
4. Check `/`, `/admin/`, `/api/health`, `/api/db-health` and products on both HTTPS vhosts. Verify the admin auth boundary, authenticated webhook `TEST`, loopback health and the old API on `127.0.0.1:8000`. Compare five-minute error/latency samples against the baseline. Roll back on any OOM increase, RAM below 150 MiB, container restart, unhealthy origin, failed auth/webhook probe or sustained 5xx/latency regression. Monitor at least 15 minutes and include several CloudWatch CPU-credit samples. Preserve old systemd and workers through this observation window.
5. To roll back, restore the backed-up site to the resolved original file path, run `sudo nginx -t`, then `sudo systemctl reload nginx`. Confirm both vhosts again serve the old static release and old API. After successful restoration, stop only the `macket-canary-011` Compose project if it caused the rollback. Keep both ECR versions available. No database schema change is introduced. Lambda, Scheduler and worker ownership are separate from this web cutover.

In the two existing HTTPS server blocks, use the following directives inside the reviewed `location /` and `location /api/` blocks. Keep any existing route-specific restrictions, Certbot locations and the port 80 redirects. TLS remains on host Nginx.

```nginx
proxy_pass http://127.0.0.1:8080;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

### Pre-cutover backup and recovery evidence

- Record RDS automated backup retention, `LatestRestorableTime` and the production DB identifier. At the release window, capture an approved manual snapshot and wait for `available`, then record the snapshot ID, completion time, encryption key access and recovery owner. Retrieve metadata without recording DB credentials. The audit identity was denied `rds:DescribeDBInstances`; an authorized operator must provide the live evidence and perform any snapshot or restore.
- Back up the active Nginx site, the exact old static release and systemd unit/configuration references, plus both Compose manifests and image digests. Preserve ownership, permissions and checksums. Keep runtime credentials in the approved restricted location, outside Git and deployment logs. Leave the old backend and static release in place for traffic-only rollback.
- The staging drill created a custom `pg_dump` with a PostgreSQL 18.3 client and restored to a separate staging DB with `pg_restore --exit-on-error`. Verified matching write-path counts and schema constraints. For production disaster recovery, restore the verified snapshot or PITR point to a **new isolated RDS instance**, verify TLS/schema and reconcile transactions after the restore point before any separately approved connection switch. A web rollback does not restore RDS or discard newly committed transactions.

### Restart behavior

EC2 `docker.service` and `containerd.service` are enabled. The initial read-only canary used `restart: no`; production uses `unless-stopped` for both services. Docker Engine restarted a disposable process that exited after 12 seconds using that policy. During a reboot, eligible existing containers restart when Docker starts. Compose `depends_on` gates `compose up`; Docker Engine does not replay Compose startup order on daemon restart. Allow a brief readiness window while the API becomes healthy and keep the old Nginx config ready for restoration. If the project has been manually stopped or removed, use the approved `compose up` command. No production reboot or daemon restart was performed.

## Pre-cutover load check

`tests/canary_load.py` compares `127.0.0.1:8000` directly with the actual canary path through its inner Nginx on `127.0.0.1:8080`. It uses 12-second phases at 1, 3 and 6 requests/sec per target, one target at a time, with a 50/50 mix of GET health and GET products. It checks RAM, OOM, legacy PID/HTTPS health and container restart counters while running. Percentiles use successful response times and include reading the response. This short test is a comparison at light load, with normal traffic and the DB shared by both targets. It does not establish production capacity.

The 2026-11-26 run completed 120 requests per target with zero errors. Host RAM stayed above 252 MiB and both canary restart counters plus the host OOM counter remained zero. See the report for per-phase latency. `cloudwatch:GetMetricStatistics` was denied for both available identities, so sustained credit behavior remains unverified.

## Security review for `0.1.1-ec2-parity`

The Backend actually loads OpenSSL 3.5.9. At this deployment the container accepts plain HTTP only from the inner Nginx and has outbound HTTPS and PostgreSQL TLS. Source and port inspection did not identify a QUIC/DTLS listener or a specialized caller for the OpenSSL features listed below. These reachability assessments apply to the reviewed routes and configuration. Track the Debian backport and rerun ECR scanning and regression before deploying any patched digest.

| Findings | Observed exposure and controls |
|---|---|
| OpenSSL QUIC/DTLS `CVE-2026-95691`, `107494`, `124709`, `84785`, `88822`, `95690` (all `CVE-2026` IDs) | Loopback publication is TCP only. The backend uses ASGI HTTP, HTTPS clients and PostgreSQL over TCP. Preserve this binding and avoid enabling QUIC/DTLS in this backend release. |
| OpenSSL CMS/PEM/DANE/Suite B `CVE-2026-107496`, `121482`, `107493`, `84786`, `35190` | No route accepts CMS documents, caller-supplied PEM stacks or custom TLS flags. Preserve trusted, operator-managed TLS material and the outer Nginx boundary. Normal client TLS remains in use. |
| OpenSSL AES-GCM-SIV and encoding `CVE-2026-88823`, `95692`, `121481` | Application credentials use Fernet, and inspected routes do not expose AES-GCM-SIV operations or unbounded native OpenSSL base64 calls. Preserve web request-size limits. |
| dpkg `CVE-2026-91094` | The finding concerns unpacking untrusted Debian source packages. The container runs Uvicorn as UID 10001 and does not process packages at runtime. Restrict image builds to the approved apt repositories. |
| util-linux `CVE-2026-78410`, SQLite `CVE-2026-119373`, `119374`, `119379`, glibc `CVE-2026-84243` | Preserve non-root, `no-new-privileges`, no privileged mounts or Docker socket, and `LANG=C.UTF-8`. Backend uses PostgreSQL and has no FTS5/changeset route. These Debian advisories remain open even when the ECR scan does not list them. |
| Bundled Kerberos in `psycopg-binary` | No KDC/kadmind service. Wheel library version and client GSS-RPC applicability are unverified. Keep the existing RDS TLS/auth configuration and track wheel advisory evidence separately. |

Sources: [OpenSSL advisories](https://openssl-library.org/news/vulnerabilities-3.5/), [Debian OpenSSL](https://security-tracker.debian.org/tracker/source-package/openssl), [Debian dpkg](https://security-tracker.debian.org/tracker/CVE-2026-91094), [Debian util-linux](https://security-tracker.debian.org/tracker/CVE-2026-78410), [Debian SQLite](https://security-tracker.debian.org/tracker/source-package/sqlite3), [Debian glibc](https://security-tracker.debian.org/tracker/CVE-2026-84243).

## Isolated smoke test

On Windows PowerShell, point `MACKET_RUNTIME_ENV` at `tests/container.env.example` and use the candidate image tags. Use a unique project name and an unused port. The override sets `internal: true` for the test bridge; the test client runs inside the backend container.

```powershell
$env:MACKET_RUNTIME_ENV = Join-Path $PWD 'tests/container.env.example'
$env:MACKET_FRONTEND_PORT = '18080'
$composeArgs = @('-p','macket-container-test','-f','compose.yaml','-f','tests/compose.isolated.yaml')
docker compose @composeArgs config --quiet
docker compose @composeArgs build backend-api frontend
try {
  docker compose @composeArgs up --no-build --pull never --wait backend-api frontend
  if ($LASTEXITCODE -ne 0) { throw 'Startup failed' }
  Get-Content -Raw tests/container_smoke.py | docker compose @composeArgs exec -T backend-api python -
  if ($LASTEXITCODE -ne 0) { throw 'Smoke test failed' }
} finally {
  docker compose @composeArgs down
}
```

## Isolated write and restore test

`tests/compose.writes.yaml` uses the exact web image tags, an internal Docker network with no published ports, synthetic credentials and a temporary PostgreSQL 18.3 database with TLS. `tests/staging_schema.sql` contains the 14 application write-path table definitions and indexes obtained from read-only catalog metadata. It excludes legacy tables outside the test and contains no production rows. The runner refuses to start unless its DB values identify the staging project and IMDS is disabled. Apify, OpenAI, S3, Scheduler and token estimation are mocked only where required by the integration tests.

```powershell
$stage = @('-p','macket-write-test','-f','tests/compose.writes.yaml')
docker pull postgres:18.3-bookworm
try {
  docker compose @stage up -d --no-build --pull never --wait
  if ($LASTEXITCODE -ne 0) { throw 'Staging startup failed' }
  Get-Content -Raw tests/staging_writes.py | docker compose @stage exec -T backend-api python -B -
  if ($LASTEXITCODE -ne 0) { throw 'Staging writes failed' }
  docker compose @stage exec -T staging-db bash -ec 'umask 077; pg_dump -U staging -Fc -f /tmp/macket-fixture.dump macket_staging; createdb -U staging macket_staging_restore; pg_restore -U staging --exit-on-error -d macket_staging_restore /tmp/macket-fixture.dump'
  if ($LASTEXITCODE -ne 0) { throw 'Staging restore failed' }
} finally {
  docker compose @stage down
}
```
