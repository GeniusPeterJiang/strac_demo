# Cache Freshness Tracking

## Overview

The materialized view `job_progress` now tracks **exactly when** it was last refreshed, providing complete transparency about data freshness.

## What Changed

### Before
```json
{
  "job_id": "abc-123",
  "status": "processing",
  "total": 100000,
  "succeeded": 50000,
  "data_source": "cached"
  // ❌ No way to know when this data was cached
}
```

### After
```json
{
  "job_id": "abc-123",
  "status": "processing",
  "total": 100000,
  "succeeded": 50000,
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:14:30Z",  // ✅ Exact refresh time!
  "cache_refresh_duration_ms": 920                // ✅ How long it took
}
```

## New Features

### 1. Refresh Tracking Table

**Migration 002** now creates a tracking table:

```sql
CREATE TABLE materialized_view_refresh_log (
    view_name TEXT PRIMARY KEY,
    last_refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    refresh_duration_ms INTEGER,
    total_jobs INTEGER,
    total_objects BIGINT
);
```

This table stores:
- When each materialized view was last refreshed
- How long the refresh took
- Summary statistics (jobs, objects)

### 2. Refresh Lambda Updates Table

After every refresh, the Lambda function updates the tracking table:

```python
# Update refresh log
cur.execute("""
    INSERT INTO materialized_view_refresh_log 
    (view_name, last_refreshed_at, refresh_duration_ms, total_jobs, total_objects)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (view_name) 
    DO UPDATE SET 
        last_refreshed_at = EXCLUDED.last_refreshed_at,
        refresh_duration_ms = EXCLUDED.refresh_duration_ms,
        total_jobs = EXCLUDED.total_jobs,
        total_objects = EXCLUDED.total_objects;
""", ('job_progress', refresh_end, duration_ms, total_jobs, total_objects))
```

### 3. API Returns Freshness Info

The API Lambda now queries this table and includes the data in cached responses:

```python
# Get refresh timestamp
cur.execute("""
    SELECT last_refreshed_at, refresh_duration_ms
    FROM materialized_view_refresh_log
    WHERE view_name = 'job_progress';
""")

# Add to response
result['cache_refreshed_at'] = timestamp
result['cache_refresh_duration_ms'] = duration_ms
```

## Response Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `cache_refreshed_at` | ISO 8601 timestamp | Exact time the cache was last updated | `"2025-11-09T10:14:30Z"` |
| `cache_refresh_duration_ms` | Integer (milliseconds) | How long the refresh took | `920` |
| `data_source` | String | Always `"cached"` for materialized view | `"cached"` |

**Only present when:**
- Using cached data (default)
- Not present when `?real_time=true`

## Usage Examples

### Check Data Age

```bash
# Get job status with freshness info
curl "${API_URL}/jobs/${JOB_ID}" | jq '{
  job_id,
  status,
  cache_refreshed_at,
  data_age_info: "Data refreshed at \(.cache_refreshed_at)"
}'
```

**Output:**
```json
{
  "job_id": "abc-123",
  "status": "processing",
  "cache_refreshed_at": "2025-11-09T10:14:30Z",
  "data_age_info": "Data refreshed at 2025-11-09T10:14:30Z"
}
```

### Calculate Staleness

```bash
# Calculate how old the cached data is
REFRESH_TIME=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.cache_refreshed_at')
NOW=$(date -u +%s)
REFRESH_EPOCH=$(date -d "$REFRESH_TIME" +%s)
AGE=$((NOW - REFRESH_EPOCH))

echo "Cached data is $AGE seconds old"
```

### Monitor Refresh Performance

```bash
# Check how long refreshes are taking
curl "${API_URL}/jobs/${JOB_ID}" | jq '{
  refresh_duration_ms,
  refresh_duration_seconds: (.cache_refresh_duration_ms / 1000),
  status: (if .cache_refresh_duration_ms < 1000 then "Fast ✓" 
           elif .cache_refresh_duration_ms < 5000 then "Normal ⚠" 
           else "Slow ✗" end)
}'
```

**Output:**
```json
{
  "refresh_duration_ms": 920,
  "refresh_duration_seconds": 0.92,
  "status": "Fast ✓"
}
```

### Alert on Stale Data

```bash
#!/bin/bash
# Alert if cached data is more than 5 minutes old

MAX_AGE_SECONDS=300  # 5 minutes

REFRESH_TIME=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.cache_refreshed_at')
NOW=$(date -u +%s)
REFRESH_EPOCH=$(date -d "$REFRESH_TIME" +%s)
AGE=$((NOW - REFRESH_EPOCH))

if [ $AGE -gt $MAX_AGE_SECONDS ]; then
    echo "⚠️  WARNING: Cached data is $AGE seconds old (max: $MAX_AGE_SECONDS)"
    echo "Check refresh Lambda: aws logs tail /aws/lambda/strac-scanner-refresh-job-progress"
    exit 1
else
    echo "✓ Cached data is fresh ($AGE seconds old)"
fi
```

## Monitoring

### Query Refresh History

```sql
-- Connect to database
psql -h your-rds-endpoint -U scanner_admin -d scanner_db

-- Check refresh status
SELECT 
    view_name,
    last_refreshed_at,
    refresh_duration_ms,
    (refresh_duration_ms / 1000.0) as refresh_duration_sec,
    total_jobs,
    total_objects,
    NOW() - last_refreshed_at as data_age
FROM materialized_view_refresh_log
WHERE view_name = 'job_progress';
```

