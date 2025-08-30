#!/bin/bash
set -e

# Docker entrypoint script for Medical Document Parser
# This script handles initialization and startup tasks

echo "🏥 Medical Document Parser - Docker Entrypoint"
echo "=============================================="

# Function to wait for database to be ready
wait_for_db() {
    echo "⏳ Waiting for database to be ready..."
    while ! python manage.py check --database default; do
        echo "Database not ready yet. Retrying in 2 seconds..."
        sleep 2
    done
    echo "✅ Database is ready!"
}

# Function to wait for Redis to be ready
wait_for_redis() {
    echo "⏳ Waiting for Redis to be ready..."
    while ! python -c "import redis; r = redis.from_url('${REDIS_URL}'); r.ping()"; do
        echo "Redis not ready yet. Retrying in 2 seconds..."
        sleep 2
    done
    echo "✅ Redis is ready!"
}

# Function to run Django migrations
run_migrations() {
    echo "🔄 Running database migrations..."
    python manage.py migrate --noinput
    echo "✅ Migrations completed!"
}

# Function to collect static files
collect_static() {
    echo "📦 Collecting static files..."
    python manage.py collectstatic --noinput
    echo "✅ Static files collected!"
}

# Function to create superuser if needed
create_superuser() {
    if [ "$DJANGO_SUPERUSER_USERNAME" ] && [ "$DJANGO_SUPERUSER_EMAIL" ] && [ "$DJANGO_SUPERUSER_PASSWORD" ]; then
        echo "👤 Creating superuser..."
        python manage.py createsuperuser --noinput || echo "Superuser already exists"
        echo "✅ Superuser setup completed!"
    else
        echo "ℹ️ Superuser environment variables not set. Skipping superuser creation."
    fi
}

# Function to set up RBAC system for healthcare roles
setup_rbac_system() {
    echo "🔐 Setting up RBAC system..."
    
    # Set up role permissions
    echo "⚙️ Configuring healthcare role permissions..."
    python manage.py setup_role_permissions || echo "Role permissions setup failed"
    
    # Set up admin user with RBAC
    echo "👑 Setting up admin user with RBAC roles..."
    python manage.py setup_admin_user --from-env || echo "Admin user setup skipped"
    
    echo "✅ RBAC system setup completed!"
}

# Function to start the application
start_application() {
    echo "🚀 Starting application..."
    exec "$@"
}

# Main execution
case "$1" in
    "web")
        wait_for_db
        wait_for_redis
        run_migrations
        collect_static
        create_superuser
        setup_rbac_system
        start_application gunicorn --bind 0.0.0.0:8000 --workers 3 --timeout 120 meddocparser.wsgi:application
        ;;
    "worker")
        wait_for_db
        wait_for_redis
        start_application celery -A meddocparser worker --loglevel=info --queues=document_processing,fhir_processing
        ;;
    "beat")
        wait_for_db
        wait_for_redis
        start_application celery -A meddocparser beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
        ;;
    "flower")
        wait_for_redis
        start_application celery -A meddocparser flower --port=5555
        ;;
    "migrate")
        wait_for_db
        run_migrations
        ;;
    "collectstatic")
        collect_static
        ;;
    "createsuperuser")
        wait_for_db
        create_superuser
        ;;
    "test")
        wait_for_db
        start_application python manage.py test
        ;;
    *)
        echo "🔧 Running custom command: $@"
        start_application "$@"
        ;;
esac 