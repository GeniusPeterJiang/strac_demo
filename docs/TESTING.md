# Testing Guide

This guide covers testing the S3 Sensitive Data Scanner system.

## Prerequisites

- AWS CLI configured
- Terraform deployed infrastructure
- Docker installed
- Python 3.12 installed
- Access to the deployed API Gateway endpoint

## 1. Prepare Test Data

### Upload Test Files to S3

Create a script to upload 500+ test files with various sensitive data patterns:

```bash
#!/bin/bash
# upload_test_files.sh
# Uploads 500+ small files to S3 for testing

BUCKET="s3-scanner-demo-697547269674"  # From Terraform output
REGION="us-west-2"
PREFIX="test/"  # Prefix for test files

echo "Generating and uploading test files..."

# Create test files with various sensitive data patterns
for i in {1..500}; do
  # Generate file with random sensitive data
  cat > /tmp/test_${i}.txt <<EOF
Test file number $i
Generated for S3 scanner testing

Sample data:
- SSN: 123-45-6789
- Credit Card: 4532-1234-5678-9010
- Email: user${i}@example.com
- Phone: (555) 123-4567
- AWS Key: AKIAIOSFODNN7EXAMPLE

Some random text: $(openssl rand -hex 20)
EOF
  
  # Upload to S3
  aws s3 cp /tmp/test_${i}.txt s3://${BUCKET}/${PREFIX}test_${i}.txt --region ${REGION} > /dev/null 2>&1
  
  # Progress indicator
  if [ $((i % 50)) -eq 0 ]; then
    echo "Uploaded $i files..."
  fi
done

# Upload additional files with specific patterns
echo "Uploading pattern-specific test files..."

# SSN files
for i in {1..50}; do
  echo "My SSN is 111-22-3333" > /tmp/ssn_${i}.txt
  aws s3 cp /tmp/ssn_${i}.txt s3://${BUCKET}/${PREFIX}ssn_${i}.txt --region ${REGION} > /dev/null 2>&1
done

# Credit card files (with valid Luhn numbers)
for i in {1..50}; do
  echo "Credit card: 4532-1234-5678-9010" > /tmp/cc_${i}.txt
  aws s3 cp /tmp/cc_${i}.txt s3://${BUCKET}/${PREFIX}cc_${i}.txt --region ${REGION} > /dev/null 2>&1
done

# Clean files (no sensitive data)
for i in {1..50}; do
  echo "This is a clean file with no sensitive data. File number $i." > /tmp/clean_${i}.txt
  aws s3 cp /tmp/clean_${i}.txt s3://${BUCKET}/${PREFIX}clean_${i}.txt --region ${REGION} > /dev/null 2>&1
done

echo ""
echo "Upload complete! Total files uploaded: 650+"
echo "Files are in s3://${BUCKET}/${PREFIX}"
```

Save as `upload_test_files.sh` and run:
```bash
chmod +x upload_test_files.sh
./upload_test_files.sh
```

**Alternative Python script** (if you prefer Python):

```python
#!/usr/bin/env python3
# upload_test_files.py
import boto3
import random
import string

s3 = boto3.client('s3', region_name='us-west-2')
bucket = 's3-scanner-demo-697547269674'
prefix = 'test/'

# Generate 500+ files
for i in range(1, 501):
    content = f"""Test file number {i}
Generated for S3 scanner testing

Sample data:
- SSN: 123-45-6789
- Credit Card: 4532-1234-5678-9010
- Email: user{i}@example.com
- Phone: (555) 123-4567
- AWS Key: AKIAIOSFODNN7EXAMPLE

Some random text: {''.join(random.choices(string.ascii_letters + string.digits, k=40))}
"""
    
    key = f"{prefix}test_{i:04d}.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=content)
    
    if i % 50 == 0:
        print(f"Uploaded {i} files...")

print(f"Upload complete! Uploaded 500 files to s3://{bucket}/{prefix}")
```

Run with: `python3 upload_test_files.py`

## 2. Test API Endpoints

### Get API Gateway URL

```bash
cd terraform
API_URL=$(terraform output -raw api_gateway_url)
echo "API URL: $API_URL"
```

### Test POST /scan

```bash
# Trigger a scan
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "s3-scanner-demo-697547269674",
    "prefix": "test/"
  }'

# Response should include job_id
# Save the job_id for next steps
JOB_ID="<job_id_from_response>"
```

