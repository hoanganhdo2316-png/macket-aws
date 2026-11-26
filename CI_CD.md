# Macket web CI/CD preparation

The web CI and deploy workflows are manual dispatch and gated by repository variables. Leave the variables unset until approved. The workflows cover the web Backend and Frontend. They have no Lambda, Scheduler, database migration, worker, CloudFront or Nginx host deployment step. The separate OIDC verification workflow is also manual and uses an STS-only session policy.

## Workflow design

- **`web-ci.yml`** selects only affected image components from a full ancestor SHA (or the previous commit). CI/shared Compose changes select both and documentation-only changes select neither. Supply the last tested release SHA as `base_sha` when promoting several commits. The plan scans Git history and checkout with Gitleaks. Linux/amd64 jobs build the selected component and test Backend against isolated PostgreSQL or Frontend against a local mock API, then run Trivy on the source dependency manifests and exact image. A failed scan or test blocks publish.
- The optional publish job downloads the tested image from the same run, obtains AWS credentials using GitHub OIDC, and pushes an immutable `<version>-<full Git SHA>` tag to the corresponding ECR repository. `ecr-publish` approval is separate from running CI. The job prints the ECR digest. Use a new version tag for a new publish. A tag is never repointed.
- **`web-deploy.yml`** accepts one component and its approved digest. The `production` environment and a concurrency group gate the SSM command. The approved SSM document accepts only an allowlisted component and a digest and invokes a fixed, root-owned script already installed on the host. It does not download code from GitHub. The script preserves the existing Compose manifest and runtime env, pulls via the EC2 role, recreates only the requested service and checks both containers, the host HTTPS origin and RAM/OOM. It restores the old manifest and image on a failed check. A single-host service replacement can cause a brief interruption during restart; schedule a release window.

## GitHub configuration

On 2026-11-26, GitHub API confirmed both environments restrict deployments to the `main` branch, list `hoanganhdo2316-png` as required reviewer, prevent self-review and disallow administrator bypass. The collaborator `nnsgenztaynguyen-ux` can dispatch an approved test while the owner acts as the independent reviewer. Keep passwords, SSH keys, `.env` and AWS access keys out of this public repository and workflow inputs.

GitHub API confirmed the following environment variables. The three repository enablement variables were unset at audit time.

| Environment | Variable | Value |
|---|---|---|
| `ecr-publish` | `MACKET_ECR_PUBLISH_ROLE_ARN` | `arn:aws:iam::393840684011:role/MacketGitHubECRPublishRole` |
| `production` | `MACKET_CD_ROLE_ARN` | `arn:aws:iam::393840684011:role/MacketGitHubDeployRole` |
| `production` | `MACKET_EC2_INSTANCE_ID` | `i-0c8a12e28de443f56` |
| `production` | `MACKET_SSM_DOCUMENT_VERSION` | `1` |

Keep repository variables `MACKET_CI_ENABLED`, `MACKET_ECR_PUBLISH_ENABLED` and `MACKET_CD_ENABLED` unset. After separate approval, the CI-only trial sets `MACKET_CI_ENABLED=true` and dispatches with publish unchecked. Enable publish only after OIDC validation and a passing security gate. Enable CD only after hosted OIDC, isolated SSM and rollback tests pass and the production release is separately approved.

## AWS permissions and preparation after approval

