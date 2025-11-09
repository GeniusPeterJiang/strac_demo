# Database Views Comparison: job_summary vs job_progress

## Overview

The S3 Scanner database has two views for job statistics:

1. **`job_summary`** - A regular view (defined in `database_schema.sql`)
2. **`job_progress`** - A materialized view (defined in migration `002_optimize_for_scale.sql`)

## Key Differences

| Feature | `job_summary` (View) | `job_progress` (Materialized View) |
|---------|---------------------|-----------------------------------|
| **Type** | Regular view | Materialized view |
| **Data Freshness** | Real-time (always current) | Cached (refreshed periodically) |
| **Query Speed** | Slow for large datasets | Very fast (pre-computed) |
| **Storage** | No storage (computed on-the-fly) | Stores pre-computed results |
| **Best For** | Small jobs (<10K objects) | Large jobs (>100K objects) |
| **Maintenance** | None | Requires periodic refresh |

## Technical Details

### `job_summary` (Regular View)

**Defined in:** `terraform/database_schema.sql` (lines 73-99)

**Query:**
```sql
CREATE OR REPLACE VIEW job_summary AS
SELECT 
    j.job_id,
    j.bucket,
    j.prefix,
    j.created_at,
    j.updated_at,
    COUNT(DISTINCT jo.id) as total_objects,
    COUNT(DISTINCT CASE WHEN jo.status = 'queued' THEN jo.id END) as queued,
    COUNT(DISTINCT CASE WHEN jo.status = 'processing' THEN jo.id END) as processing,
    COUNT(DISTINCT CASE WHEN jo.status = 'succeeded' THEN jo.id END) as succeeded,
    COUNT(DISTINCT CASE WHEN jo.status = 'failed' THEN jo.id END) as failed,
    COUNT(DISTINCT f.id) as total_findings
FROM jobs j
LEFT JOIN job_objects jo ON j.job_id = jo.job_id
LEFT JOIN findings f ON j.job_id = f.job_id
GROUP BY j.job_id, j.bucket, j.prefix, j.created_at, j.updated_at;
```

**Characteristics:**
- ✅ Always shows real-time data
- ❌ Slow for large jobs (must scan all `job_objects` rows)
- ❌ Uses `COUNT(DISTINCT ...)` which is less efficient
- ❌ Joins with `findings` table in the main query

**Performance:**
- Small job (1K objects): ~50ms
- Medium job (100K objects): ~500ms
- Large job (1M objects): ~5 seconds

### `job_progress` (Materialized View)

**Defined in:** `terraform/migrations/002_optimize_for_scale.sql` (lines 20-40)

**Query:**
```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS job_progress AS
SELECT
    j.job_id,
    j.bucket,
    j.prefix,
    j.execution_arn,
    j.created_at,
    j.updated_at,
    COALESCE(SUM(CASE WHEN jo.status IS NOT NULL THEN 1 ELSE 0 END), 0) AS total_objects,
    COALESCE(SUM(CASE WHEN jo.status = 'queued' THEN 1 ELSE 0 END), 0) AS queued_count,
    COALESCE(SUM(CASE WHEN jo.status = 'processing' THEN 1 ELSE 0 END), 0) AS processing_count,
    COALESCE(SUM(CASE WHEN jo.status = 'succeeded' THEN 1 ELSE 0 END), 0) AS succeeded_count,
    COALESCE(SUM(CASE WHEN jo.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
    COALESCE(f.total_findings, 0) AS total_findings,
    CASE
        WHEN COALESCE(SUM(CASE WHEN jo.status IS NOT NULL THEN 1 ELSE 0 END), 0) = 0 THEN 0.0
        ELSE (COALESCE(SUM(CASE WHEN jo.status = 'succeeded' THEN 1 ELSE 0 END), 0) + 
              COALESCE(SUM(CASE WHEN jo.status = 'failed' THEN 1 ELSE 0 END), 0)) * 100.0 / 
              COALESCE(SUM(CASE WHEN jo.status IS NOT NULL THEN 1 ELSE 0 END), 0)
    END AS progress_percent
FROM jobs j
LEFT JOIN job_objects jo ON j.job_id = jo.job_id
LEFT JOIN (SELECT job_id, COUNT(*) AS total_findings FROM findings GROUP BY job_id) f 
    ON j.job_id = f.job_id
GROUP BY j.job_id, j.bucket, j.prefix, j.execution_arn, j.created_at, j.updated_at, f.total_findings;
```

**Characteristics:**
- ✅ Extremely fast (pre-computed, indexed)
- ✅ Includes `execution_arn` field
- ✅ Pre-calculates `progress_percent`
- ✅ Uses efficient `SUM(CASE ...)` instead of `COUNT(DISTINCT ...)`
- ✅ Findings are pre-aggregated in subquery
- ❌ Data is cached (up to 1 minute stale)
- ❌ Requires periodic refresh

