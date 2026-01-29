# AWS EC2 Deployment Troubleshooting Log

**Purpose**: Document all issues encountered during first AWS EC2 deployment and their solutions for future reference.

**Environment**: Amazon Linux 2023, t3.small, Docker Compose development stack

**Deployment Date**: December 20, 2025 - January 5, 2026

---

## Issue 1: Docker Compose Plugin Not Available in Amazon Linux 2023 Repos

### Problem
```bash
sudo dnf install -y docker-compose-plugin
# Error: Unable to find a match: docker-compose-plugin
```

### Root Cause
Amazon Linux 2023's default repositories don't include the `docker-compose-plugin` package name.

### Solution
Install Docker Compose v2 manually as a CLI plugin:

```bash
mkdir -p ~/.docker/cli-plugins
COMPOSE_TAG=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep -m1 '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_TAG}/docker-compose-linux-x86_64" -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose

# Verify
docker compose version
```

**Status**: ✅ Fixed - Compose v5.0.1 installed successfully

---

## Issue 2: Docker Buildx Plugin Download Failed (9-byte "Not Found" File)

### Problem
```bash
sudo curl -SL https://github.com/docker/buildx/releases/latest/download/buildx-linux-amd64 ...
# Downloaded only 9 bytes containing "Not Found"

docker compose up --build
# Error: compose build requires buildx 0.17 or later
```

### Root Cause
The GitHub release URL redirected to a "Not Found" page instead of the binary.

### Solution
Download Buildx with version tag explicitly resolved:

```bash
mkdir -p ~/.docker/cli-plugins
BUILDX_TAG=$(curl -s https://api.github.com/repos/docker/buildx/releases/latest | grep -m1 '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
curl -SL "https://github.com/docker/buildx/releases/download/${BUILDX_TAG}/buildx-${BUILDX_TAG}.linux-amd64" -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx

# Verify
docker buildx version
```

**Status**: ✅ Fixed - Buildx v0.30.1 installed successfully

---

## Issue 3: Docker Volume Permission Errors (Container Running as Non-Root)

### Problem
```
web-1  | PermissionError: [Errno 13] Permission denied: '/app/logs/meddocparser.log'
# All Django/Celery containers in restart loop
```

### Root Cause
- Dockerfile creates and runs as non-root user `django` (UID 999, GID 999)
- Docker named volumes (`logs_volume`, `media_volume`) created with root ownership
- Django can't write to `/app/logs/` or `/app/media/`

### Solution
Fix volume ownership before starting containers:

```bash
# Build image first to confirm UID/GID
docker compose build web
docker run --rm django_doc-web id
# Output: uid=999(django) gid=999(django)

# Fix volume permissions
docker run --rm -v django_doc_logs_volume:/vol alpine chown -R 999:999 /vol
docker run --rm -v django_doc_media_volume:/vol alpine chown -R 999:999 /vol

# Now start containers
docker compose up -d
```

**Status**: ✅ Fixed - Containers run stable after volume permission fix

---

## Issue 4: t3.micro Instance Completely Overloaded

### Problem
- EC2 t3.micro instance (1 vCPU, 1 GB RAM) became completely unresponsive
- SSH connections hung after "Connection established"
- Instance showed healthy in AWS console but couldn't actually connect

### Root Cause
Running 6 containers simultaneously on t3.micro:
- **Postgres**: ~150 MB RAM
- **Redis**: ~75 MB RAM  
- **Django web** (runserver): ~350 MB RAM
- **Celery worker**: ~350 MB RAM
- **Celery beat**: ~250 MB RAM
- **Flower**: ~150 MB RAM

**Total**: ~1.3-1.5 GB RAM on a 1 GB instance, causing:
- Linux kernel started swapping (using disk as RAM)
- CPU credits exhausted during `docker compose up --build`
- System became glacially slow, including SSH daemon

### Solution
Upgraded to **t3.small** (2 vCPU, 2 GB RAM):

