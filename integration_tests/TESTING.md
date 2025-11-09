# Integration Testing Guide

Complete end-to-end integration tests for the S3 Sensitive Data Scanner system.

## Available Test Scripts

All scripts are located in the `integration_tests/` directory and are ready to use:

| Script | Purpose | Usage |
|--------|---------|-------|
| `upload_test_files.sh` | Upload 500 test files (Bash) | `./upload_test_files.sh` |
| `upload_test_files.py` | Upload 500 test files (Python, faster) | `./upload_test_files.py` |
| `run_integration_test.sh` | **Complete end-to-end test** | `./run_integration_test.sh` |
| `monitor_queue.sh` | Real-time queue monitoring | `./monitor_queue.sh` |
| `monitor_scaling.sh` | Monitor ECS auto-scaling | `./monitor_scaling.sh` |
| `measure_throughput.sh` | Calculate processing speed | `./measure_throughput.sh <job_id>` |
| `cleanup_test_data.sh` | Remove all test files | `./cleanup_test_data.sh` |
| `generate_large_dataset.py` | Create 10,000 files for load testing | `./generate_large_dataset.py` |

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform infrastructure deployed (`terraform apply`)
- `jq` installed for JSON parsing:
  ```bash
  # Ubuntu/Debian
  sudo apt-get install jq
  
  # macOS
  brew install jq
  ```
- Python 3.6+ with `boto3` (for Python scripts):
  ```bash
  pip3 install boto3
  ```

## Quick Start: Complete Integration Test

Run the full end-to-end test in 3 simple steps:

### Step 1: Upload Test Files

Choose either Bash or Python version (Python is faster):

```bash
cd integration_tests/

# Option A: Bash (simpler)
./upload_test_files.sh

# Option B: Python (faster)
./upload_test_files.py
```

**What it does:**
- Automatically gets bucket name from Terraform
- Generates 500 files with realistic sensitive data patterns
- Uploads to S3 under `test/` prefix
- Shows progress every 100 files

**Expected output:**
```
=== Uploading Test Files ===
Bucket: s3://strac-scanner-demo-697547269674/test/

Generating 500 test files...
  Uploaded 100 files...
  Uploaded 200 files...
  Uploaded 300 files...
  Uploaded 400 files...
  Uploaded 500 files...

✓ Upload complete! Uploaded 500 files to s3://strac-scanner-demo-697547269674/test/
```

### Step 2: Run Integration Test

```bash
./run_integration_test.sh
```

**What it does:**
1. Gets configuration from Terraform (API URL, bucket, queue URLs)
2. Triggers scan via `POST /scan`
3. Monitors SQS queue depth
4. Polls `GET /jobs/{job_id}` every 5 seconds until complete
5. Fetches results via `GET /results`
6. Checks DLQ for failed messages
7. Provides pass/fail summary

**Expected output:**
```
=== Getting Configuration from Terraform ===
API URL: https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com
Bucket: strac-scanner-demo-697547269674
...

=== Step 1: Triggering Scan ===
✓ Scan job created successfully
  Job ID: 550e8400-e29b-41d4-a716-446655440000

=== Step 2: Monitoring SQS Queue ===
  Queue depth: 500 messages

=== Step 3: Polling Job Status ===
  [10:23:45] Progress: 45.2% | Processed: 226/500 | Findings: 1234 | Failed: 0
  ...
✓ Job completed!

=== Step 4: Fetching Results ===
  Findings in first page: 100
  Total findings: 2500
  
Sample findings (first 5):
{
  "bucket": "strac-scanner-demo-697547269674",
  "key": "test/test_001.txt",
  "detector": "ssn",
  "masked_match": "XXX-XX-6789"
}
...

=== Test Summary ===
✅ TEST PASSED - System working as expected!
```

The test **passes** if:
- ✅ More than 450 files processed successfully
- ✅ At least some findings detected
- ✅ No messages in DLQ

### Step 3: Cleanup (Optional)

```bash
./cleanup_test_data.sh
```

Removes all test files from S3 to avoid storage costs.

---

## Individual Scripts Usage

### Monitor Queue in Real-Time

Watch queue depth, in-flight messages, and DLQ in real-time:

```bash
./monitor_queue.sh
```