**Output:**
```
 view_name    | last_refreshed_at           | refresh_duration_ms | refresh_duration_sec | total_jobs | total_objects | data_age
--------------+-----------------------------+--------------------+---------------------+------------+---------------+-----------
 job_progress | 2025-11-09 10:14:30.123-08  |                920 |                0.92 |        150 |     1,250,000 | 00:00:45
```

### Dashboard Query

```sql
-- Get refresh statistics for dashboard
SELECT 
    last_refreshed_at,
    refresh_duration_ms,
    total_jobs,
    total_objects,
    CASE 
        WHEN refresh_duration_ms < 1000 THEN 'Fast'
        WHEN refresh_duration_ms < 5000 THEN 'Normal'
        ELSE 'Slow'
    END as performance_rating,
    EXTRACT(EPOCH FROM (NOW() - last_refreshed_at)) as seconds_since_refresh
FROM materialized_view_refresh_log
WHERE view_name = 'job_progress';
```

### CloudWatch Metrics

You can publish refresh metrics to CloudWatch:

```python
# In refresh Lambda (optional enhancement)
import boto3

cloudwatch = boto3.client('cloudwatch')

# After refresh
cloudwatch.put_metric_data(
    Namespace='S3Scanner',
    MetricData=[
        {
            'MetricName': 'MatViewRefreshDuration',
            'Value': duration_ms,
            'Unit': 'Milliseconds',
            'Dimensions': [
                {'Name': 'ViewName', 'Value': 'job_progress'}
            ]
        },
        {
            'MetricName': 'MatViewJobCount',
            'Value': total_jobs,
            'Unit': 'Count'
        }
    ]
)
```

## Benefits

### For Users

✅ **Transparency**: Know exactly how old the cached data is
✅ **Confidence**: See refresh performance in real-time
✅ **Debugging**: Quickly identify stale data issues
✅ **Monitoring**: Set up alerts for stale caches

### For Developers

✅ **Performance tracking**: Monitor refresh duration over time
✅ **Capacity planning**: Understand when refreshes slow down
✅ **Troubleshooting**: Quickly diagnose refresh failures
✅ **Optimization**: Identify when indexes need tuning

## Comparison: Before vs After

| Aspect | Before | After |
|--------|--------|-------|
| **Data freshness** | Unknown | Exact timestamp |
| **Refresh performance** | Unknown | Duration in ms |
| **Debugging stale data** | Hard | Easy |
| **Monitoring** | Manual | Automatic |
| **User confidence** | Low | High |

## Migration

### Existing Deployments

If you already have migration 002 applied, you need to update:

```bash
# Option 1: Drop and recreate (loses existing mat view data)
psql -h localhost -U scanner_admin -d scanner_db <<EOF
DROP MATERIALIZED VIEW IF EXISTS job_progress CASCADE;
DROP TABLE IF EXISTS materialized_view_refresh_log;
\i terraform/migrations/002_optimize_for_scale.sql
EOF

# Option 2: Add tracking table manually
psql -h localhost -U scanner_admin -d scanner_db <<EOF
CREATE TABLE IF NOT EXISTS materialized_view_refresh_log (
    view_name TEXT PRIMARY KEY,
    last_refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    refresh_duration_ms INTEGER,
    total_jobs INTEGER,
    total_objects BIGINT
);

INSERT INTO materialized_view_refresh_log (view_name, last_refreshed_at)
VALUES ('job_progress', NOW())
ON CONFLICT (view_name) DO NOTHING;
EOF
```

### Then Deploy

```bash
# Deploy updated Lambda functions
./build_and_push.sh
```

## FAQ

### Q: Why not use PostgreSQL system catalogs?

**A:** While `pg_stat_get_last_analyze_time()` exists, it:
- Is less reliable
- Harder to query
- Doesn't track refresh duration
- No custom metadata

Our tracking table provides complete control and better performance.

### Q: Does this add overhead?

**A:** Minimal:
- Single INSERT/UPDATE per refresh (1-2ms)
- Indexed by primary key (instant lookups)
- No impact on application queries

### Q: What if the tracking table gets out of sync?

**A:** It can't - the Lambda updates it in the same transaction as the refresh:
```python
cur.execute("REFRESH MATERIALIZED VIEW...")
cur.execute("INSERT INTO tracking_log...")
conn.commit()  # Atomic
```

### Q: Can I track multiple materialized views?

**A:** Yes! The table is designed for it:
```sql
INSERT INTO materialized_view_refresh_log 
(view_name, last_refreshed_at, refresh_duration_ms)
VALUES ('my_other_view', NOW(), 500);
```

### Q: How do I query the refresh log directly?

```bash
# Get refresh status
psql -h localhost -U scanner_admin -d scanner_db \
  -c "SELECT * FROM materialized_view_refresh_log;"

# Or via Lambda (add new endpoint)
curl "${API_URL}/cache/status"
```

## Summary

✅ **Added**: Refresh timestamp tracking table
✅ **Updated**: Refresh Lambda writes timestamps
✅ **Enhanced**: API returns freshness info
✅ **Improved**: Complete cache transparency

Users now have full visibility into cached data freshness! 🎉

**Response Example:**
```json
{
  "job_id": "abc-123",
  "status": "processing",
  "progress_percent": 50.0,
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:14:30.123Z",  ← Exact refresh time
  "cache_refresh_duration_ms": 920                    ← How long it took
}
```

**Bottom line**: You always know how fresh your data is! ⏱️

