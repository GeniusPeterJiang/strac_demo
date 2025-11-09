# Job Status API - Enhanced with Step Functions Tracking

## Overview

The `GET /jobs/{job_id}` endpoint now tracks Step Functions execution status to accurately reflect whether the job is still listing objects or has moved to processing/completed stages.

## Query Parameters

### `real_time` (optional)

Controls whether to use cached or real-time data:

- **Default**: `false` (cached data from materialized view)
  - ✅ **Fast**: Optimized for large jobs with millions of objects
  - ✅ **Efficient**: Doesn't query millions of rows on every request
  - ℹ️ **Staleness**: Data may be up to refresh interval old (default: 1 minute)
  - 📊 Returns `data_source: "cached"` and `cache_timestamp`

- **`?real_time=true`**: Real-time data from database
  - ✅ **Fresh**: Always up-to-the-second accurate
  - ⚠️ **Slower**: For jobs with millions of objects, may take several seconds
  - 📊 Returns `data_source: "real_time"`

**Examples:**
```bash
# Fast cached data (default)
curl "${API_URL}/jobs/${JOB_ID}"

# Real-time fresh data
curl "${API_URL}/jobs/${JOB_ID}?real_time=true"

# Explicit cached request
curl "${API_URL}/jobs/${JOB_ID}?real_time=false"
```

## Status Flow

```
1. POST /scan → Job Created
         ↓
2. status: "listing" (Step Functions RUNNING)
         ├─ Step Functions listing S3 objects
         ├─ Objects being inserted to DB
         └─ Objects being enqueued to SQS
         ↓
3. status: "processing" (Step Functions SUCCEEDED)
         ├─ All objects listed and enqueued
         ├─ ECS tasks scanning files
         └─ Progress: N% (based on job_objects status)
         ↓
4. status: "completed"
         └─ All objects scanned
```

## Response Examples

### 1. Initial State - Listing Objects

**Request:**
```bash
curl "${API_URL}/jobs/abc-123-def"
```

**Response (Cached):**
```json
{
  "job_id": "abc-123-def",
  "bucket": "my-bucket",
  "prefix": "large-dataset/",
  "created_at": "2025-11-09T10:00:00Z",
  "updated_at": "2025-11-09T10:00:00Z",
  
  "status": "listing",
  "status_message": "Step Functions is listing S3 objects",
  "step_function_status": "RUNNING",
  "execution_arn": "arn:aws:states:us-west-2:123456789:execution:strac-scanner-s3-scanner:scan-abc-123-def",
  
  "total": 25000,
  "queued": 25000,
  "processing": 0,
  "succeeded": 0,
  "failed": 0,
  "total_findings": 0,
  "progress_percent": 0,
  
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T09:59:30Z",
  "cache_refresh_duration_ms": 850
}
```

**Key indicators:**
- ✅ `status: "listing"` - Still discovering objects
- ✅ `step_function_status: "RUNNING"` - Step Functions active
- ✅ `total` is increasing as more objects are discovered
- ℹ️ `progress_percent: 0` - Processing hasn't started yet
- 📊 `cache_refreshed_at` - When this cached data was last updated
- ⚡ `cache_refresh_duration_ms` - How long the refresh took (850ms = very fast!)

### 2. Transitioning - Listing Complete, Processing Starting

**Request:**
```bash
curl "${API_URL}/jobs/abc-123-def"
```

**Response (Cached):**
```json
{
  "job_id": "abc-123-def",
  "bucket": "my-bucket",
  "prefix": "large-dataset/",
  "created_at": "2025-11-09T10:00:00Z",
  "updated_at": "2025-11-09T10:05:00Z",
  
  "status": "processing",
  "status_message": "Scanning objects (5000/100000)",
  "step_function_status": "SUCCEEDED",
  "execution_arn": "arn:aws:states:us-west-2:123456789:execution:strac-scanner-s3-scanner:scan-abc-123-def",
  
  "total": 100000,
  "queued": 80000,
  "processing": 15000,
  "succeeded": 5000,
  "failed": 0,
  "total_findings": 234,
  "progress_percent": 5.0,
  
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:04:30Z",
  "cache_refresh_duration_ms": 920
}
```