### Test GET /jobs/{job_id}

```bash
# Check job status (poll until completion)
JOB_ID="<job_id_from_scan_response>"

# Poll job status until complete
while true; do
  RESPONSE=$(curl -s "${API_URL}/jobs/${JOB_ID}")
  echo "$RESPONSE" | jq .
  
  STATUS=$(echo "$RESPONSE" | jq -r '.succeeded // 0')
  TOTAL=$(echo "$RESPONSE" | jq -r '.total // 0')
  PROGRESS=$(echo "$RESPONSE" | jq -r '.progress_percent // 0')
  
  echo "Progress: ${PROGRESS}% (${STATUS}/${TOTAL} completed)"
  
  if [ "$(echo "$PROGRESS >= 100" | bc)" -eq 1 ]; then
    echo "Job completed!"
    break
  fi
  
  sleep 5
done
```

### Test GET /results

```bash
# Get all findings
curl "${API_URL}/results"

# Get findings for specific job
curl "${API_URL}/results?job_id=${JOB_ID}"

# Get findings with cursor-based pagination (recommended)
curl "${API_URL}/results?limit=10"
# Use next_cursor from response for next page
NEXT_CURSOR="<next_cursor_from_response>"
curl "${API_URL}/results?limit=10&cursor=${NEXT_CURSOR}"

# Get findings with offset-based pagination (alternative)
curl "${API_URL}/results?limit=10&offset=0"
curl "${API_URL}/results?limit=10&offset=10"

# Filter by bucket
curl "${API_URL}/results?bucket=s3-scanner-demo-697547269674"

# Filter by prefix (using key parameter)
curl "${API_URL}/results?key=test/"
```

## 3. Monitor Queue and Processing

### Check SQS Queue Depth

**Using AWS CLI:**

```bash
# Get queue URL from Terraform
cd terraform
QUEUE_URL=$(terraform output -raw sqs_queue_url)
DLQ_URL=$(terraform output -raw sqs_dlq_url)

# Get queue depth (ApproximateNumberOfMessagesVisible)
aws sqs get-queue-attributes \
  --queue-url ${QUEUE_URL} \
  --attribute-names ApproximateNumberOfMessagesVisible \
  --query 'Attributes.ApproximateNumberOfMessagesVisible' \
  --output text

# Get all queue attributes
aws sqs get-queue-attributes \
  --queue-url ${QUEUE_URL} \
  --attribute-names All

# Get message age (ApproximateAgeOfOldestMessage)
aws sqs get-queue-attributes \
  --queue-url ${QUEUE_URL} \
  --attribute-names ApproximateAgeOfOldestMessage \
  --query 'Attributes.ApproximateAgeOfOldestMessage' \
  --output text

# Check DLQ for failed messages
aws sqs get-queue-attributes \
  --queue-url ${DLQ_URL} \
  --attribute-names ApproximateNumberOfMessagesVisible \
  --query 'Attributes.ApproximateNumberOfMessagesVisible' \
  --output text
```

**Using AWS Console:**

1. Navigate to **SQS** in AWS Console
2. Click on the queue name: `s3-scanner-scan-jobs`
3. View the **Monitoring** tab to see:
   - **ApproximateNumberOfMessagesVisible** - Current queue depth
   - **ApproximateAgeOfOldestMessage** - Age of oldest message
   - **NumberOfMessagesReceived** - Total messages received
   - **NumberOfMessagesSent** - Total messages sent
4. For DLQ, click on `s3-scanner-scan-jobs-dlq` to see failed messages

**Continuous Monitoring Script:**

```bash
#!/bin/bash
# monitor_queue.sh
# Continuously monitor queue depth

QUEUE_URL=$(cd terraform && terraform output -raw sqs_queue_url)

while true; do
  DEPTH=$(aws sqs get-queue-attributes \
    --queue-url ${QUEUE_URL} \
    --attribute-names ApproximateNumberOfMessagesVisible \
    --query 'Attributes.ApproximateNumberOfMessagesVisible' \
    --output text)
  
  AGE=$(aws sqs get-queue-attributes \
    --queue-url ${QUEUE_URL} \
    --attribute-names ApproximateAgeOfOldestMessage \
    --query 'Attributes.ApproximateAgeOfOldestMessage' \
    --output text)
  
  echo "$(date): Queue depth: $DEPTH, Oldest message age: ${AGE}s"
  sleep 5
done
```