**Output:**
```
=== Queue Monitor (Ctrl+C to stop) ===

[10:23:45] Queue:   487 msgs | In-flight:    13 | Oldest:   45s | DLQ:   0
[10:23:47] Queue:   465 msgs | In-flight:    22 | Oldest:   47s | DLQ:   0
[10:23:49] Queue:   441 msgs | In-flight:    15 | Oldest:   49s | DLQ:   0
...
```

**Understanding the metrics:**
- **Queue**: Messages waiting to be processed
- **In-flight**: Messages currently being processed by workers (visibility timeout active)
- **Oldest**: Age of oldest message in queue (should stay < 10 minutes)
- **DLQ**: Failed messages (should stay at 0)

Press `Ctrl+C` to stop.

### Monitor ECS Auto-Scaling

Watch how ECS tasks scale up/down based on queue depth:

```bash
./monitor_scaling.sh
```

**Output:**
```
=== Auto-Scaling Monitor ===
Cluster: strac-scanner-cluster
Service: strac-scanner-scanner

[10:23:45] Tasks:  5/ 5 running | Queue:    487 msgs | Target: ~  5 tasks
[10:23:50] Tasks:  5/ 5 running | Queue:    465 msgs | Target: ~  5 tasks
[10:23:55] Tasks:  7/ 8 running | Queue:    823 msgs | Target: ~  8 tasks
```

**Understanding auto-scaling:**
- Target calculation: `queue_depth / 100` messages per task
- Scale-out happens when queue depth exceeds target
- Scale-in has 300-second cooldown to prevent thrashing

### Measure Processing Throughput

Calculate how fast the system processes files:

```bash
# Get job_id from previous scan
JOB_ID="550e8400-e29b-41d4-a716-446655440000"

./measure_throughput.sh $JOB_ID
```

**Output:**
```
=== Throughput Measurement ===
Job ID: 550e8400-e29b-41d4-a716-446655440000

Initial processed: 226
Starting timer...

Final processed: 346
Time elapsed: 60s
Files processed: 120

Throughput: 2.00 files/second
Projected hourly: 7200 files/hour
```

### Generate Large Dataset for Load Testing

Create 10,000 files for stress testing:

```bash
./generate_large_dataset.py
```

**What it does:**
- Uses parallel uploads (50 workers) for speed
- Creates files under `load-test/` prefix
- Takes approximately 2-3 minutes

**Expected output:**
```
=== Generating Large Dataset ===
Bucket: s3://strac-scanner-demo-697547269674/load-test/
Uploading 10,000 files (parallel upload)...

  Uploaded 1000 files...
  Uploaded 2000 files...
  ...
  Uploaded 10000 files...

✓ Upload complete! 10,000 files in s3://...
```

Then test with:
```bash
API_URL=$(cd ../terraform && terraform output -raw api_gateway_url)
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{"bucket": "your-bucket", "prefix": "load-test/"}'
```

---

## Manual Testing (Without Scripts)

If you prefer to test manually or need custom parameters, here are actual executable commands:

### Step 1: Create a Scan

Trigger a scan job (replace `test/` prefix if needed):

```bash
curl -X POST "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/scan" \
  -H "Content-Type: application/json" \
  -d '{"bucket": "strac-scanner-demo-697547269674", "prefix": "test/"}'
```

**Expected Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "listing",
  "execution_arn": "arn:aws:states:us-west-2:...",
  "message": "Job created. Objects are being listed asynchronously."
}
```

**Save the job_id** from the response - you'll need it for the next steps.

### Step 2: Check Job Status

Replace `YOUR_JOB_ID` with the actual job_id from Step 1:

```bash
# Single status check (cached data, faster)
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/jobs/YOUR_JOB_ID" | jq .

# Single status check (real-time data, always current)
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/jobs/YOUR_JOB_ID?real_time=true" | jq .

# Example with actual job_id (cached)
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/jobs/550e8400-e29b-41d4-a716-446655440000" | jq .

# Example with actual job_id (real-time)
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/jobs/550e8400-e29b-41d4-a716-446655440000?real_time=true" | jq .
```

**Expected Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "total": 500,
  "succeeded": 247,
  "failed": 0,
  "progress_percent": 49.4,
  "total_findings": 1234,
  "data_source": "cached",
  "cache_refreshed_at": "2025-11-09T10:23:00Z"
}
```

### Step 3: Poll Until Complete