1. Terminated old t3.micro instance
2. Launched new t3.small with same configuration
3. Re-ran setup scripts
4. All containers ran smoothly with room to spare

**Cost Impact**: ~$0.023/hour (~$17/month if running 24/7, or ~$5-10/month if stopped when not in use)

**Status**: ✅ Fixed - t3.small handles full stack comfortably

---

## Issue 5: Django `DisallowedHost` Error Despite Correct `.env` Configuration

### Problem
```
DisallowedHost at /
Invalid HTTP_HOST header: '3.129.92.221:8000'. You may need to add '3.129.92.221' to ALLOWED_HOSTS.
```

Even after:
- Creating `.env` with correct `ALLOWED_HOSTS` value
- Adding `env_file: .env` to docker-compose.yml
- Restarting containers multiple times
- Verifying `decouple.config('ALLOWED_HOSTS')` read the correct value

Django still showed old hardcoded value: `['localhost', '127.0.0.1', '0.0.0.0', 'moritrac.ngrok.pizza']`

### Root Causes (Multiple Layers)

#### 5a. Hardcoded ALLOWED_HOSTS in development.py
**Original Code**:
```python
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']  # Hardcoded
ALLOWED_HOSTS.append('moritrac.ngrok.pizza')  # Hardcoded
```

Django was **ignoring** the `.env` file entirely because `development.py` had hardcoded values.

**Fix**: Changed to read from environment:
```python
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,0.0.0.0').split(',')
```

#### 5b. .env Committed to Git BUT Also in .gitignore
- `.env` was committed to Git at some point in the past (so it exists in the repo)
- **Then** `.env` was added to `.gitignore` (blocking future changes)
- Result: Local edits to `.env` couldn't be committed
- EC2 clone had frozen version of `.env` from last successful commit

**Attempted Fix**: Force-add with `git add -f .env`
**Result**: GitHub **blocked push** due to API keys in `.env` (Secret Scanning protection)

#### 5c. Git Pull Authentication Failed on EC2
```
git@github.com: Permission denied (publickey)
```

The SSH deploy key created for initial `git clone` didn't work for subsequent `git pull` operations.

### Final Solution (Direct File Edit)
Since Git was completely blocked (can't push `.env` with secrets, can't pull due to auth), we **directly edited** `development.py` on EC2:

```bash
# Overwrote development.py with minimal working version
cat > meddocparser/settings/development.py << 'EOF'
from .base import *
from decouple import config

DEBUG = True
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,0.0.0.0').split(',')
# ... rest of minimal config
EOF

# Ensured .env had correct value
cat > .env << 'EOF'
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,3.129.92.221
...
EOF

docker compose down
docker compose up -d
```

**Status**: ✅ Fixed - App now accessible at `http://3.129.92.221:8000`

---

## Issue 6: GitHub Secret Scanning Blocked .env Push

### Problem
```
remote: - Push cannot contain secrets
remote:   —— Anthropic API Key ——
remote:   —— OpenAI API Key ——
error: failed to push some refs
```

### Root Cause
GitHub's push protection detected API keys in `.env` file and blocked the push for security.

### Proper Solution (For Future)
1. **Never commit `.env`** - ensure `.gitignore` blocks it from the start
2. **Use environment-specific configs**:
   - Local: `.env` (git-ignored)
   - EC2: Environment variables or server-specific `.env.production` (not in Git)
   - Production: AWS Secrets Manager, Parameter Store, or ECS/Kubernetes secrets

3. **Rotate exposed API keys** - Any keys committed to Git history should be rotated

### Proper Solution (Applied January 2026)
Used `git-filter-repo` to completely remove `.env` from all Git history:

```bash
# Backup .env locally
cp .env .env.backup

# Remove from all history
pip install git-filter-repo
git filter-repo --path .env --invert-paths --force

# Re-add remote and force push clean history
git remote add origin https://github.com/ptrdmr/django_doc.git
git push --force --set-upstream origin master

# Restore local .env from backup
cp .env.backup .env
```

