#!/bin/bash

# Database Backup Script for Medical Document Parser
# Run this regularly to backup your PostgreSQL database

# Configuration
BACKUP_DIR="./backups"
DB_NAME="meddocparser"
DB_USER="postgres"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/meddocparser_backup_${TIMESTAMP}.sql"

# Create backup directory if it doesn't exist
mkdir -p $BACKUP_DIR

# Create database backup
echo "Creating database backup..."
docker-compose exec -T db pg_dump -U $DB_USER -d $DB_NAME > $BACKUP_FILE

# Compress the backup
gzip $BACKUP_FILE

echo "Backup created: ${BACKUP_FILE}.gz"

# Keep only last 10 backups
cd $BACKUP_DIR
ls -t meddocparser_backup_*.sql.gz | tail -n +11 | xargs -r rm --

echo "Backup completed successfully!"
