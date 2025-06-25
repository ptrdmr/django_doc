# Docker Setup for Medical Document Parser

This directory contains Docker configuration files for the Medical Document Parser application.

## Quick Start (Development)

1. **Copy environment file:**
   ```bash
   cp env.example .env
   ```

2. **Start development environment:**
   ```bash
   docker-compose up --build
   ```

3. **Access the application:**
   - Web Application: http://localhost:8000
   - Celery Flower (monitoring): http://localhost:5555
   - PostgreSQL: localhost:5432
   - Redis: localhost:6379

## Production Deployment

1. **Set up environment variables:**
   ```bash
   # Copy and customize production environment
   cp env.example .env.prod
   
   # Edit .env.prod with production values:
   # - Strong passwords for DB_PASSWORD and REDIS_PASSWORD
   # - Proper SECRET_KEY
   # - Correct ALLOWED_HOSTS
   # - SSL certificate paths
   ```

2. **Deploy with production compose:**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d --build
   ```

## Services Overview

### Development (`docker-compose.yml`)
- **web**: Django application (port 8000)
- **db**: PostgreSQL database (port 5432)
- **redis**: Redis cache/broker (port 6379)
- **celery_worker**: Background task processor
- **celery_beat**: Scheduled task runner
- **flower**: Celery monitoring (port 5555)

### Production (`docker-compose.prod.yml`)
- Same services as development, plus:
- **nginx**: Reverse proxy with SSL (ports 80/443)
- Resource limits and replicas for scaling
- Enhanced security settings

## Environment Variables

Required environment variables (see `env.example`):

```bash
# Database
DB_NAME=meddocparser
DB_USER=postgres
DB_PASSWORD=your_secure_password

# Redis
REDIS_PASSWORD=your_redis_password

# Django (Production)
SECRET_KEY=your_very_long_secret_key
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DEBUG=0

# Superuser (Optional)
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@yourdomain.com
DJANGO_SUPERUSER_PASSWORD=secure_admin_password
```

## Useful Commands

### Development
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f web

# Run Django commands
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
docker-compose exec web python manage.py shell

# Run tests
docker-compose exec web python manage.py test

# Stop all services
docker-compose down
```

### Production
```bash
# Deploy
docker-compose -f docker-compose.prod.yml up -d --build

# Scale workers
docker-compose -f docker-compose.prod.yml up -d --scale celery_worker=4

# View production logs
docker-compose -f docker-compose.prod.yml logs -f

# Backup database
docker-compose -f docker-compose.prod.yml exec db pg_dump -U postgres meddocparser > backup.sql
```

## File Structure

```
docker/
├── README.md           # This file
├── postgres/
│   └── init.sql       # PostgreSQL initialization
├── nginx/             # Nginx configuration (production)
│   ├── nginx.conf
│   └── default.conf
└── ssl/               # SSL certificates (production)
```

## Health Checks

All services include health checks:
- **PostgreSQL**: `pg_isready` command
- **Redis**: `redis-cli ping` command
- **Django**: HTTP check on admin endpoint

## Volumes

Persistent data is stored in Docker volumes:
- `postgres_data`: Database files
- `redis_data`: Redis persistence
- `static_volume`: Django static files
- `media_volume`: User uploaded files
- `logs_volume`: Application logs

## Security Notes

For production deployment:
1. Use strong, unique passwords for all services
2. Configure SSL certificates in `docker/ssl/`
3. Set up proper firewall rules
4. Regularly update Docker images
5. Monitor logs for security events
6. Implement backup strategies for persistent volumes

## Troubleshooting

### Common Issues

1. **Port conflicts**: Change ports in docker-compose.yml if needed
2. **Permission issues**: Ensure Docker daemon is running with proper permissions
3. **Database connection**: Check that DB_HOST matches service name in docker-compose
4. **Redis connection**: Verify REDIS_URL format and password

### Logs
```bash
# View all logs
docker-compose logs

# View specific service logs
docker-compose logs web
docker-compose logs celery_worker

# Follow logs in real-time
docker-compose logs -f
``` 