-- Database schema for S3 Scanner
-- Run this script to initialize the database

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bucket TEXT NOT NULL,
    prefix TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);

-- Job objects table (tracks individual S3 objects in a job)
CREATE TABLE IF NOT EXISTS job_objects (
    job_id UUID NOT NULL,
    bucket TEXT NOT NULL,
    key TEXT NOT NULL,
    etag TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'succeeded', 'failed')),
    last_error TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (job_id, bucket, key, etag),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_objects_job_id ON job_objects(job_id);
CREATE INDEX IF NOT EXISTS idx_job_objects_status ON job_objects(status);
CREATE INDEX IF NOT EXISTS idx_job_objects_bucket_key ON job_objects(bucket, key);

-- Findings table (stores detected sensitive data)
CREATE TABLE IF NOT EXISTS findings (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL,
    bucket TEXT NOT NULL,
    key TEXT NOT NULL,
    detector TEXT NOT NULL,
    masked_match TEXT NOT NULL,
    context TEXT,
    byte_offset INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (bucket, key, etag, detector, byte_offset)
);

-- Add etag column if not exists (for deduplication)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='findings' AND column_name='etag') THEN
        ALTER TABLE findings ADD COLUMN etag TEXT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_findings_job_id ON findings(job_id);
CREATE INDEX IF NOT EXISTS idx_findings_bucket_key ON findings(bucket, key);
CREATE INDEX IF NOT EXISTS idx_findings_detector ON findings(detector);
CREATE INDEX IF NOT EXISTS idx_findings_created_at ON findings(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_dedup ON findings(bucket, key, etag, detector, byte_offset);

-- Partition findings table by job_id for very large datasets
-- Uncomment and adjust if you expect > 100M rows
-- CREATE TABLE findings_partitioned (
--     LIKE findings INCLUDING ALL
-- ) PARTITION BY HASH (job_id);
--
-- CREATE TABLE findings_partitioned_0 PARTITION OF findings_partitioned
--     FOR VALUES WITH (modulus 4, remainder 0);
-- CREATE TABLE findings_partitioned_1 PARTITION OF findings_partitioned
--     FOR VALUES WITH (modulus 4, remainder 1);
-- CREATE TABLE findings_partitioned_2 PARTITION OF findings_partitioned
--     FOR VALUES WITH (modulus 4, remainder 2);
-- CREATE TABLE findings_partitioned_3 PARTITION OF findings_partitioned
--     FOR VALUES WITH (modulus 4, remainder 3);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers to auto-update updated_at
CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_job_objects_updated_at BEFORE UPDATE ON job_objects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- View for job summary statistics
CREATE OR REPLACE VIEW job_summary AS
SELECT 
    j.job_id,
    j.bucket,
    j.prefix,
    j.status,
    j.total_objects,
    COUNT(jo.id) FILTER (WHERE jo.status = 'queued') as queued_count,
    COUNT(jo.id) FILTER (WHERE jo.status = 'processing') as processing_count,
    COUNT(jo.id) FILTER (WHERE jo.status = 'succeeded') as succeeded_count,
    COUNT(jo.id) FILTER (WHERE jo.status = 'failed') as failed_count,
    SUM(jo.findings_count) as total_findings,
    j.created_at,
    j.updated_at
FROM jobs j
LEFT JOIN job_objects jo ON j.job_id = jo.job_id
GROUP BY j.job_id, j.bucket, j.prefix, j.status, j.total_objects, j.created_at, j.updated_at;

-- Grant permissions (adjust as needed for your RDS user)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO scanner_admin;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO scanner_admin;