**Status**: ✅ Fixed - `.env` removed from entire Git history, push protection no longer blocks

---

## Lessons Learned

### 1. Instance Sizing Matters
- **t3.micro** (1 GB RAM) is insufficient for multi-container Django stack
- **t3.small** (2 GB RAM) is minimum recommended for dev/test

### 2. Docker Volume Permissions
- Always fix named volume permissions for non-root containers
- Do this **before** starting containers to avoid restart loops

### 3. Environment Configuration Best Practices
- `.env` files should **never** be committed to Git
- Use `env.example` as a template
- Each environment should have its own configuration method
- For EC2/production: use environment variables or secrets management

### 4. Docker Compose on Amazon Linux 2023
- Standard packages (`docker-compose-plugin`) not always available
- Manual installation of Compose and Buildx required
- Install to `~/.docker/cli-plugins/` for user-level access

### 5. Git Deploy Keys vs HTTPS
- Deploy keys work for initial `git clone`
- May not persist for `git pull` operations
- **HTTPS is simpler** - use `git remote set-url origin https://...` for EC2

### 6. CSP Headers Must Be Environment-Aware
- `upgrade-insecure-requests` in CSP forces browsers to use HTTPS
- Must be conditional on `DEBUG` setting, not hardcoded
- Check response headers with `curl -I` when debugging SSL issues

### 7. Removing Secrets from Git History
- Use `git-filter-repo` (not `git filter-branch`) - it's faster and safer
- Always backup files before rewriting history
- Force push required after rewrite: `git push --force`
- All clones must `git fetch --all && git reset --hard origin/master`

---

## Issue 7: Missing .env File on EC2 After Instance Restart

### Problem
After restarting EC2 instance, Celery worker and other containers showed unhealthy status with errors:
```
WARN[0000] The "ANTHROPIC_API_KEY" variable is not set. Defaulting to a blank string.
WARN[0000] The "OPENAI_API_KEY" variable is not set. Defaulting to a blank string.
```

Containers were running but had no API keys to process documents.

### Root Cause
- `.env` file was git-ignored (correctly)
- EC2 clone from GitHub didn't include `.env`
- Containers started but couldn't access AI services

### Solution
Created `.env` file manually on EC2 with proper permissions:

```bash
cd django_doc

# Create .env with all required settings
cat > .env << 'EOF'
SECRET_KEY=...
DJANGO_CRYPTOGRAPHY_SALT=...
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,3.18.45.181
DB_ENGINE=postgresql
DB_NAME=meddocparser
DB_USER=postgres
DB_PASSWORD=admin
DB_HOST=db
DB_PORT=5432
REDIS_URL=redis://:redis123@redis:6379/0
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-proj-...
PERPLEXITY_API_KEY=pplx-...
AI_MODEL_PRIMARY=claude-sonnet-4-5-20250929
AI_MODEL_FALLBACK=gpt-4o-mini
EOF

# Set proper permissions (readable by container)
chmod 644 .env

# Restart containers
docker compose down
docker compose up -d
```

**Status**: ✅ Fixed - Containers now have access to API keys

---

## Issue 8: Celery Broker Using localhost Instead of Docker Redis Container

### Problem
Celery worker couldn't connect to Redis:
```
Error 99 connecting to localhost:6379. Cannot assign requested address.
```

Web container could read `.env` but Celery was still trying `localhost:6379` instead of `redis:6379`.

### Root Cause
`meddocparser/settings/development.py` had:
```python
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
```

The `.env` file had `REDIS_URL=redis://:redis123@redis:6379/0` (correct) but Celery was using separate env vars that defaulted to `localhost`.

### Solution
Changed `development.py` to use the existing `REDIS_URL`:

```python
# Use REDIS_URL from base.py instead of separate config vars
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
```