Replace `YOUR_JOB_ID` with your actual job_id:

```bash
# Set your job_id
JOB_ID="550e8400-e29b-41d4-a716-446655440000"

# Poll every 5 seconds until complete (using real_time=true for live data)
while true; do
  RESPONSE=$(curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/jobs/${JOB_ID}?real_time=true")
  PROGRESS=$(echo "$RESPONSE" | jq -r '.progress_percent // 0')
  STATUS=$(echo "$RESPONSE" | jq -r '.status')
  SUCCEEDED=$(echo "$RESPONSE" | jq -r '.succeeded // 0')
  TOTAL=$(echo "$RESPONSE" | jq -r '.total // 0')
  
  echo "[$(date +%T)] Status: $STATUS | Progress: ${PROGRESS}% | Processed: ${SUCCEEDED}/${TOTAL}"
  
  if [ "$(echo "$PROGRESS >= 100" | bc)" -eq 1 ] || [ "$STATUS" = "completed" ]; then
    echo "✓ Job completed!"
    break
  fi
  
  sleep 5
done
```

### Step 4: Fetch Results

**Note:** The `/results` endpoint does not support `job_id` parameter. Use `bucket` filter instead.

```bash
# Get all findings for the bucket (first 100)
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/results?bucket=strac-scanner-demo-697547269674" | jq .

# With pagination (10 results per page)
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/results?bucket=strac-scanner-demo-697547269674&limit=10" | jq .

# Get next page using cursor from previous response
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/results?limit=10&cursor=12345" | jq .

# Filter by bucket
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/results?bucket=strac-scanner-demo-697547269674" | jq .

# Filter by key prefix (use with bucket)
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/results?bucket=strac-scanner-demo-697547269674&key=test/" | jq .

# Group findings by detector type
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/results?bucket=strac-scanner-demo-697547269674" | jq '.findings | group_by(.detector) | map({detector: .[0].detector, count: length})'
```

**Expected Response:**
```json
{
  "findings": [
    {
      "bucket": "strac-scanner-demo-697547269674",
      "key": "test/test_001.txt",
      "detector": "ssn",
      "masked_match": "XXX-XX-6789",
      "context": "Sample sensitive data:\n- SSN: XXX-XX-6789\n- Credit Card:",
      "byte_offset": 145
    },
    {
      "bucket": "strac-scanner-demo-697547269674",
      "key": "test/test_001.txt",
      "detector": "credit_card",
      "masked_match": "4532-XXXX-XXXX-9010",
      "context": "- SSN: XXX-XX-6789\n- Credit Card: 4532-XXXX-XXXX-9010\n- Email:",
      "byte_offset": 178
    }
  ],
  "total": 2500,
  "has_more": true,
  "next_cursor": "12345"
}
```

### Step 5: Real-Time vs Cached Data

**Cached data (default, faster):**
```bash
# Uses materialized view, refreshed every 1 minute
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/jobs/550e8400-e29b-41d4-a716-446655440000" | jq .
```

**Real-time data (slower, always current):**
```bash
# Bypasses cache, queries database directly
curl -s "https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com/jobs/550e8400-e29b-41d4-a716-446655440000?real_time=true" | jq .
```

⚠️ **Note:** 
- **Cached data** is faster (6000× faster for large jobs) but may be up to 1 minute old
- **Real-time data** is always current but slower for jobs with millions of objects
- **For polling during active processing**, use `real_time=true` to see live updates
- **For one-time checks**, cached data is usually sufficient

### Quick Reference Commands

```bash
# Set these variables for easy copy-paste
API_URL="https://j3k85zn5ue.execute-api.us-west-2.amazonaws.com"
BUCKET="strac-scanner-demo-697547269674"
JOB_ID="YOUR_JOB_ID_HERE"

# Trigger scan
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\": \"${BUCKET}\", \"prefix\": \"test/\"}"

# Check status (cached, faster)
curl -s "${API_URL}/jobs/${JOB_ID}" | jq .

# Check status (real-time, always current)
curl -s "${API_URL}/jobs/${JOB_ID}?real_time=true" | jq .

# Get results (filter by bucket, job_id parameter not supported)
curl -s "${API_URL}/results?bucket=${BUCKET}" | jq .
```

### Check Queue Depth and DLQ

