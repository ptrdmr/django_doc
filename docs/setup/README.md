# ⚙️ Setup & Installation

## Quick Start (Docker - Recommended) 🚀

For experienced developers who just want to get the Django app running:

```bash
# Clone and navigate to project
git clone [repository-url]
cd doc2db_2025_django

# Start Docker containers (PostgreSQL + Django + Redis + Celery)
docker-compose up -d

# Verify everything is working
docker ps
curl http://localhost:8000

# Access the application
open http://localhost:8000  # Login/register to get started
```

**Services Available:**
- Django App: http://localhost:8000
- PostgreSQL: localhost:5432 (internal Docker network)
- Redis: localhost:6379
- Flower (Celery monitoring): http://localhost:5555

---

## Prerequisites

- **Python 3.12+** 
- **Git** for version control
- **Docker & Docker Compose** (optional but recommended)
- **PostgreSQL 15+** (production)
- **Redis** (caching and task queue)

## Quick Setup

### 1. Clone Repository
```bash
git clone [repository-url]
cd doc2db_2025_django
```

### 2. Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Configuration
```bash
# Copy environment template
cp env.example .env

# Edit .env with your settings
# Required variables:
# - SECRET_KEY
# - DJANGO_CRYPTOGRAPHY_SALT
# - Database settings (if using PostgreSQL)
# - Redis settings
```

### 5. Database Setup
```bash
# Using SQLite (development)
python manage.py migrate

# Using PostgreSQL (production)
# Set DB_ENGINE=postgresql in .env
python manage.py migrate
```

### 6. Create Superuser
```bash
python manage.py createsuperuser
```

### 7. Run Development Server
```bash
python manage.py runserver
```

Access at: http://localhost:8000

## Docker Setup (Recommended)

### Development Environment

**First-Time Setup:**
```bash
# Stop any existing containers
docker-compose down

# Remove any problematic volumes (if this is a fresh setup)
docker volume rm doc2db_2025_django_static_volume 2>/dev/null || true

# Build and start all services
docker-compose build
docker-compose up -d

# Verify everything is running
docker ps
```

**Daily Development:**
```bash
# Start the environment
docker-compose up -d

# Check logs if needed
docker logs doc2db_2025_django-web-1
```

**Troubleshooting Common Issues:**
```bash
# If static files have permission issues:
docker-compose down
docker volume rm doc2db_2025_django_static_volume
docker-compose build --no-cache
docker-compose up -d

# If database connection fails:
# Check that DB_ENGINE=postgresql in docker-compose.yml
# (Not django.db.backends.postgresql)
```

### Production Environment
```bash
# Use production configuration
docker-compose -f docker-compose.prod.yml up --build
```

## Dependencies Overview

### Core Django Packages (40+ total)
```
Django==5.2.3
djangorestframework==3.15.1
psycopg2-binary==2.9.10
celery==5.3.1
redis==5.0.0
```

### Security & HIPAA Compliance
```
django-allauth==64.2.1        # Enhanced authentication
django-otp==1.5.4             # Two-factor authentication
django-axes==7.0.0            # Failed login monitoring
django-ratelimit==4.1.0       # API rate limiting
django-cryptography==1.1      # Field encryption
argon2-cffi==23.1.0           # Secure password hashing
```

### FHIR & Medical Data
```
fhir.resources==7.1.0         # FHIR R4 resources
fhirclient==4.2.1             # FHIR client library
jsonschema==4.23.0            # JSON validation
```

### Document Processing
```
PyPDF2==3.0.1                 # PDF processing
python-magic==0.4.27          # File type detection
Pillow==10.4.0                # Image processing
python-docx==1.1.2            # Word documents
```

### Testing & Development
```
pytest==8.3.4                 # Testing framework
pytest-django==4.9.0          # Django test integration
factory-boy==3.3.1            # Test data generation
coverage==7.6.9               # Code coverage
django-debug-toolbar==5.2.0   # Development debugging
```

## Configuration Files

### Settings Structure
```
meddocparser/settings/
├── __init__.py
├── base.py          # Common settings
├── development.py   # Development overrides
└── production.py    # Production overrides
```

### Environment Variables
```bash
# Security
SECRET_KEY=your-secret-key
DJANGO_CRYPTOGRAPHY_SALT=your-encryption-salt

# Database
DB_ENGINE=sqlite  # or postgresql
DATABASE_URL=postgresql://user:pass@localhost/dbname

# Redis
REDIS_URL=redis://localhost:6379/0

# Email (production)
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email
EMAIL_HOST_PASSWORD=your-password
EMAIL_USE_TLS=True
```

## Verification

### Health Checks
```bash
# Django system check
python manage.py check

# Production deployment check
python manage.py check --deploy

# Test Celery
python manage.py test_celery
```

### Docker Health
```bash
# Check container status
docker ps

# View logs
docker-compose logs web
docker-compose logs db
docker-compose logs redis
```

## Troubleshooting

### Common Issues

**Missing packages after installation**
```bash
pip install -r requirements.txt --force-reinstall
```

**Database connection errors**
- Verify PostgreSQL is running
- Check DATABASE_URL in .env
- Ensure database exists

**Redis connection errors**
- Verify Redis is running
- Check REDIS_URL in .env
- Test connection: `redis-cli ping`

**Docker issues**
```bash
# Rebuild containers
docker-compose down
docker-compose up --build

# Clear volumes
docker-compose down -v
```

---

*Last updated with Task 1.8 completion - All HIPAA packages installed* 