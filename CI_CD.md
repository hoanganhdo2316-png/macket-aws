# Macket web CI/CD preparation

Both workflows are manual dispatch and gated by repository variables. Leave the variables unset until approved. The workflows cover the web Backend and Frontend. They have no Lambda, Scheduler, database migration, worker, CloudFront or Nginx host deployment step.

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

The EC2 role read `MacketWebRelease` version `1` in `ap-southeast-1`. Status is `Active`, default/latest are both `1`, and YAML matches `deploy/ssm-web-release.yaml` after normalizing comments, line endings and outer whitespace. AWS reports SHA-256 `ad5c275b2d06dec78171c386ab5c1fdde2995cb7fea127d3284b9db94288ab11`. SSM Agent `3.3.4793.0` was verified active via SSH. Fleet Manager `Online` was reported by the operator, and both audit identities were denied `ssm:DescribeInstanceInformation`.

The reviewed `deploy/deploy_web.py` is installed at `/opt/macket-deploy/deploy_web.py`, SHA-256 `8a9db901d071051ef5f8bbff8732b4457dc3bc252ee5390b75c52abace4e8b7c`. Directory and script are `root:root`, with modes `0700` and `0600` respectively. SSM invokes the script via `/usr/bin/python3`. The manifest is root-owned and mode `0600`. The read-only preflight verified the configured digests match the two active containers and their cached linux/amd64 images, both services are healthy without restarts, and HTTP/HTTPS smoke checks passed. Keep previous release digests retained in ECR and cached on the host for rollback.

## Isolated verification before enabling CD

1. After separate approval, dispatch `verify-aws-oidc.yml` from `main`. Its two independent jobs bind to the real `ecr-publish` and `production` environments. Each requests `id-token: write`, assumes its environment role with an STS-only session policy, and verifies the account and full assumed-role ARN using `aws sts get-caller-identity`. Confirm both jobs appear under **Review deployments** before the independent reviewer approves them. GitHub labels the button **Approve and deploy** for environment review, including this STS-only workflow. Check each job for its PASS line. This verification does not call ECR or SSM and does not use the release enablement variables.
2. Use an existing nonproduction managed node only if one is available under an already-authorized operator identity. Use a fixture with its own Compose project, local mock endpoints, isolated data and known compatible test images. The deployed production script uses fixed paths and origins. Use a staging-only copy wired to the fixture and review that diff before running the Command document there. Exercise valid component/digest forwarding, an invalid parameter, a healthy one-service swap, a health failure with rollback, peer container ID stability and restart/OOM checks. Capture the Command ID and terminal status. A policy granting the deploy role only the production target stays scoped to that target.
3. When a staging node is unavailable, run `python -B -m unittest discover -s tests -p test_ci_deploy_web.py -v` and keep the cloud SSM delivery and real rollback checks pending. The four local tests passed, including simulated rollback. Treat hard process or host termination during a swap as a manual recovery case using the saved Compose backup. Keep CD disabled until an existing staging target can be used and an operator verifies the rollback.

## Backend security gate

Trivy 0.76.2 reported 53 High rows, no Critical rows and 13 distinct CVEs on the linux/amd64 Backend CI candidate. The table covers the Debian OS findings on that image. On 2026-11-26 the Debian tracker showed these open in Trixie. Perl was marked postponed. Assess reachability separately for each candidate digest. Image inspection confirmed Python loads system OpenSSL 3.5.9, the psycopg binary wheel separately loads bundled OpenSSL 3.5.8, and Python SQLite 3.46.1 has both FTS5 and SESSION enabled. The production database is PostgreSQL. A source search found no Backend references to the affected tools or SQLite. That search alone cannot establish absence from dependencies or runtime.

| CVE | Rows | Image-specific verification required before considering an exception |
|---|---:|---|
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | 9 | Verify the non-root service cannot perform privileged mounts or reach mount hooks. |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | 9 | Verify no privileged `nsenter` or cgroup-join path in the service. |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | 9 | Check for delegated mounts and fstab entries using `X-mount.subdir`. |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | 9 | Check restricted bind mounts, SUID behavior and writable mount sources. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | 1 | Trace privileged pathname-based ACL operations on user-influenced paths. |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | 4 | `infocmp` is present. Verify it never processes user-controlled terminfo. |
| [CVE-2026-119373](https://security-tracker.debian.org/tracker/CVE-2026-119373) | 1 | Check for a dependency path that runs FTS5 prefix queries against attacker-influenced indexed data. |
| [CVE-2026-119374](https://security-tracker.debian.org/tracker/CVE-2026-119374) | 1 | Check handling of external SQLite files and FTS5 secure-delete. |
| [CVE-2026-119379](https://security-tracker.debian.org/tracker/CVE-2026-119379) | 1 | Check handling of external SQLite session changesets. |
| [CVE-2026-107494](https://security-tracker.debian.org/tracker/CVE-2026-107494) | 3 | Check inbound and outbound OpenSSL QUIC exposure. Identify system and bundled versions separately. |
| [CVE-2026-124709](https://security-tracker.debian.org/tracker/CVE-2026-124709) | 3 | Verify the Backend does not act as an OpenSSL QUIC server. Check the HTTPS terminator separately if it enables HTTP/3. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | 2 | `systemd-homed` was absent from the candidate PATH. Verify service/binary absence and lack of host IPC. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | 1 | `Archive::Tar` could not be loaded from the candidate's default Perl module path. Confirm the module is absent from deployed paths and Perl does not handle external archives. |

Use a patched Trixie base or system package when available. Rebuild linux/amd64, run isolated Backend regression including PostgreSQL TLS and writes, and rescan the exact resulting image. Update the psycopg wheel only for a confirmed bundled-library fix with regression evidence. For an unfixed CVE, require package-specific reachability evidence, compensating controls, an accountable reviewer and an expiry with recheck criteria. Only after approval use a Backend-specific, narrowly scoped Trivy exception or validated VEX statement. Keep the original unfiltered scan result and fail the gate on every unapproved High or Critical finding. No exceptions are active in this configuration.

References: [GitHub OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws), [environment protection rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments), [ECR push permissions](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html), [SSM IAM actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ssm.html), [SSM document parameter handling](https://docs.aws.amazon.com/systems-manager/latest/userguide/documents-schemas-features.html).
