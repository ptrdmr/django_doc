# AWS Deployment (EC2) — Day 1 Setup (Sandbox)

This guide documents the **exact AWS setup steps** used to stand up a first-pass EC2 sandbox for this project. It is intentionally “small and simple” while we’re still actively developing.

> **Security note**: Do **not** paste secrets, account IDs, IPs, or key material into docs. Keep this guide generic and store secrets only in your password manager / `.env` (never committed).

---

## Scope / What we did today

- **Secured AWS account** (MFA, non-root admin user)
- **Added billing guardrails** (Budgets + anomaly alerts)
- **Launched an EC2 instance** (Amazon Linux 2023, small sandbox)
- **SSH’d from Windows** using a key pair
- **Installed Docker + Docker Compose + Buildx**
- **Pulled private GitHub repo** using a **deploy key**
- **Started the Docker Compose stack** and documented issues/fixes encountered

---

## 1) AWS Account hardening (do this first)

### Root account
- **Enable MFA** for the root user
- **Do not** use root for daily work

### Create an IAM admin user
- Create an IAM user (example: `peter_admin`)
- Attach policy: **`AdministratorAccess`**
- Enable **MFA** for that IAM user
- Use this IAM user for all day-to-day AWS console work

---

## 2) Billing guardrails (free tier ≠ free forever)

### Budget (monthly)
- Create a **Monthly cost budget** (example: `$10`)
- Add email notifications (80% and 100% are good defaults)

### Cost Anomaly Detection (real-time spikes)
AWS Cost Anomaly Detection is useful but may require **~24 hours** before cost data is fully available.

We configured:
- **Monitor**: overall cost monitor (Managed by AWS)
- **Alert subscription**: “Individual alerts” with a threshold (example: `$2 above expected spend`)

#### SNS topic (for individual alerts)
When “Individual alerts” is selected, AWS requires an SNS topic ARN.

- Create an SNS **Standard** topic (example name: `cost-anomaly-alerts`)
- Add an **Email subscription**
- Click the confirmation link AWS emails you (subscription must be **Confirmed**)
- Use the SNS topic ARN in the anomaly alert subscription

---

## 3) EC2 sandbox instance (Amazon Linux 2023)

### Instance configuration (as used)
- **AMI**: Amazon Linux 2023
- **Instance type**: `t3.micro` (for learning only; see performance note below)
- **Storage**: gp3, **30 GiB**, **Encrypted**
- **Key pair**: downloaded once as a `.pem` file (store securely)

### Security group (firewall)
Keep it minimal:
- **SSH (22)**: **My IP** only
- **HTTP (80)**: open to the internet for testing (later you can lock down or put behind a load balancer)
- **HTTPS (443)**: defer until TLS is set up

> For dev-compose testing, you may temporarily need **8000** open (preferably to **My IP** only). Production should terminate TLS on 443 and serve on 80/443 only.

### Why `t3.micro` got flaky
This app’s full dev stack is heavy for a micro instance:
- Postgres + Redis + Django + Celery worker + Celery beat + Flower

When CPU credits run low, the instance can appear “up” but become unresponsive to SSH handshakes.

**Recommended fix**:
- Stop the instance
- Resize to **`t3.small`**
- Start again

---

## 4) SSH from Windows (PowerShell)

From Windows PowerShell:

```powershell
ssh -i "$env:USERPROFILE\Downloads\YOUR_KEY_PAIR.pem" ec2-user@YOUR_PUBLIC_IPV4
```

Notes:
- `ec2-user` is the default username for Amazon Linux.
- The first time, SSH will ask to trust the host fingerprint (answer `yes`).

If you see `identity file ... type -1` in `ssh -vvv` output, Windows OpenSSH may be failing to parse the key. A quick remediation is:

```powershell
ssh-keygen -p -m PEM -f "$env:USERPROFILE\Downloads\YOUR_KEY_PAIR.pem"
```

---

## 5) Install Docker + Git on the instance

Run on the EC2 box:

```bash
sudo dnf update -y
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
exit
```

SSH back in and verify Docker works without sudo:

```bash
docker ps
```

---

## 6) Install Docker Compose (v2) on Amazon Linux 2023

The `docker-compose-plugin` package may not exist in the default AL2023 repos, so we installed Compose as a Docker CLI plugin:

```bash
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

docker compose version
```

---

## 7) Install Docker Buildx (required for compose builds)

We hit:
- `compose build requires buildx 0.17 or later`

The initial “latest” URL returned a 9-byte `Not Found` file, so we installed Buildx using the release tag and the user plugin path:

```bash
mkdir -p ~/.docker/cli-plugins

TAG="$(curl -s https://api.github.com/repos/docker/buildx/releases/latest \
  | grep -m1 '"tag_name"' \
  | sed -E 's/.*"([^"]+)".*/\1/')"
echo "Latest buildx tag: $TAG"

curl -SL "https://github.com/docker/buildx/releases/download/${TAG}/buildx-${TAG}.linux-amd64" \
  -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx

docker buildx version
```

---

## 8) Pull private GitHub repo using a Deploy Key

On the EC2 box, generate an SSH deploy key:

```bash
ssh-keygen -t ed25519 -C "ec2-deploy" -f ~/.ssh/ec2_deploy -N ""
cat ~/.ssh/ec2_deploy.pub
```

In GitHub:
- Repo → **Settings** → **Deploy keys** → **Add deploy key**
- Paste the **single-line** public key that starts with `ssh-ed25519` and ends with the comment (e.g., `ec2-deploy`)
- Leave **write access unchecked** (read-only)

Clone using that deploy key:

```bash
GIT_SSH_COMMAND='ssh -i ~/.ssh/ec2_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new' \
git clone git@github.com:OWNER/REPO.git
```

---

## 9) Run the Docker Compose stack (development compose)

For a first sandbox bring-up we used development compose:

```bash
cd REPO
docker compose -f docker-compose.yml up -d --build
docker ps
```

### Expected warnings (ok for sandbox)
If you see warnings like `The "OPENAI_API_KEY" variable is not set`, that’s expected until you create a server-side `.env` file.

---

## 10) Troubleshooting: Django log file permission error

We hit an application crash loop:
- `PermissionError: [Errno 13] Permission denied: '/app/logs/meddocparser.log'`

Cause:
- Containers run as non-root user (`uid=999(django)`), but the named volume mounted at `/app/logs` was owned by root.

Fix:
1) Stop compose
2) Determine container UID/GID
3) `chown` the named volumes to that UID/GID

Example:

```bash
docker compose -f docker-compose.yml down
docker run --rm django_doc-web sh -lc 'id'

# Replace 999:999 with the uid/gid from the id command
docker run --rm -v django_doc_logs_volume:/vol alpine sh -lc 'chown -R 999:999 /vol && ls -ld /vol'
docker run --rm -v django_doc_media_volume:/vol alpine sh -lc 'chown -R 999:999 /vol && ls -ld /vol'

docker compose -f docker-compose.yml up -d --build
```

---

## 11) Next steps (when ready)

- Decide whether this EC2 box is:
  - **Sandbox only** (recommended while still developing), or
  - **Production path** (requires TLS, secrets management, hardened networking, backups, and likely managed DB/Redis)
- For production:
  - Prefer **RDS** for Postgres and **ElastiCache** for Redis
  - Move containers to **ECS/Fargate** (or similar) rather than running everything on one VM

---

*Updated: 2025-12-20 23:19:01 | Added AWS account setup, billing guardrails, EC2 sandbox bring-up, and troubleshooting log for Docker Compose on Amazon Linux 2023*