**Performance:**
- Any job size: ~10-50ms (constant time)

**Refresh:**
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;
```

## API Integration

The `get_job_status()` function in Lambda uses both views:

```python
def get_job_status(job_id: str, real_time: bool = False) -> Dict[str, Any]:
    """
    Get status of a scan job.
    
    Args:
        job_id: Job ID
        real_time: If True, fetch real-time data (slower). 
                   If False, use cached data (faster, default)
    """
    if has_matview and not real_time:
        # Use job_progress (cached, fast)
        # Returns data_source: "cached" and cache_timestamp
    else:
        # Use direct queries (similar to job_summary)
        # Returns data_source: "real_time"
```

**Default Behavior:**
- Uses `job_progress` (materialized view) for fast responses
- Falls back to real-time queries if:
  - Materialized view doesn't exist
  - User requests `?real_time=true`
  - Job not in materialized view yet (very recent)

## Why We Keep Both

### Keep `job_summary`:
- ✅ Backwards compatibility
- ✅ Simple queries for developers
- ✅ Good for ad-hoc analysis in psql
- ✅ No maintenance required
- ✅ Always accurate for debugging

**Usage:**
```sql
-- Quick overview of all jobs
SELECT * FROM job_summary WHERE bucket = 'my-bucket' ORDER BY created_at DESC;
```

### Keep `job_progress`:
- ✅ Production API performance
- ✅ Scales to millions of objects per job
- ✅ Reduces database load
- ✅ Includes `execution_arn` for Step Functions integration
- ✅ Pre-computed `progress_percent`

**Usage:**
```python
# In Lambda - fast API responses
cur.execute("SELECT * FROM job_progress WHERE job_id = %s", (job_id,))
```

## Migration Path

### Phase 1: Development (Current)
- Use `job_summary` for local testing
- Simple queries, no maintenance

### Phase 2: Scale Testing
- Apply migration `002_optimize_for_scale.sql`
- Test with large datasets (>100K objects)

### Phase 3: Production
- Enable `job_progress` refresh cron job
- API defaults to cached data
- `job_summary` remains available for ad-hoc queries

## Maintenance

### For `job_summary`:
No maintenance required - it's always in sync.

### For `job_progress`:
Setup cron job:
```bash
# Refresh every minute
* * * * * /usr/bin/python3 /path/to/refresh_job_progress.py >> /var/log/refresh_job_progress.log 2>&1
```

Or manual refresh:
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;
```

**Refresh Time:**
- <10K jobs: ~100ms
- 100K jobs: ~1 second
- 1M jobs: ~10 seconds

**CONCURRENTLY** allows queries while refreshing (requires unique index).

## Query Examples

### Using `job_summary` (Real-Time)

```sql
-- All jobs with their current status
SELECT 
    job_id, 
    bucket, 
    total_objects, 
    succeeded, 
    failed,
    CASE 
        WHEN total_objects = 0 THEN 0
        ELSE (succeeded + failed) * 100.0 / total_objects
    END as progress
FROM job_summary
ORDER BY created_at DESC;

-- Jobs with active processing
SELECT * FROM job_summary 
WHERE processing > 0 OR queued > 0
ORDER BY created_at DESC;
```

### Using `job_progress` (Cached, Fast)

```sql
-- Same queries, but much faster for large jobs
SELECT 
    job_id, 
    bucket, 
    total_objects, 
    succeeded_count, 
    failed_count,
    progress_percent  -- Pre-calculated!
FROM job_progress
ORDER BY created_at DESC;

-- Active jobs (use helper view)
SELECT * FROM active_jobs_progress;

-- Jobs by Step Functions status
SELECT * FROM job_progress 
WHERE execution_arn IS NOT NULL
AND total_objects > 0;
```

## Recommendations

### Use `job_summary` when:
- 🔬 Debugging specific issues
- 📊 Ad-hoc analysis in psql
- 🧪 Testing with small datasets
- ⚡ Need guaranteed real-time accuracy

### Use `job_progress` when:
- 🚀 Production API calls
- 📈 Large scale deployments (>100K objects/job)
- 🎯 Dashboard/monitoring systems
- 💰 Reducing database costs

### API Usage:
```bash
# Default: Fast cached data (uses job_progress)
curl "${API_URL}/jobs/${JOB_ID}"

# Explicit real-time (uses direct queries like job_summary)
curl "${API_URL}/jobs/${JOB_ID}?real_time=true"
```

## Summary

Both views serve important purposes:

- **`job_summary`**: Always accurate, simple, developer-friendly
- **`job_progress`**: Production-ready, optimized, scalable

The Lambda API intelligently chooses based on the `real_time` parameter, giving you the best of both worlds:
- Fast by default (cached)
- Accurate when needed (real-time)

