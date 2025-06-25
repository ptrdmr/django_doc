-- PostgreSQL initialization script for Medical Document Parser
-- This script sets up the database with necessary extensions for FHIR processing

-- Create the main database if it doesn't exist
-- (This is typically handled by POSTGRES_DB environment variable)

-- Connect to the meddocparser database
\c meddocparser;

-- Enable necessary PostgreSQL extensions for medical data processing
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";     -- For generating UUIDs
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- For text similarity and fuzzy matching
CREATE EXTENSION IF NOT EXISTS "btree_gin";     -- For better JSONB indexing performance

-- Create indexes for common JSONB queries on FHIR data
-- These will be used by Django models once they're created

-- Set timezone to UTC for consistent timestamps
SET timezone = 'UTC';

-- Create a function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Grant necessary permissions for the Django user
-- (postgres user has full access by default)

-- Log initialization completion
DO $$
BEGIN
    RAISE NOTICE 'Medical Document Parser database initialized successfully';
    RAISE NOTICE 'Extensions enabled: uuid-ossp, pg_trgm, btree_gin';
    RAISE NOTICE 'Ready for FHIR data processing with JSONB support';
END $$; 