**Key indicators:**
- ✅ `status: "processing"` - Objects being scanned
- ✅ `step_function_status: "SUCCEEDED"` - Listing complete
- ✅ `total` is now fixed (100,000 objects found)
- ✅ `progress_percent: 5%` - 5K out of 100K scanned
- ✅ `total_findings: 234` - Sensitive data detected

### 3. In Progress - Scanning Objects

**Request:**
```bash
curl "${API_URL}/jobs/abc-123-def"
```

**Response (Cached):**
```json
{
  "job_id": "abc-123-def",
  "bucket": "my-bucket",
  "prefix": "large-dataset/",
  "created_at": "2025-11-09T10:00:00Z",
  "updated_at": "2025-11-09T10:15:00Z",
  
  "status": "processing",
  "status_message": "Scanning objects (50000/100000)",
  "step_function_status": "SUCCEEDED",
  
  "total": 100000,
  "queued": 30000,
  "processing": 20000,
  "succeeded": 48000,
  "failed": 2000,
  "total_findings": 5421,
  "progress_percent": 50.0,
  
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:14:30Z",
  "cache_refresh_duration_ms": 1150
}
```

**Key indicators:**
- ✅ `progress_percent: 50%` - Half way done
- ✅ `succeeded: 48000` - Successfully scanned
- ⚠️ `failed: 2000` - Some files failed (too large, invalid format, etc.)
- ✅ `total_findings: 5421` - Findings accumulating

### 4. Completed

**Request:**
```bash
curl "${API_URL}/jobs/abc-123-def"
```

**Response (Cached):**
```json
{
  "job_id": "abc-123-def",
  "bucket": "my-bucket",
  "prefix": "large-dataset/",
  "created_at": "2025-11-09T10:00:00Z",
  "updated_at": "2025-11-09T10:30:00Z",
  
  "status": "completed",
  "status_message": "All objects scanned",
  "step_function_status": "SUCCEEDED",
  
  "total": 100000,
  "queued": 0,
  "processing": 0,
  "succeeded": 97500,
  "failed": 2500,
  "total_findings": 12543,
  "progress_percent": 100.0,
  
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:29:30Z",
  "cache_refresh_duration_ms": 1050
}
```

**Key indicators:**
- ✅ `status: "completed"` - Job finished
- ✅ `progress_percent: 100%` - All objects processed
- ✅ `total_findings: 12543` - Final findings count
- ℹ️ `failed: 2500` - Some files couldn't be scanned

### 5. No Objects Found

**Request:**
```bash
curl "${API_URL}/jobs/xyz-789"
```

**Response:**
```json
{
  "job_id": "xyz-789",
  "bucket": "my-bucket",
  "prefix": "empty-folder/",
  "created_at": "2025-11-09T11:00:00Z",
  "updated_at": "2025-11-09T11:00:30Z",
  
  "status": "completed",
  "status_message": "No objects found to scan",
  "step_function_status": "SUCCEEDED",
  
  "total": 0,
  "queued": 0,
  "processing": 0,
  "succeeded": 0,
  "failed": 0,
  "total_findings": 0,
  "progress_percent": 0
}
```

**Key indicators:**
- ✅ `status: "completed"` - Job finished quickly
- ℹ️ `total: 0` - No objects in that prefix
- ℹ️ `status_message` explains why

### 6. Step Functions Failed

**Request:**
```bash
curl "${API_URL}/jobs/err-456"
```

**Response:**
```json
{
  "job_id": "err-456",
  "bucket": "restricted-bucket",
  "prefix": "data/",
  "created_at": "2025-11-09T12:00:00Z",
  "updated_at": "2025-11-09T12:01:00Z",
  
  "status": "failed",
  "status_message": "Step Functions execution failed",
  "step_function_status": "FAILED",
  "execution_arn": "arn:aws:states:us-west-2:123456789:execution:strac-scanner-s3-scanner:scan-err-456",
  
  "total": 5000,
  "queued": 5000,
  "processing": 0,
  "succeeded": 0,
  "failed": 0,
  "total_findings": 0,
  "progress_percent": 0
}
```