### View DLQ Messages

```bash
# Receive messages from DLQ (for inspection)
DLQ_URL=$(cd terraform && terraform output -raw sqs_dlq_url)

aws sqs receive-message \
  --queue-url ${DLQ_URL} \
  --max-number-of-messages 10 \
  --attribute-names All

# To see message body content:
aws sqs receive-message \
  --queue-url ${DLQ_URL} \
  --max-number-of-messages 1 \
  --query 'Messages[0].Body' \
  --output text | jq .
```

### Check ECS Service Status

```bash
CLUSTER_NAME=$(terraform output -raw ecs_cluster_name)
SERVICE_NAME=$(terraform output -raw ecs_service_name)

# Get service status
aws ecs describe-services \
  --cluster ${CLUSTER_NAME} \
  --services ${SERVICE_NAME}

# Get running tasks
aws ecs list-tasks \
  --cluster ${CLUSTER_NAME} \
  --service-name ${SERVICE_NAME}
```

### Check CloudWatch Logs

```bash
# View scanner logs
aws logs tail /ecs/s3-scanner-scanner --follow

# View Lambda API logs
aws logs tail /aws/lambda/s3-scanner-api --follow
```

## 4. Load Testing

### Create Large Test Dataset

```python
#!/usr/bin/env python3
# generate_test_data.py

import boto3
import random
import string

s3 = boto3.client('s3', region_name='us-west-2')
bucket = 's3-scanner-demo-697547269674'

# Generate 1000 files with random sensitive data
for i in range(1000):
    # Random SSN
    ssn = f"{random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(1000, 9999)}"
    
    # Random email
    email = f"user{random.randint(1, 10000)}@example.com"
    
    # Random phone
    phone = f"({random.randint(200, 999)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}"
    
    content = f"""
    Test file {i}
    SSN: {ssn}
    Email: {email}
    Phone: {phone}
    Some random text: {''.join(random.choices(string.ascii_letters, k=100))}
    """
    
    key = f"load-test/file_{i:05d}.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=content)
    print(f"Uploaded {key}")

print("Done!")
```

Run:
```bash
python3 generate_test_data.py
```

### Trigger Large Scan

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "s3-scanner-demo-697547269674",
    "prefix": "load-test/"
  }'
```

### Monitor Scaling

Watch ECS tasks scale up:
```bash
watch -n 5 "aws ecs describe-services --cluster ${CLUSTER_NAME} --services ${SERVICE_NAME} --query 'services[0].runningCount'"
```

Watch queue depth:
```bash
watch -n 5 "aws sqs get-queue-attributes --queue-url ${QUEUE_URL} --attribute-names ApproximateNumberOfMessagesVisible --query 'Attributes.ApproximateNumberOfMessagesVisible'"
```

## 5. Test Error Handling

### Test Invalid Bucket

```bash
curl -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "bucket": "non-existent-bucket"
  }'
```

### Test Dead Letter Queue

Force messages to DLQ by causing processing failures:

1. Temporarily break database connection in scanner code
2. Trigger a scan
3. Wait for messages to fail 3 times
4. Check DLQ:

```bash
DLQ_URL=$(terraform output -raw sqs_dlq_url)
aws sqs receive-message --queue-url ${DLQ_URL}
```

## 6. Database Verification

### Connect to Database

```bash
# Get RDS Proxy endpoint
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint)

# Connect via bastion (if enabled)
BASTION_IP=$(terraform output -raw bastion_public_ip)
ssh -L 5432:${RDS_ENDPOINT}:5432 ec2-user@${BASTION_IP}

# Then connect locally
psql -h localhost -U scanner_admin -d scanner_db
```

### Query Job Statistics

```sql
-- View all jobs
SELECT * FROM jobs ORDER BY created_at DESC LIMIT 10;

-- View job summary
SELECT * FROM job_summary ORDER BY created_at DESC LIMIT 10;

-- View findings by type
SELECT finding_type, COUNT(*) as count
FROM findings
GROUP BY finding_type
ORDER BY count DESC;

-- View findings for a specific job
SELECT * FROM findings
WHERE job_id = '<job_id>'
ORDER BY created_at DESC
LIMIT 100;
```

## 7. Performance Testing

### Measure Processing Throughput

```python
#!/usr/bin/env python3
# performance_test.py