```bash
# Main queue depth
aws sqs get-queue-attributes \
  --queue-url ${QUEUE_URL} \
  --attribute-names ApproximateNumberOfMessages,ApproximateAgeOfOldestMessage \
  --query 'Attributes' \
  --output table

# DLQ depth
aws sqs get-queue-attributes \
  --queue-url ${DLQ_URL} \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes' \
  --output table

# View DLQ messages (if any)
aws sqs receive-message \
  --queue-url ${DLQ_URL} \
  --max-number-of-messages 10 \
  --attribute-names All | jq '.Messages[] | {MessageId, Body: .Body | fromjson}'
```

---

## Using AWS Console

### View SQS Queue Status

1. **Navigate to SQS Console:**
   - AWS Console → Services → SQS
   - Region: `us-west-2` (or your configured region)

2. **Main Queue** (`strac-scanner-scan-jobs`):
   - Click on queue name
   - **Messages Available**: Current queue depth
   - **Messages in Flight**: Being processed by workers
   - Click **Monitoring** tab to see:
     - `ApproximateNumberOfMessages` - Queue depth over time
     - `ApproximateAgeOfOldestMessage` - Message age
     - `NumberOfMessagesSent/Received` - Throughput

3. **Dead Letter Queue** (`strac-scanner-scan-jobs-dlq`):
   - Click on DLQ queue name
   - **Messages Available**: Failed message count (should be 0)
   - Click **Send and receive messages** → **Poll for messages** to inspect
   - Each message shows:
     - Original message body (job_id, bucket, key)
     - `ApproximateReceiveCount` - Number of retry attempts (max 3)
     - Timestamps

4. **CloudWatch Alarms:**
   - Monitoring tab → **View all CloudWatch alarms**
   - Pre-configured alarms:
     - `strac-scanner-sqs-queue-depth` - Alerts when queue > 1000
     - `strac-scanner-sqs-message-age` - Alerts when age > 10 minutes

### View ECS Service Status

1. **Navigate to ECS Console:**
   - AWS Console → Services → ECS
   - Click cluster: `strac-scanner-cluster`

2. **Service Details:**
   - Click service: `strac-scanner-scanner`
   - View:
     - **Desired tasks** vs **Running tasks**
     - **Task definition** version
     - **Auto Scaling** configuration

3. **Tasks Tab:**
   - See all running tasks
   - Click task ID to view:
     - Container status
     - CloudWatch logs link
     - CPU/Memory utilization

4. **Metrics Tab:**
   - CPU utilization over time
   - Memory utilization
   - Task count changes (auto-scaling)

### View CloudWatch Logs

1. **Navigate to CloudWatch:**
   - AWS Console → Services → CloudWatch → Log groups

2. **Available Log Groups:**
   - `/ecs/strac-scanner-scanner` - Worker processing logs
   - `/aws/lambda/strac-scanner-api` - API requests
   - `/aws/stepfunctions/strac-scanner-s3-scanner` - S3 listing progress

3. **View Logs:**
   - Click log group → Latest log stream
   - Use filter patterns to find errors: `?ERROR ?WARN`
   - Click **Actions** → **Create metric filter** for custom metrics

---

## Advanced Testing

### Load Test with 10,000 Files

```bash
# 1. Generate large dataset
./generate_large_dataset.py

# 2. Trigger scan
API_URL=$(cd ../terraform && terraform output -raw api_gateway_url)
BUCKET=$(cd ../terraform && terraform output -raw s3_bucket_name)

RESPONSE=$(curl -s -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\": \"${BUCKET}\", \"prefix\": \"load-test/\"}")

JOB_ID=$(echo $RESPONSE | jq -r '.job_id')
echo "Load test job ID: $JOB_ID"

# 3. Monitor in separate terminals
# Terminal 1: Monitor queue
./monitor_queue.sh

# Terminal 2: Monitor auto-scaling
./monitor_scaling.sh

# Terminal 3: Poll job status
watch -n 5 "curl -s \"${API_URL}/jobs/${JOB_ID}\" | jq '{status, total, succeeded, failed, progress_percent}'"
```

### Database Verification

Connect to database via bastion host:

```bash
# Get credentials
cd terraform/
BASTION_IP=$(terraform output -raw bastion_public_ip)
DB_ENDPOINT=$(terraform output -raw rds_proxy_endpoint)
DB_USERNAME=$(terraform output -raw rds_master_username)

# SSH to bastion
ssh -i ~/.ssh/your-key.pem ubuntu@${BASTION_IP}

# Connect to database
psql -h ${DB_ENDPOINT} -U ${DB_USERNAME} -d scanner
```