**Key indicators:**
- ❌ `status: "failed"` - Something went wrong
- ❌ `step_function_status: "FAILED"` - Step Functions error
- ℹ️ Check Step Functions console or CloudWatch logs for details
- ℹ️ Common causes: S3 permissions, Lambda errors, DB connection issues

## Performance: Cached vs Real-Time

### When to Use Each Mode

| Mode | Best For | Response Time | Data Freshness |
|------|----------|---------------|----------------|
| **Cached (default)** | Dashboards, monitoring, frequent polls | <100ms | Up to 1 minute old |
| **Real-Time** | Critical status checks, debugging | 100ms - 5s+ | Live, exact |

### Performance Comparison

For a job with **1 million objects**:

**Cached Query:**
```bash
curl "${API_URL}/jobs/${JOB_ID}"
```
- ⚡ Response time: ~50ms
- 📊 Queries materialized view: 1 row lookup
- 💰 Database load: Minimal (indexed lookup)
- ✅ Scales to millions of jobs

**Real-Time Query:**
```bash
curl "${API_URL}/jobs/${JOB_ID}?real_time=true"
```
- 🐌 Response time: ~3-5 seconds
- 📊 Queries job_objects: COUNT(*) on 1M rows
- 💰 Database load: High (aggregation on large table)
- ⚠️ Can impact database performance under load

### Recommendation

**For most use cases**: Use cached data (default)
- ✅ Fast and scalable
- ✅ 1-minute staleness is acceptable for monitoring
- ✅ Reduces database load

**Use real-time only when**:
- 🔍 Debugging specific issues
- 🎯 Need exact, second-by-second accuracy
- 📈 Verifying cache is working correctly

### Cache Freshness

The materialized view is refreshed every **1 minute** by EventBridge + Lambda.

**New Fields (for cached responses):**

| Field | Description | Example |
|-------|-------------|---------|
| `cache_refreshed_at` | Exact timestamp when materialized view was last refreshed | `"2025-11-09T10:29:30Z"` |
| `cache_refresh_duration_ms` | How long the refresh took (in milliseconds) | `850` (0.85 seconds) |
| `data_source` | Always `"cached"` when using materialized view | `"cached"` |

**Check data freshness:**
```bash
# Get refresh timestamp
curl "${API_URL}/jobs/${JOB_ID}" | jq '.cache_refreshed_at'
# Output: "2025-11-09T10:29:30Z"

# Calculate age
curl "${API_URL}/jobs/${JOB_ID}" | jq -r '.cache_refreshed_at' | \
  xargs -I {} date -d {} +%s | \
  awk -v now=$(date +%s) '{print "Data is " (now - $1) " seconds old"}'
```

**If data is more than 2 minutes old:**
```bash
# Check refresh Lambda logs
aws logs tail /aws/lambda/strac-scanner-refresh-job-progress --since 5m

# Check EventBridge rule status
aws events describe-rule --name strac-scanner-refresh-job-progress
```

## Status Field Values

| Status | Meaning | Step Functions | Objects |
|--------|---------|----------------|---------|
| `listing` | Discovering S3 objects | RUNNING | Increasing |
| `processing` | Scanning files | SUCCEEDED | Fixed, being processed |
| `completed` | All done | SUCCEEDED | All processed |
| `failed` | Error occurred | FAILED/TIMED_OUT | Processing stopped |
| `aborted` | Manually stopped | ABORTED | Processing stopped |

## Step Function Status Values

AWS Step Functions statuses:
- `RUNNING` - Currently executing
- `SUCCEEDED` - Completed successfully
- `FAILED` - Execution failed (check CloudWatch logs)
- `TIMED_OUT` - Exceeded maximum execution time
- `ABORTED` - Manually cancelled