| Identity | Scope and actions |
|---|---|
| GitHub ECR publish role | `ecr:GetAuthorizationToken` on `*`. On repository ARNs for `macket-backend` and `macket-frontend` in `ap-southeast-1`: `ecr:BatchCheckLayerAvailability`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`, `ecr:PutImage`, `ecr:BatchGetImage`, `ecr:DescribeImages`. |
| GitHub deploy role | `ssm:SendCommand` against only the account-owned `MacketWebRelease` document ARN and the approved EC2 instance ARN. `ssm:GetCommandInvocation` on `*` for polling status. Restrict AWS region to `ap-southeast-1`. Keep document creation/update and the AWS-managed arbitrary-shell document outside this role. |
| EC2 instance role | Existing ECR pull (`GetAuthorizationToken`, `BatchGetImage`, `BatchCheckLayerAvailability`, `GetDownloadUrlForLayer`). Confirm managed-node registration and the IAM permissions and connectivity required for SSM Agent. This role still supplies existing application permissions. |

In IAM Console, verify the reported provider `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com` and the trust and permission policies of both roles. Neither audit identity had `iam:GetRole` or `iam:GetOpenIDConnectProvider`. Use exact `StringEquals` conditions for `token.actions.githubusercontent.com:aud` and `token.actions.githubusercontent.com:sub` with `sts:AssumeRoleWithWebIdentity`. GitHub API verified immutable subjects for this repository. The assignments are:

| Role | Immutable `sub` |
|---|---|
| `MacketGitHubECRPublishRole` | `repo:hoanganhdo2316-png@229678175/macket-aws@1461193837:environment:ecr-publish` |
| `MacketGitHubDeployRole` | `repo:hoanganhdo2316-png@229678175/macket-aws@1461193837:environment:production` |

### Verified OIDC and permission checks

[Run 45752876412](https://github.com/hoanganhdo2316-png/macket-aws/actions/runs/45752876412), attempt 1, succeeded on commit `e39e540ad2e35e2f93a47675cd270b8d7aa54b7e`. Both environment jobs waited for review. GitHub recorded approval for both from `hoanganhdo2316-png`, separate from initiating collaborator `nnsgenztaynguyen-ux`. Cloud STS logs confirmed the following:

| Environment | Account | STS assumed-role ARN |
|---|---|---|
| `ecr-publish` | `393840684011` | `arn:aws:sts::393840684011:assumed-role/MacketGitHubECRPublishRole/macket-oidc-45752876412-1` |
| `production` | `393840684011` | `arn:aws:sts::393840684011:assumed-role/MacketGitHubDeployRole/macket-oidc-45752876412-1` |

Operator-reported IAM Policy Simulator results:

| Role | Scenario | Result |
|---|---|---|
| ECR publish | `macket-backend` | 8 allowed, 0 denied |
| ECR publish | `macket-frontend` | 8 allowed, 0 denied |
| ECR publish | Lambda Collector repository | 1 allowed, 7 denied. Registry authentication is account-scoped. |
| Deploy | `MacketWebRelease` and the Macket EC2 instance in Singapore | 2 allowed, 0 denied |
| Deploy | `AWS-RunShellScript` | `SendCommand` denied, `GetCommandInvocation` allowed |

The separate [ECR read verification run 45757364339](https://github.com/hoanganhdo2316-png/macket-aws/actions/runs/45757364339) **PASS** on commit `758cbe307a315cadf7b76847ba1fe136582088a3`. GitHub recorded independent approval by `hoanganhdo2316-png` for `ecr-publish`. Logs show `GetAuthorizationToken` and all three repository read checks passed through the role's read-only session. Both `0.1.1-ec2-parity` tags resolved to OCI indexes, and the workflow read the corresponding linux/amd64 child manifests to check layer availability.

| Repository | Verified index digest | Live checks passed |
|---|---|---|
| `macket-backend` | `sha256:a47c1f2649a866abe6b3aac45767bd675ce63eaa755ef1ea86662cb2adbd5fb1` | `DescribeImages`, `BatchGetImage`, `BatchCheckLayerAvailability` |
| `macket-frontend` | `sha256:7ca48780b2463e79c3bf63c142e4dd1980754311496eb704dd804cb4708b523f` | `DescribeImages`, `BatchGetImage`, `BatchCheckLayerAvailability` |

The audit profile verified immutable tags and no repository-specific policy on both web repositories. Upload and `PutImage` remain simulation-only. The SSM simulation covers authorization for the tested inputs. Actual command delivery and agent behavior remain open.

The EC2 role read `MacketWebRelease` version `1` in `ap-southeast-1`. Status is `Active`, default/latest are both `1`, and YAML matches `deploy/ssm-web-release.yaml` after normalizing comments, line endings and outer whitespace. AWS reports SHA-256 `ad5c275b2d06dec78171c386ab5c1fdde2995cb7fea127d3284b9db94288ab11`. SSM Agent `3.3.4793.0` was verified active via SSH. Fleet Manager `Online` was reported by the operator, and both audit identities were denied `ssm:DescribeInstanceInformation`.

The reviewed `deploy/deploy_web.py` is installed at `/opt/macket-deploy/deploy_web.py`, SHA-256 `8a9db901d071051ef5f8bbff8732b4457dc3bc252ee5390b75c52abace4e8b7c`. Directory and script are `root:root`, with modes `0700` and `0600` respectively. SSM invokes the script via `/usr/bin/python3`. The manifest is root-owned and mode `0600`. The read-only preflight verified the configured digests match the two active containers and their cached linux/amd64 images, both services are healthy without restarts, and HTTP/HTTPS smoke checks passed. Keep previous release digests retained in ECR and cached on the host for rollback.

## Isolated verification before enabling CD

1. After separate approval, dispatch `verify-aws-oidc.yml` from `main`. Its two independent jobs bind to the real `ecr-publish` and `production` environments. Each requests `id-token: write`, assumes its environment role with an STS-only session policy, and verifies the account and full assumed-role ARN using `aws sts get-caller-identity`. Confirm both jobs appear under **Review deployments** before the independent reviewer approves them. GitHub labels the button **Approve and deploy** for environment review, including this STS-only workflow. Check each job for its PASS line. This verification does not call ECR or SSM and does not use the release enablement variables.
2. Run the rollback fixture on existing local Linux/Docker capacity first. Use a disposable environment with its own Docker daemon or Compose project, test data, mock health/TLS endpoints, and test images already present locally. Keep production credentials, manifest and Docker daemon out of the fixture. The production script uses fixed paths and origins. Use a staging-only copy with fixture paths, local image preparation and mock endpoints, keeping the swap, health and rollback logic intact. Test a healthy one-service replacement, then force a fixture health-check failure and verify the original manifest and image are restored, the peer container ID is stable, and restart/OOM checks behave as expected. Treat hard process or host termination during a swap as a manual recovery case using the saved Compose backup.
3. Local rollback **PASS** on Docker Desktop for Windows, Compose v5.7.0, project `macket-rollback-96761514b0`. Both services independently moved from cached `0.1.0` to `0.1.1-ec2-parity` digests. For each service, a Compose fixture override made the next replacement fail a real container health check. The script restored the prior manifest byte-for-byte, recreated only the target at its last healthy digest, and verified the peer was healthy with the same container ID throughout the tested checks. Docker and Compose calls were real. AWS auth and remote pull were replaced with validation of cached images, HTTP smoke used fixture endpoints, and Linux host metrics and root checks were simulated on Windows. The fixture used an internal network with no published ports or production settings and was removed after the test.
4. The saved reproduction is `python -B -m unittest discover -s tests -p windows_rollback_integration.py -v` from the repo root with PyYAML, local Docker Desktop, and both original ECR-tagged releases already cached. The original execution was retained as test evidence. The checked-in copy was syntax and discovery checked without repeating the Docker cases. Prior local command-wrapper and unit tests covered both valid components, invalid `worker`/`latest` inputs and simulated rollback.

### SSM end-to-end plan, pending approval

1. Prefer an existing nonproduction managed node in `ap-southeast-1` with an already-authorized operator identity. Confirm the exact target ID, agent Online status and absence of production credentials, data and endpoints. AWS lists no additional Run Command charge for managed EC2 instances. No suitable node has been confirmed.
2. If none is available, reuse an existing disposable Linux VM. Subject to approval, use a one-registration, short-lived hybrid activation with an already-approved activation role and a scoped operator identity. Hybrid Run Command is listed at USD 0.002 per invocation. Two accepted invocations would cost about USD 0.004 for Run Command alone. Deregister the fixture node and remove the activation after the test. If the existing role, operator access or isolated VM is unavailable, keep this check pending. [Hybrid activation](https://docs.aws.amazon.com/systems-manager/latest/userguide/activations.html) · [Systems Manager pricing](https://aws.amazon.com/systems-manager/pricing/)
3. Place only a reviewed fixture copy behind the document's fixed path on the test node. Pin `MacketWebRelease` version `1`. Submit one invalid parameter expecting validation rejection and no host-side change. Use accepted commands to prove a successful fixture-only replace and a staged health failure. Capture the command IDs, final invocation statuses, original digest restored after failure, and unchanged peer container ID. Verify that a rollback reports failure to SSM so a failed release cannot be mistaken for success.
4. Keep the production deploy role scoped to its current EC2 target. A run using the test-node identity covers SSM API validation, agent delivery, parameter interpolation and fixture rollback. The production target authorization remains simulator evidence, and EC2-role ECR pulls are a separate path. The production target, `production` environment and `MACKET_CD_ENABLED` stay out of the test.

### Frontend-only ECR publish trial

1. Use the manual `frontend-publish-test.yml` workflow from `main`. It builds only Frontend and targets the existing `macket-frontend` repository. The general Web CI change selector remains unchanged. The trial OIDC session limits every repository action to `macket-frontend` and uses the `ecr-publish` environment.
2. The workflow scans Git history and checkout with Gitleaks and requires Frontend smoke, source dependency scan, image-secret scan and the full High/Critical vulnerability gate. The build job uploads the exact linux/amd64 archive after checks pass. Publish downloads by artifact ID from the same run, verifies archive SHA-256, and checks the loaded image ID and platform. The historical local Frontend PASS remains recorded separately.
3. For the approved test window, set repository variables `MACKET_CI_ENABLED=true` and `MACKET_ECR_PUBLISH_ENABLED=true` before dispatch. Keep `MACKET_CD_ENABLED` unset. Once the build succeeds, approve only `ecr-publish` for this trial run. Publish uses the immutable tag `0.1.2-publish-test-<full Git SHA>`, refuses an existing tag and compares the push digest with the ECR tag lookup. Record the workflow ID, tag, digest, and ECR scan status and findings. A successful push proves `PutImage` and proves layer uploads only if ECR received new layers. Clear both enablement flags after the approved test window. The test tag is not a production release.

## Backend security gate

Trivy 0.76.2 reported 53 High rows, no Critical rows and 13 distinct CVEs on the linux/amd64 Backend CI candidate. The table covers the Debian OS findings on that image. On 2026-11-26 the Debian tracker showed all 13 open in Trixie, with Perl postponed. A fresh APT metadata query in a disposable candidate container showed candidate versions already installed for the seven affected package groups. Image inspection confirmed Python loads system OpenSSL 3.5.9, the psycopg binary wheel separately loads bundled OpenSSL 3.5.8, and Python SQLite 3.46.1 has both FTS5 and SESSION enabled. The production database is PostgreSQL. A source search found no Backend references to the affected tools or SQLite. That search alone cannot establish absence from dependencies or runtime.

The candidate runs as UID 10001 with zero effective capabilities under the tested Docker defaults, and its image contains no active fstab entries. The live Backend process also runs as UID 10001 with zero effective capabilities and `NoNewPrivs=1`. Its container uses private IPC, no mounts and unprivileged mode. EC2 had no UDP/443 listener at inspection time. These observations reduce the assessed exposure of the indicated paths. They do not cover outbound QUIC, container configuration drift, or code running in dependencies.

Follow-up inspection of the same CI image found no `aioquic`, `qh3` or `pycurl` packages and no overrides for `TERMINFO` or `TERMINFO_DIRS`. In the surveyed Python dependencies, direct SQLite imports were limited to SQLAlchemy's SQLite dialect. The configured application engine uses `postgresql+psycopg`. No `getfacl` or `setfacl` executable was on the candidate PATH. `bsdutils`, `util-linux`, `ncurses-bin` and `perl-base` are Debian Essential packages in this image, so manual removal is not part of the remediation plan. This evidence narrows the tests in the table. It does not justify accepting the findings without review.

This is a proposal for the inspected Backend CI image ID `sha256:e0cfbf31b29c6c3b5af9071342ff4635e0719209759df6424d0aaf99bd9757a3` and its required runtime configuration. Expiry dates below are maximum approval windows in UTC for this assessment. The exact candidate, compensating controls and accountable approver must be recorded before any exception takes effect.

| CVE | Debian scope and rows | Reachability evidence and release decision | Max expiry (UTC) |
|---|---|---|---|
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | util-linux family · 9 | **Conditional exception.** No active fstab entries or mounts, UID 10001, zero effective capabilities. Require `no-new-privileges` and no delegated mount helpers or elevated paths. | 2026-12-10 |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | util-linux family · 9 | **Conditional exception.** No host PID mode or mounts and no effective capabilities were observed. Require no privileged `nsenter` path or host cgroup access. | 2026-12-10 |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | util-linux family · 9 | **Conditional exception.** No active fstab or volume mounts. Recheck that the released deployment has no delegated mounts and no `X-mount.subdir` declaration. | 2026-12-10 |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | util-linux family · 9 | **Conditional exception.** Live `NoNewPrivs=1`, no mounts and no effective capabilities. Require the same controls and no authorized restricted bind mounts or writable source paths. | 2026-12-10 |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | libacl1 · 1 | **Block.** CLI tools were absent. Trace privileged pathname-based libacl operations on user-influenced paths before reconsidering. | — |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | ncurses family · 4 | **Block.** `infocmp` is present. Prove dependencies and subprocesses never invoke it with user-controlled terminfo or paths. | — |
| [CVE-2026-119373](https://security-tracker.debian.org/tracker/CVE-2026-119373) | libsqlite3-0 · 1 | **Block.** FTS5 compiled in. PostgreSQL is the default database, but dependency and ingestion tracing must rule out affected FTS5 queries against externally influenced indexed data. | — |
| [CVE-2026-119374](https://security-tracker.debian.org/tracker/CVE-2026-119374) | libsqlite3-0 · 1 | **Block.** FTS5 compiled in. Rule out external SQLite database inputs and FTS5 secure-delete across dependencies. | — |
| [CVE-2026-119379](https://security-tracker.debian.org/tracker/CVE-2026-119379) | libsqlite3-0 · 1 | **Block.** SESSION compiled in. Rule out accepting or applying SQLite session changesets. | — |
| [CVE-2026-107494](https://security-tracker.debian.org/tracker/CVE-2026-107494) | OpenSSL family · 3 | **Block.** No surveyed QUIC client installed. Outbound and inbound QUIC exposure of both loaded OpenSSL copies still needs confirmation. | — |
| [CVE-2026-124709](https://security-tracker.debian.org/tracker/CVE-2026-124709) | OpenSSL family · 3 | **Conditional exception.** Backend startup uses Uvicorn HTTP and host had no UDP/443 listener. Confirm the exact release has no OpenSSL QUIC server or exposed QUIC listener. Scope the exception to the reported Debian packages. Track the bundled wheel separately. | 2026-12-03 |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | libsystemd0, libudev1 · 2 | **Conditional exception.** No `systemd-homed` binary under candidate `/usr` or `/opt`; live IPC private and no mounts. Confirm no home service, host IPC or host socket in the release configuration. | 2026-12-10 |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | perl-base · 1 | **Conditional exception.** `Archive::Tar` failed to load and its module file was absent under candidate `/usr` and `/opt`. Verify the deployed Perl path and archive workflow cannot introduce this module. | 2026-12-10 |

The util-linux family here is `bsdutils`, `libblkid1`, `liblastlog2-2`, `libmount1`, `libsmartcols1`, `libuuid1`, `login`, `mount` and `util-linux`. The ncurses family is `libncursesw6`, `libtinfo6`, `ncurses-base` and `ncurses-bin`. The OpenSSL family is `libssl3t64`, `openssl` and `openssl-provider-legacy`.

Seven CVEs covering 42 rows are candidates for time-limited review. Even if all seven are approved, the remaining six CVEs covering 11 rows still block Backend. Use a patched Trixie base or package when available. Rebuild linux/amd64, run isolated Backend regression including PostgreSQL TLS and writes, and rescan that image. Update the psycopg wheel only for a confirmed bundled-library fix with regression evidence.

If authorized later, match exact CVE and approved versioned package PURLs from the raw scan, scoping any exception to the approved Backend image digest and runtime. Archive the unfiltered scan. Test that an unapproved package, expired exception, changed digest and any other High or Critical finding still fail CI. Revoke an exception at expiry, when a compatible fix becomes available or when an exposure control changes. No exceptions are active. [Trivy filtering and expiry](https://trivy.dev/docs/latest/configuration/filtering/)

References: [GitHub OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws), [environment protection rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments), [ECR push permissions](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html), [SSM IAM actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ssm.html), [SSM document parameter handling](https://docs.aws.amazon.com/systems-manager/latest/userguide/documents-schemas-features.html).