**Useful queries:**

```sql
-- Check job status
SELECT 
  job_id,
  bucket,
  status,
  created_at,
  (SELECT COUNT(*) FROM job_objects WHERE job_id = jobs.job_id) as total,
  (SELECT COUNT(*) FROM job_objects WHERE job_id = jobs.job_id AND status = 'succeeded') as succeeded,
  (SELECT COUNT(*) FROM findings WHERE job_id = jobs.job_id) as findings
FROM jobs
ORDER BY created_at DESC
LIMIT 10;

-- Findings breakdown by detector
SELECT 
  detector,
  COUNT(*) as count,
  COUNT(DISTINCT bucket) as buckets,
  COUNT(DISTINCT key) as files
FROM findings
GROUP BY detector
ORDER BY count DESC;

-- Processing status for a job
SELECT 
  status,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage
FROM job_objects
WHERE job_id = 'YOUR_JOB_ID'
GROUP BY status;

-- View cached progress (fast query)
SELECT * FROM job_progress_cache
WHERE job_id = 'YOUR_JOB_ID';
```

### CloudWatch Metrics

```bash
# Queue depth over last hour
aws cloudwatch get-metric-statistics \
  --namespace AWS/SQS \
  --metric-name ApproximateNumberOfMessages \
  --dimensions Name=QueueName,Value=strac-scanner-scan-jobs \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average,Maximum \
  --output table

# ECS task count over last hour
CLUSTER_NAME=$(cd terraform && terraform output -raw ecs_cluster_name)
SERVICE_NAME=$(cd terraform && terraform output -raw ecs_service_name)

aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name RunningTaskCount \
  --dimensions Name=ClusterName,Value=${CLUSTER_NAME} Name=ServiceName,Value=${SERVICE_NAME} \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average,Maximum \
  --output table
```

---

## Troubleshooting

### API Returns Invalid JSON or HTTP Error

**Symptoms:**
- `jq: parse error: Invalid numeric literal`
- Non-JSON response (HTML, plain text, or error message)

**Debug Steps:**

1. **Test API connectivity:**
```bash
# Get API URL
API_URL=$(cd terraform && terraform output -raw api_gateway_url)

# Test with verbose output
curl -v -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{"bucket": "strac-scanner-demo-697547269674", "prefix": "test/"}'
```

2. **Check Lambda function logs:**
```bash
# View recent errors
aws logs tail /aws/lambda/strac-scanner-api --since 5m --filter-pattern "ERROR"

# View all recent logs
aws logs tail /aws/lambda/strac-scanner-api --since 5m --follow
```

3. **Verify Lambda exists:**
```bash
FUNCTION_NAME=$(cd terraform && terraform output -raw lambda_api_function_name)
aws lambda get-function --function-name ${FUNCTION_NAME}
```

4. **Check API Gateway:**
```bash
# List APIs
aws apigatewayv2 get-apis --query 'Items[?Name==`strac-scanner-api`]'
```

**Common Causes:**
- Lambda function not deployed: Run `./build_and_push.sh`
- Lambda runtime error: Check CloudWatch logs
- API Gateway integration issue: Redeploy with `terraform apply`
- Wrong API URL: Verify with `terraform output api_gateway_url`

### Test Failed - No Findings Detected

**Possible causes:**
1. Test files didn't upload properly
2. Workers aren't processing messages
3. Detector patterns not matching

**Solutions:**
```bash
# 1. Verify files uploaded
BUCKET=$(cd terraform && terraform output -raw s3_bucket_name)
aws s3 ls s3://${BUCKET}/test/ | wc -l
# Should show 500 files

# 2. Check if workers are running
CLUSTER_NAME=$(cd terraform && terraform output -raw ecs_cluster_name)
SERVICE_NAME=$(cd terraform && terraform output -raw ecs_service_name)
aws ecs describe-services \
  --cluster ${CLUSTER_NAME} \
  --services ${SERVICE_NAME} \
  --query 'services[0].{runningCount: runningCount, desiredCount: desiredCount}'

# 3. Check worker logs for errors
aws logs tail /ecs/strac-scanner-scanner --since 10m
```

