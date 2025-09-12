# Database Backup Script for Medical Document Parser (PowerShell)
# Run this regularly to backup your PostgreSQL database

# Configuration
$BACKUP_DIR = ".\backups"
$DB_NAME = "meddocparser"
$DB_USER = "postgres"
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$BACKUP_FILE = "$BACKUP_DIR\meddocparser_backup_$TIMESTAMP.sql"

# Create backup directory if it doesn't exist
if (-not (Test-Path $BACKUP_DIR)) {
    New-Item -ItemType Directory -Path $BACKUP_DIR
}

# Create database backup
Write-Host "Creating database backup..."
docker-compose exec -T db pg_dump -U $DB_USER -d $DB_NAME | Out-File -FilePath $BACKUP_FILE -Encoding UTF8

# Compress the backup
Compress-Archive -Path $BACKUP_FILE -DestinationPath "$BACKUP_FILE.zip"
Remove-Item $BACKUP_FILE

Write-Host "Backup created: $BACKUP_FILE.zip"

# Keep only last 10 backups
$backups = Get-ChildItem -Path $BACKUP_DIR -Filter "meddocparser_backup_*.sql.zip" | Sort-Object LastWriteTime -Descending
if ($backups.Count -gt 10) {
    $backups | Select-Object -Skip 10 | Remove-Item
    Write-Host "Cleaned up old backups"
}

Write-Host "Backup completed successfully!"