Restarted containers:
```bash
docker compose down
docker compose up -d
```

**Status**: ✅ Fixed - Celery now connects to `redis:6379` correctly

---

## Issue 9: Instructor Library Failing to Patch Anthropic Client

### Problem
Celery worker logs showed:
```
WARNING: Could not patch Anthropic client with instructor: 'Anthropic' object has no attribute 'chat', using manual JSON parsing
```

This caused Claude to use fragile manual JSON parsing, leading to syntax errors:
```
Claude response is not valid JSON: Expecting ',' delimiter: line 492 column 6 (char 19234)
```

Banner Health lab documents (with hundreds of test results) consistently failed with JSON parsing errors.

### Root Cause
Incorrect instructor patching syntax in `apps/documents/services/ai_extraction.py`:
```python
# WRONG - doesn't work with Anthropic
anthropic_client = instructor.patch(anthropic_client)
```

Instructor's `patch()` method is for OpenAI. Anthropic requires `from_anthropic()`.

### Solution
Fixed the patching code:

```python
# CORRECT - proper Anthropic patching
from instructor import from_anthropic
anthropic_client = from_anthropic(anthropic_client)
```

Restarted worker:
```bash
docker compose restart celery_worker
```

Verified fix:
```bash
docker compose logs celery_worker | grep instructor
# Output: "Anthropic Claude client patched with instructor for Pydantic support"
```

**Status**: ✅ Fixed - Claude now properly validates responses with Pydantic models, eliminating JSON syntax errors

---

## Issue 10: Large Medical Documents Overwhelming t3.small Instance

### Problem
- Document 6 (729KB "MICHAEL SIMS BANNER VISIT" PDF) got stuck in "Extracting text from PDF" stage
- Processing lasted 19+ minutes (should take ~1 minute)
- Celery worker showed 4 failed attempts
- EC2 instance became completely unresponsive
- SSH connections timed out
- Had to force-stop instance from AWS Console

Memory usage before crash:
```
celery_worker: 573MB (30% of 2GB)
web: 250MB (13%)
db: 96MB (5%)
Total: ~920MB + processing overhead
```

### Root Cause
1. **No task timeout enforcement** - PDF extraction can run indefinitely
2. **Concurrent processing** - Multiple large documents processed simultaneously
3. **Insufficient RAM** - t3.small (2GB) struggles with complex PDF extraction + AI processing
4. **No retry backoff** - Failed documents immediately retry, compounding the problem

### Solution (Immediate)
Force-stopped instance and marked document 6 as failed:

```bash
# After instance reboot
cd django_doc
docker compose up -d db
docker compose exec -T db psql -U postgres -d meddocparser -c \
  "UPDATE documents SET status='failed', 
   error_message='PDF too complex - requires manual processing', 
   processing_started_at=NULL 
   WHERE id=6;"
```

### Solution (Long-term Options)

**Option A: Upgrade Instance Size**
- **t3.medium** (4GB RAM, 2 vCPU): ~$30/month
- **t3.large** (8GB RAM, 2 vCPU): ~$60/month
- Handles multiple concurrent document processing

**Option B: Configure Celery Limits** (keeping t3.small)
Add to `.env` or `base.py`:
```python
# Process one document at a time
CELERY_WORKER_CONCURRENCY = 1

# Strict task timeouts
CELERYD_TASK_TIME_LIMIT = 300  # 5 minutes hard limit
CELERYD_TASK_SOFT_TIME_LIMIT = 240  # 4 minutes soft limit

# Memory management
CELERY_WORKER_MAX_MEMORY_PER_CHILD = 500000  # 500MB per worker
```

**Option C: Implement Document Size Limits**
```python
# Reject PDFs larger than 5MB during upload
MAX_PDF_SIZE = 5 * 1024 * 1024  # 5MB
```

**Status**: ⚠️ Workaround applied - Document 6 marked as failed. Need to implement proper resource limits or upgrade instance.

---