### Messages Stuck in DLQ

**Investigate failed messages:**
```bash
DLQ_URL=$(cd terraform && terraform output -raw sqs_dlq_url)

# View failed messages
aws sqs receive-message \
  --queue-url ${DLQ_URL} \
  --max-number-of-messages 10 \
  --attribute-names All | jq '.Messages[] | {
    Body: .Body | fromjson,
    ApproximateReceiveCount: .Attributes.ApproximateReceiveCount,
    SentTimestamp: .Attributes.SentTimestamp
  }'
```

**Common causes:**
- S3 object deleted during processing
- Insufficient IAM permissions
- Worker crashes/timeouts
- Network issues

### Slow Processing

**Check if auto-scaling is working:**
```bash
# View scaling activities
CLUSTER_NAME=$(cd terraform && terraform output -raw ecs_cluster_name)
SERVICE_NAME=$(cd terraform && terraform output -raw ecs_service_name)

aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs \
  --resource-id service/${CLUSTER_NAME}/${SERVICE_NAME} \
  --max-results 10

# Check current vs max capacity
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs \
  --resource-ids service/${CLUSTER_NAME}/${SERVICE_NAME}
```

**Solutions:**
- Increase `ecs_max_capacity` in Terraform variables
- Check CloudWatch logs for worker errors
- Verify queue depth is increasing (triggering scale-out)

### API Returns 500 Error

**Check Lambda logs:**
```bash
aws logs tail /aws/lambda/strac-scanner-api --follow --since 5m --filter-pattern "ERROR"
```

**Common causes:**
- Invalid bucket name (bucket doesn't exist)
- Lambda timeout (shouldn't happen with Step Functions)
- Database connection issues
- IAM permission issues

---

## Best Practices

1. **Always run cleanup after testing** - Avoids S3 storage costs
   ```bash
   ./cleanup_test_data.sh
   ```

2. **Monitor queue during tests** - Verify workers are processing
   ```bash
   ./monitor_queue.sh
   ```

3. **Use cached data for large jobs** - Much faster than real-time
   ```bash
   # Cached (fast)
   curl "${API_URL}/jobs/${JOB_ID}"
   
   # Real-time (slow for large jobs)
   curl "${API_URL}/jobs/${JOB_ID}?real_time=true"
   ```

4. **Check DLQ after each test** - Identify systematic failures early

5. **Test with various file sizes** - Validates edge case handling
   - Small files (< 1 KB)
   - Medium files (1-10 MB)
   - Large files (close to 100 MB limit)

6. **Load test before production** - Verify system handles expected scale
   ```bash
   ./generate_large_dataset.py  # 10,000 files
   ```

7. **Use bastion for DB access only** - Never expose RDS publicly

---

## Script Reference

### Environment Variables

All scripts automatically read from Terraform outputs. To override:

```bash
export API_URL="https://custom-api.example.com"
export BUCKET="custom-bucket-name"
export QUEUE_URL="https://sqs.us-west-2.amazonaws.com/..."
export DLQ_URL="https://sqs.us-west-2.amazonaws.com/..."
```

### Exit Codes

- `0` - Success
- `1` - Test failed or error occurred

### Script Dependencies

| Script | Requires |
|--------|----------|
| `*.sh` | bash, aws-cli, jq, bc |
| `*.py` | python3, boto3 |
| `run_integration_test.sh` | Previous upload + jq |
| `measure_throughput.sh` | Active job_id |

---

## Additional Resources

- [README.md](../README.md) - Architecture overview and API documentation
- [DEVELOPMENT.md](../DEVELOPMENT.md) - Deployment and configuration guide
- [SCALING.md](../SCALING.md) - Capacity planning and optimization strategies
- [scanner/LOCAL_TESTING.md](../scanner/LOCAL_TESTING.md) - Local unit testing (no AWS)

---

## Quick Reference

```bash
# Complete test (3 commands)
./upload_test_files.sh
./run_integration_test.sh
./cleanup_test_data.sh

# Monitoring (run in separate terminals)
./monitor_queue.sh        # Queue depth
./monitor_scaling.sh      # ECS tasks

# Load testing
./generate_large_dataset.py
# ... trigger scan via API ...
./measure_throughput.sh <job_id>

# Get configuration
cd terraform/
terraform output
```
