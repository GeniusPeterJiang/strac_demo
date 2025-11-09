# Curl Testing Examples for S3 Scanner API

## Setup

First, get your API URL from Terraform:

```bash
cd terraform
export API_URL=$(terraform output -raw api_gateway_url)
echo "API URL: $API_URL"
```

## POST /scan - Trigger Scan

### Basic Scan (All Objects in Bucket)

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "strac-scanner-demo-697547269674"
  }'
```

**Response:**
```json
{
  "job_id": "abc-123-def-456",
  "bucket": "strac-scanner-demo-697547269674",
  "prefix": "",
  "status": "listing",
  "execution_arn": "arn:aws:states:us-west-2:123456789:execution:strac-scanner-s3-scanner:scan-abc-123-def-456",
  "message": "Job created. Objects are being listed and enqueued asynchronously.",
  "async": true
}
```

### Scan with Prefix (Specific Folder)

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "strac-scanner-demo-697547269674",
    "prefix": "test/"
  }'
```

### Scan Specific Date Partition

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "my-logs-bucket",
    "prefix": "logs/2025/11/"
  }'
```

### Scan Multiple Prefixes (Run Multiple Jobs)

```bash
# Scan each prefix separately
for prefix in "documents/" "images/" "logs/"; do
  echo "Scanning prefix: $prefix"
  curl -X POST "${API_URL}/scan" \
    -H "Content-Type: application/json" \
    -d "{
      \"bucket\": \"my-bucket\",
      \"prefix\": \"$prefix\"
    }"
  echo ""
done
```

## GET /jobs/{job_id} - Check Status

### Get Job Status (Cached - Default, Fast)

```bash
# Save job_id from scan response
JOB_ID="abc-123-def-456"

# Default: uses cached data from materialized view (fast)
curl "${API_URL}/jobs/${JOB_ID}" | jq .
```

**Response (Cached):**
```json
{
  "job_id": "abc-123-def-456",
  "bucket": "strac-scanner-demo-697547269674",
  "prefix": "test/",
  "execution_arn": "arn:aws:states:...",
  "created_at": "2025-11-09T10:00:00Z",
  "updated_at": "2025-11-09T10:05:00Z",
  "status": "processing",
  "status_message": "Scanning objects (5000/10000)",
  "step_function_status": "SUCCEEDED",
  "total": 10000,
  "queued": 3000,
  "processing": 2000,
  "succeeded": 5000,
  "failed": 0,
  "total_findings": 123,
  "progress_percent": 50.0,
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:04:30Z",
  "cache_refresh_duration_ms": 920
}
```

### Get Job Status (Real-Time - Slower but Fresh)

```bash
# Add ?real_time=true to get live data (slower for large jobs)
curl "${API_URL}/jobs/${JOB_ID}?real_time=true" | jq .
```

**Response (Real-Time):**
```json
{
  "job_id": "abc-123-def-456",
  "bucket": "strac-scanner-demo-697547269674",
  "prefix": "test/",
  "execution_arn": "arn:aws:states:...",
  "created_at": "2025-11-09T10:00:00Z",
  "updated_at": "2025-11-09T10:05:15Z",
  "status": "processing",
  "status_message": "Scanning objects (5250/10000)",
  "step_function_status": "SUCCEEDED",
  "total": 10000,
  "queued": 2750,
  "processing": 2000,
  "succeeded": 5250,
  "failed": 0,
  "total_findings": 128,
  "progress_percent": 52.5,
  "data_source": "real_time"
}
```

### Poll Until Complete

```bash
JOB_ID="abc-123-def-456"

while true; do
  RESPONSE=$(curl -s "${API_URL}/jobs/${JOB_ID}")
  STATUS=$(echo "$RESPONSE" | jq -r '.status')
  PROGRESS=$(echo "$RESPONSE" | jq -r '.progress_percent')
  
  echo "Status: $STATUS | Progress: $PROGRESS%"
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    echo "$RESPONSE" | jq .
    break
  fi
  
  sleep 5
done
```

### Check Multiple Jobs

```bash
# Check status of multiple jobs
for job_id in "job1" "job2" "job3"; do
  echo "=== Job: $job_id ==="
  curl -s "${API_URL}/jobs/${job_id}" | jq '{
    job_id,
    status,
    progress_percent,
    total_findings
  }'
  echo ""
done
```

## GET /results - Retrieve Findings

### Get All Results

```bash
curl "${API_URL}/results" | jq .
```

### Get Results for Specific Job

```bash
JOB_ID="abc-123-def-456"