## Issue 11: Static Files Failing with ERR_SSL_PROTOCOL_ERROR

### Problem
Browser tried to load all static files via HTTPS even though:
- Server was HTTP-only (no SSL certificate)
- `SECURE_SSL_REDIRECT = False` in Django settings
- Hard refresh + incognito mode didn't help

```
GET https://3.129.92.221:8000/static/css/base.css net::ERR_SSL_PROTOCOL_ERROR
```

Login page loaded but with no CSS styling.

### Root Cause
Custom `SecurityHeadersMiddleware` in `apps/core/middleware.py` had `upgrade-insecure-requests` hardcoded in the Content-Security-Policy header:

```python
csp_directives = [
    # ... other directives ...
    "upgrade-insecure-requests",  # This forces browser to use HTTPS
]
```

This CSP directive tells browsers to automatically upgrade all HTTP requests to HTTPS, regardless of Django's SSL settings.

### Solution
Made CSP `upgrade-insecure-requests` conditional on `DEBUG` setting:

```python
csp_directives = [
    "default-src 'self'",
    # ... other directives ...
    "base-uri 'self'",
]

# Only force HTTPS upgrade in production (DEBUG=False)
if not settings.DEBUG:
    csp_directives.append("upgrade-insecure-requests")
```

Verified fix:
```bash
curl -I http://3.129.92.221:8000/ | grep -i content-security-policy
# Output no longer contains "upgrade-insecure-requests"
```

**Status**: ✅ Fixed - Static files load over HTTP when DEBUG=True, HTTPS enforced when DEBUG=False

---

## Issue 12: EC2 Git Remote Using SSH Without Keys

### Problem
```bash
git fetch --all
# git@github.com: Permission denied (publickey).
# fatal: Could not read from remote repository.
```

### Root Cause
EC2 clone was using SSH remote (`git@github.com:...`) but had no SSH keys configured for GitHub.

### Solution
Switched to HTTPS remote:
```bash
git remote set-url origin https://github.com/ptrdmr/django_doc.git
git fetch --all
git reset --hard origin/master
```

**Status**: ✅ Fixed - EC2 now uses HTTPS for Git operations

---

## Current Deployment Status

✅ **Working**:
- AWS account configured with MFA and billing alerts
- EC2 t3.small instance running (3.129.92.221)
- Docker + Compose + Buildx installed
- Repository cloned and synchronized with GitHub (HTTPS remote)
- All containers running (web, db, redis, celery_worker, celery_beat)
- App accessible at `http://3.129.92.221:8000` with full CSS styling
- **Git history cleaned** - `.env` removed from all commits
- **CSP headers environment-aware** - static files load correctly over HTTP
- **Celery Redis connection fixed** (uses `redis:6379`)
- **Instructor patching working** (Pydantic validation enabled)
- **Superuser created and admin role assigned**

⚠️ **Known Issues**:
- Using development settings (DEBUG=True) in EC2 environment
- No SSL/TLS (HTTP only)
- Port 8000 exposed directly (not through nginx on port 80)
- No Celery task timeout limits (can overwhelm instance)
- No document size limits (large PDFs can crash worker)
- t3.small (2GB RAM) struggles with complex/large PDFs

📋 **Next Steps**:
- Rotate all API keys (Anthropic, OpenAI, Perplexity) - were exposed in Git history
- Implement Celery concurrency limits (`CELERY_WORKER_CONCURRENCY=1`)
- Add task timeout enforcement (`CELERYD_TASK_TIME_LIMIT=300`)
- Consider upgrading to t3.medium (4GB RAM) for better stability
- Configure nginx reverse proxy for port 80
- Add SSL/TLS certificates (Let's Encrypt)
- Switch to production Django settings (DEBUG=False)
- Implement proper secrets management (AWS Secrets Manager)

---

*Last updated: 2026-01-10 03:29:02 | Fixed CSP static files issue, cleaned Git history, added superuser*

