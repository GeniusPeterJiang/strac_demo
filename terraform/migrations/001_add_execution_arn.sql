-- Migration: Add execution_arn column to jobs table
-- Date: 2025-11-09
-- Description: Store Step Functions execution ARN in jobs table for efficient status retrieval

-- Add execution_arn column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'jobs' 
        AND column_name = 'execution_arn'
    ) THEN
        ALTER TABLE jobs ADD COLUMN execution_arn TEXT;
        
        -- Add index for efficient lookups
        CREATE INDEX idx_jobs_execution_arn ON jobs(execution_arn) WHERE execution_arn IS NOT NULL;
        
        RAISE NOTICE 'Added execution_arn column to jobs table';
    ELSE
        RAISE NOTICE 'execution_arn column already exists';
    END IF;
END $$;