curl "${API_URL}/results?job_id=${JOB_ID}" | jq .
```

**Response:**
```json
{
  "findings": [
    {
      "id": 12345,
      "job_id": "abc-123-def-456",
      "bucket": "my-bucket",
      "key": "sensitive-data.txt",
      "detector": "SSN",
      "masked_match": "***-**-1234",
      "context": "SSN: ***-**-1234 found in document",
      "byte_offset": 150,
      "created_at": "2025-11-09T10:15:00Z"
    }
  ],
  "total": 123,
  "limit": 100,
  "has_more": true
}
```

### Paginate Results (Cursor-based)

```bash
JOB_ID="abc-123-def-456"

# First page
curl "${API_URL}/results?job_id=${JOB_ID}&limit=10" > page1.json
cat page1.json | jq .

# Get next cursor
NEXT_CURSOR=$(cat page1.json | jq -r '.next_cursor')

# Second page
curl "${API_URL}/results?job_id=${JOB_ID}&limit=10&cursor=${NEXT_CURSOR}" > page2.json
cat page2.json | jq .
```

### Filter by Bucket

```bash
curl "${API_URL}/results?bucket=my-bucket" | jq '.findings[] | {key, detector, masked_match}'
```

### Filter by Key Prefix

```bash
# Find all findings in logs/2025/11/
curl "${API_URL}/results?key=logs/2025/11/" | jq .
```

### Get Summary Statistics

```bash
JOB_ID="abc-123-def-456"

curl -s "${API_URL}/results?job_id=${JOB_ID}" | jq '{
  total_findings: .total,
  findings_shown: (.findings | length),
  has_more: .has_more
}'
```

### Count Findings by Detector Type

```bash
JOB_ID="abc-123-def-456"

curl -s "${API_URL}/results?job_id=${JOB_ID}" | \
  jq '.findings | group_by(.detector) | map({detector: .[0].detector, count: length})'
```

**Output:**
```json
[
  {"detector": "SSN", "count": 45},
  {"detector": "CREDIT_CARD", "count": 23},
  {"detector": "EMAIL", "count": 67},
  {"detector": "AWS_KEY", "count": 3}
]
```

## Complete Workflow Example

```bash
#!/bin/bash
# complete_workflow.sh

set -e

# Get API URL
cd terraform
API_URL=$(terraform output -raw api_gateway_url)
cd ..

echo "=== S3 Scanner Test Workflow ==="
echo "API URL: $API_URL"
echo ""

# 1. Trigger scan
echo "1. Triggering scan..."
SCAN_RESPONSE=$(curl -s -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "strac-scanner-demo-697547269674",
    "prefix": "test/"
  }')

JOB_ID=$(echo "$SCAN_RESPONSE" | jq -r '.job_id')
echo "   Job ID: $JOB_ID"
echo ""

# 2. Wait for listing to complete
echo "2. Waiting for S3 listing..."
while true; do
  STATUS=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.status')
  TOTAL=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.total')
  
  echo "   Status: $STATUS | Objects found: $TOTAL"
  
  if [ "$STATUS" != "listing" ]; then
    break
  fi
  
  sleep 3
done
echo ""

# 3. Monitor processing
echo "3. Monitoring scan progress..."
while true; do
  RESPONSE=$(curl -s "${API_URL}/jobs/${JOB_ID}")
  STATUS=$(echo "$RESPONSE" | jq -r '.status')
  PROGRESS=$(echo "$RESPONSE" | jq -r '.progress_percent')
  SUCCEEDED=$(echo "$RESPONSE" | jq -r '.succeeded')
  TOTAL=$(echo "$RESPONSE" | jq -r '.total')
  FINDINGS=$(echo "$RESPONSE" | jq -r '.total_findings')
  
  echo "   Progress: $PROGRESS% ($SUCCEEDED/$TOTAL) | Findings: $FINDINGS"
  
  if [ "$STATUS" = "completed" ]; then
    echo "   ✓ Scan completed!"
    break
  fi
  
  if [ "$STATUS" = "failed" ]; then
    echo "   ✗ Scan failed!"
    exit 1
  fi
  
  sleep 10
done
echo ""

# 4. Get results summary
echo "4. Results Summary:"
RESULTS=$(curl -s "${API_URL}/results?job_id=${JOB_ID}")
TOTAL_FINDINGS=$(echo "$RESULTS" | jq -r '.total')

echo "   Total Findings: $TOTAL_FINDINGS"
echo ""

# 5. Show findings by detector
echo "5. Findings by Detector Type:"
echo "$RESULTS" | jq -r '.findings | group_by(.detector) | 
  map("   " + .[0].detector + ": " + (length | tostring)) | .[]'
echo ""

# 6. Show sample findings
echo "6. Sample Findings (first 5):"
echo "$RESULTS" | jq -r '.findings[0:5] | .[] | 
  "   - \(.key): \(.detector) = \(.masked_match)"'
echo ""