import time
import requests
import json

API_URL = "https://<your-api-gateway-url>"

# Trigger scan
response = requests.post(
    f"{API_URL}/scan",
    json={"bucket": "s3-scanner-demo-697547269674", "prefix": "load-test/"}
)
job_id = response.json()["job_id"]
print(f"Job ID: {job_id}")

# Monitor progress
start_time = time.time()
last_count = 0

while True:
    response = requests.get(f"{API_URL}/jobs/{job_id}")
    data = response.json()
    
    succeeded = data.get("succeeded", 0)
    total = data.get("total_objects", 0)
    progress = data.get("progress_percent", 0)
    
    elapsed = time.time() - start_time
    rate = (succeeded - last_count) / max(elapsed - (time.time() - start_time), 1)
    
    print(f"Progress: {progress:.1f}% ({succeeded}/{total}) | "
          f"Rate: {rate:.2f} files/sec | Elapsed: {elapsed:.0f}s")
    
    if progress >= 100:
        break
    
    last_count = succeeded
    time.sleep(5)

total_time = time.time() - start_time
print(f"\nTotal time: {total_time:.0f}s")
print(f"Average rate: {succeeded/total_time:.2f} files/sec")
```

## 8. Integration Testing Script

```bash
#!/bin/bash
# integration_test.sh

set -e

API_URL=$(cd terraform && terraform output -raw api_gateway_url)
BUCKET="s3-scanner-demo-697547269674"

echo "=== Integration Test ==="
echo "API URL: $API_URL"
echo "Bucket: $BUCKET"
echo ""

# 1. Trigger scan
echo "1. Triggering scan..."
RESPONSE=$(curl -s -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\": \"${BUCKET}\", \"prefix\": \"test/\"}")

JOB_ID=$(echo $RESPONSE | jq -r '.job_id')
echo "Job ID: $JOB_ID"
echo ""

# 2. Wait for processing
echo "2. Waiting for processing..."
for i in {1..60}; do
  STATUS=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.status')
  PROGRESS=$(curl -s "${API_URL}/jobs/${JOB_ID}" | jq -r '.progress_percent')
  echo "  Status: $STATUS, Progress: $PROGRESS%"
  
  if [ "$STATUS" = "completed" ] || [ "$(echo "$PROGRESS >= 100" | bc)" -eq 1 ]; then
    break
  fi
  
  sleep 5
done
echo ""

# 3. Check results
echo "3. Checking results..."
RESULTS=$(curl -s "${API_URL}/results?job_id=${JOB_ID}")
FINDINGS_COUNT=$(echo $RESULTS | jq '.findings | length')
TOTAL=$(echo $RESULTS | jq '.total')

echo "Found $FINDINGS_COUNT findings (total: $TOTAL)"
echo ""

# 4. Verify findings
if [ "$TOTAL" -gt 0 ]; then
  echo "4. Sample findings:"
  echo $RESULTS | jq '.findings[0:3]'
  echo "✓ Test passed!"
else
  echo "4. No findings found"
  echo "⚠ Test may have failed or no sensitive data in test files"
fi
```

## 9. Cleanup Test Data

```bash
# Delete test files
aws s3 rm s3://s3-scanner-demo-697547269674/test/ --recursive
aws s3 rm s3://s3-scanner-demo-697547269674/bulk/ --recursive
aws s3 rm s3://s3-scanner-demo-697547269674/load-test/ --recursive
```

## 10. Continuous Monitoring

Set up CloudWatch dashboards to monitor:
- Queue depth over time
- ECS task count
- Processing rate (files/sec)
- Error rate
- RDS connection count
- Findings detected per hour

## Troubleshooting Test Issues

### API Returns 500 Error
- Check Lambda logs: `aws logs tail /aws/lambda/s3-scanner-api --follow`
- Verify environment variables are set correctly
- Check IAM permissions

### No Tasks Processing
- Verify ECS service is running: `aws ecs describe-services --cluster <cluster> --services <service>`
- Check SQS queue has messages
- Review ECS task logs for errors
- Verify RDS connectivity

### Slow Processing
- Check ECS task count (may need to increase max_capacity)
- Verify RDS Proxy is working
- Check S3 download speeds
- Review CloudWatch metrics for bottlenecks

