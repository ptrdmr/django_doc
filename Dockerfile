# Use Python 3.11-slim as base image for better security and smaller size
FROM python:3.11-slim AS base

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV DJANGO_SETTINGS_MODULE=meddocparser.settings.production

# Set work directory
WORKDIR /app

# Install system dependencies required for PostgreSQL, OCR, and other packages
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    python3-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*
# NOTE: tesseract-ocr and poppler-utils removed (Task 42.22) - OCR handled by AWS Textract

# Create non-root user for security (HIPAA best practice)
RUN groupadd -r django && useradd -r -g django django

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories and set ownership
RUN mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R django:django /app

# Collect static files (use development settings during build)
RUN python manage.py collectstatic --noinput --settings=meddocparser.settings.development

# Switch to non-root user
USER django

# Expose port 8000
EXPOSE 8000

# Health check for container
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/admin/ || exit 1

# Default command - can be overridden in docker-compose
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "meddocparser.wsgi:application"] 