echo "=== Workflow Complete ==="
```

## Error Handling Examples

### Invalid Bucket

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "non-existent-bucket"
  }'
```

**Response:**
```json
{
  "error": "Error starting Step Function: ..."
}
```

### Missing Bucket Parameter

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "prefix": "test/"
  }'
```

**Response:**
```json
{
  "error": "bucket is required"
}
```

### Job Not Found

```bash
curl "${API_URL}/jobs/non-existent-job-id"
```

**Response:**
```json
{
  "error": "Job not found"
}
```

## Testing with Different Scenarios

### Small Dataset (< 10K objects)

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "my-bucket",
    "prefix": "small-folder/"
  }'

# Expected: Completes in 1-2 minutes
```

### Medium Dataset (10K - 100K objects)

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "my-bucket",
    "prefix": "medium-folder/"
  }'

# Expected: 
# - Listing: 5-10 Step Functions iterations
# - Processing: 10-15 minutes
```

### Large Dataset (> 100K objects)

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "my-bucket",
    "prefix": "large-folder/"
  }'

# Expected:
# - Listing: 10-50 Step Functions iterations
# - Processing: 30-60 minutes depending on ECS scaling
```

### Empty Prefix (No Objects)

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "my-bucket",
    "prefix": "empty-folder/"
  }'

# Expected:
# {
#   "status": "completed",
#   "total": 0,
#   "message": "No objects found to scan"
# }
```

## Useful One-Liners

### Quick Scan and Wait

```bash
JOB_ID=$(curl -s -X POST "${API_URL}/scan" -H "Content-Type: application/json" \
  -d '{"bucket": "my-bucket", "prefix": "test/"}' | jq -r '.job_id') && \
echo "Job: $JOB_ID" && \
watch -n 5 "curl -s ${API_URL}/jobs/${JOB_ID} | jq '{status, progress_percent, total_findings}'"
```

### Get Latest Job Status

```bash
# Assuming jobs are returned in created_at order
curl -s "${API_URL}/results" | jq -r '.findings[0].job_id' | \
  xargs -I {} curl -s "${API_URL}/jobs/{}" | jq .
```

### Count Total Findings Across All Jobs

```bash
curl -s "${API_URL}/results?limit=1000" | jq '.total'
```

### Find All Files with SSN

```bash
curl -s "${API_URL}/results" | \
  jq -r '.findings[] | select(.detector == "SSN") | .key' | \
  sort -u
```

### Export Findings to CSV

```bash
curl -s "${API_URL}/results?job_id=${JOB_ID}" | \
  jq -r '.findings[] | [.key, .detector, .masked_match, .byte_offset] | @csv' > findings.csv

echo "Exported to findings.csv"
```

## Performance Testing

### Concurrent Scans

```bash
# Launch 5 scans in parallel
for i in {1..5}; do
  (
    echo "Starting scan $i"
    curl -s -X POST "${API_URL}/scan" \
      -H "Content-Type: application/json" \
      -d "{\"bucket\": \"my-bucket\", \"prefix\": \"test$i/\"}"
  ) &
done

wait
echo "All scans started"
```

### Measure API Response Time

```bash
time curl -s "${API_URL}/jobs/${JOB_ID}" > /dev/null
```

### Monitor Step Functions Progress

```bash
# Get execution ARN from job
EXEC_ARN=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.execution_arn')

# Describe execution
aws stepfunctions describe-execution \
  --execution-arn "$EXEC_ARN" \
  --query '{status: status, startDate: startDate, stopDate: stopDate}'
```

## Troubleshooting

### Check if API is Accessible

```bash
curl -I "${API_URL}/results"
# Should return: HTTP/2 200
```

### Test CORS

```bash
curl -X OPTIONS "${API_URL}/scan" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -v
```

### Verify Step Functions is Working

```bash
# After creating a scan, check Step Functions
EXEC_ARN=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.execution_arn')

aws stepfunctions describe-execution \
  --execution-arn "$EXEC_ARN"
```

### Check SQS Queue Depth

```bash
cd terraform
QUEUE_URL=$(terraform output -raw sqs_queue_url)

aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessagesVisible \
  --query 'Attributes.ApproximateNumberOfMessagesVisible'
```

## Summary

**Common Commands:**
```bash
# Scan
curl -X POST "${API_URL}/scan" -H "Content-Type: application/json" \
  -d '{"bucket": "my-bucket", "prefix": "path/"}'

# Status
curl "${API_URL}/jobs/${JOB_ID}" | jq '{status, progress_percent, total_findings}'

# Results
curl "${API_URL}/results?job_id=${JOB_ID}" | jq '.findings[] | {key, detector, masked_match}'
```

Save these examples and modify the bucket names and prefixes to match your actual S3 data!