## Progress Calculation

```python
progress_percent = (succeeded + failed) / total * 100
```

**Why include failed in progress?**
- `failed` means we attempted to scan but couldn't (file too large, wrong format, etc.)
- These objects are "processed" even if unsuccessfully
- This gives accurate progress tracking

## Monitoring Patterns

### Check if Still Listing

```bash
# Poll until listing complete
while true; do
  STATUS=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.status')
  
  if [ "$STATUS" != "listing" ]; then
    echo "Listing complete! Status: $STATUS"
    break
  fi
  
  TOTAL=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.total')
  echo "Still listing... Found $TOTAL objects so far"
  sleep 5
done
```

### Monitor Processing Progress

```bash
# Poll until complete
while true; do
  RESPONSE=$(curl -s "${API_URL}/jobs/${JOB_ID}")
  STATUS=$(echo "$RESPONSE" | jq -r '.status')
  PROGRESS=$(echo "$RESPONSE" | jq -r '.progress_percent')
  SUCCEEDED=$(echo "$RESPONSE" | jq -r '.succeeded')
  TOTAL=$(echo "$RESPONSE" | jq -r '.total')
  
  echo "Status: $STATUS | Progress: $PROGRESS% ($SUCCEEDED/$TOTAL)"
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  
  sleep 10
done
```

### Check for Errors

```bash
# Check if Step Functions failed
SF_STATUS=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.step_function_status')

if [ "$SF_STATUS" = "FAILED" ]; then
  echo "Step Functions failed!"
  EXEC_ARN=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.execution_arn')
  echo "Check execution: $EXEC_ARN"
  echo "CloudWatch logs: /aws/stepfunctions/strac-scanner-demo-s3-scanner"
fi
```

## Differences from Before

### Old Response (Before Step Functions)
```json
{
  "job_id": "abc-123",
  "bucket": "my-bucket",
  "total": 50000,
  "succeeded": 10000,
  "progress_percent": 20.0
}
```
- ❌ No way to tell if still listing vs processing
- ❌ No execution tracking
- ❌ Less detailed status information

### New Response (With Step Functions)
```json
{
  "job_id": "abc-123",
  "bucket": "my-bucket",
  "status": "processing",
  "status_message": "Scanning objects (10000/50000)",
  "step_function_status": "SUCCEEDED",
  "execution_arn": "arn:aws:...",
  "total": 50000,
  "succeeded": 10000,
  "progress_percent": 20.0
}
```
- ✅ Clear distinction between listing and processing
- ✅ Execution ARN for deep debugging
- ✅ Human-readable status messages
- ✅ Step Functions status for error tracking

## API Contract

### Response Schema

```typescript
interface JobStatus {
  // Job identification
  job_id: string;
  bucket: string;
  prefix: string;
  created_at: string;  // ISO 8601
  updated_at: string;  // ISO 8601
  
  // Overall status
  status: "listing" | "processing" | "completed" | "failed" | "aborted";
  status_message: string;
  
  // Step Functions (optional - only if using async mode)
  step_function_status?: "RUNNING" | "SUCCEEDED" | "FAILED" | "TIMED_OUT" | "ABORTED";
  execution_arn?: string;
  
  // Object statistics
  total: number;           // Total objects discovered
  queued: number;          // Waiting in SQS
  processing: number;      // Currently being scanned
  succeeded: number;       // Successfully scanned
  failed: number;          // Failed to scan
  
  // Results
  total_findings: number;  // Sensitive data detections
  progress_percent: number; // 0-100
}
```

## Summary

The enhanced job status API provides:

✅ **Clear lifecycle tracking** - Know if listing or processing  
✅ **Step Functions visibility** - Track async execution  
✅ **Error detection** - Identify failures quickly  
✅ **Progress monitoring** - Real-time updates  
✅ **Debugging support** - Execution ARNs and detailed messages  

This makes it easy to build UIs that accurately reflect job progress through all stages!

