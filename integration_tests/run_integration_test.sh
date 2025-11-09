#!/bin/bash
# run_integration_test.sh - Complete end-to-end integration test

set -e

# Get configuration from Terraform
echo "=== Getting Configuration from Terraform ==="
cd ../terraform
API_URL=$(terraform output -raw api_gateway_url)
BUCKET=$(terraform output -raw s3_bucket_name)
QUEUE_URL=$(terraform output -raw sqs_queue_url)
DLQ_URL=$(terraform output -raw sqs_dlq_url)
cd ../integration_tests

echo "API URL: $API_URL"
echo "Bucket: $BUCKET"
echo "Queue URL: $QUEUE_URL"
echo "DLQ URL: $DLQ_URL"
echo ""

# Step 1: Trigger Scan
echo "=== Step 1: Triggering Scan ==="
HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/scan" \
  -H "Content-Type: application/json" \
  -d "{\"bucket\": \"${BUCKET}\", \"prefix\": \"test/\"}")

# Extract body and status code
RESPONSE=$(echo "$HTTP_RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$HTTP_RESPONSE" | tail -n 1)

echo "HTTP Status: $HTTP_CODE"

# Check if response is valid JSON
if ! echo "$RESPONSE" | jq . > /dev/null 2>&1; then
  echo "❌ API returned invalid JSON response:"
  echo "$RESPONSE"
  echo ""
  echo "Possible issues:"
  echo "  - API Gateway not deployed or misconfigured"
  echo "  - Lambda function error"
  echo "  - Check Lambda logs: aws logs tail /aws/lambda/strac-scanner-api --since 5m"
  exit 1
fi

echo "Response:"
echo "$RESPONSE" | jq .

JOB_ID=$(echo $RESPONSE | jq -r '.job_id')
EXECUTION_ARN=$(echo $RESPONSE | jq -r '.execution_arn // empty')

if [ -z "$JOB_ID" ] || [ "$JOB_ID" = "null" ]; then
  echo "❌ Failed to create scan job"
  echo "Response does not contain a valid job_id"
  exit 1
fi

echo ""
echo "✓ Scan job created successfully"
echo "  Job ID: $JOB_ID"
echo "  Execution ARN: $EXECUTION_ARN"
echo ""

# Step 2: Monitor Queue Depth
echo "=== Step 2: Monitoring SQS Queue ==="
echo "Waiting for messages to be enqueued..."
sleep 5

QUEUE_DEPTH=$(aws sqs get-queue-attributes \
  --queue-url ${QUEUE_URL} \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

echo "  Queue depth: $QUEUE_DEPTH messages"
echo "  Workers will start processing these messages..."
echo ""

# Step 3: Poll Job Status Until Completion
echo "=== Step 3: Polling Job Status ==="
echo "Waiting for job to complete (this may take several minutes)..."
echo ""

MAX_POLLS=120  # 10 minutes max (120 * 5s)
POLL_COUNT=0

while [ $POLL_COUNT -lt $MAX_POLLS ]; do
  # Get job status with real_time=true for live data
  JOB_RESPONSE=$(curl -s "${API_URL}/jobs/${JOB_ID}?real_time=true")
  
  STATUS=$(echo $JOB_RESPONSE | jq -r '.status // "unknown"')
  TOTAL=$(echo $JOB_RESPONSE | jq -r '.total // 0')
  SUCCEEDED=$(echo $JOB_RESPONSE | jq -r '.succeeded // 0')
  FAILED=$(echo $JOB_RESPONSE | jq -r '.failed // 0')
  PROGRESS=$(echo $JOB_RESPONSE | jq -r '.progress_percent // 0')
  
  # Display progress (without findings count)
  printf "\r  [%s] Progress: %.1f%% | Processed: %d/%d | Failed: %d" \
    "$(date +%T)" "$PROGRESS" "$SUCCEEDED" "$TOTAL" "$FAILED"
  
  # Check if complete
  # Use awk for floating point comparison (more reliable than bc)
  PROGRESS_COMPLETE=0
  if [ ! -z "$PROGRESS" ] && [ "$PROGRESS" != "null" ]; then
    PROGRESS_COMPLETE=$(echo "$PROGRESS" | awk '{if ($1 >= 99.9) print 1; else print 0}')
  fi
  
  if [ "$STATUS" = "completed" ] || [ "$PROGRESS_COMPLETE" -eq 1 ]; then
    echo ""
    echo ""
    echo "✓ Job completed!"
    break
  fi
  
  # Check for errors
  if [ "$STATUS" = "failed" ]; then
    echo ""
    echo "❌ Job failed!"
    echo "$JOB_RESPONSE" | jq .
    exit 1
  fi
  
  sleep 5
  POLL_COUNT=$((POLL_COUNT + 1))
done

if [ $POLL_COUNT -ge $MAX_POLLS ]; then
  echo ""
  echo "⚠ Timeout waiting for job completion"
  echo "  Current status: $STATUS ($PROGRESS% complete)"
fi

echo ""

# Step 4: Fetch Results
echo "=== Step 4: Fetching Results ==="
# Filter by bucket since job_id parameter may not be supported
RESULTS=$(curl -s "${API_URL}/results?bucket=${BUCKET}&limit=100")

FINDINGS_COUNT=$(echo $RESULTS | jq '.findings | length')
TOTAL_FINDINGS=$(echo $RESULTS | jq -r '.total // 0')
HAS_MORE=$(echo $RESULTS | jq -r '.has_more // false')

echo "  Findings in first page: $FINDINGS_COUNT"
echo "  Total findings: $TOTAL_FINDINGS"
echo "  Has more pages: $HAS_MORE"
echo ""

# Display sample findings
if [ "$FINDINGS_COUNT" -gt 0 ]; then
  echo "Sample findings (first 5):"
  echo $RESULTS | jq '.findings[0:5] | .[] | {bucket, key, detector, masked_match}' 
  echo ""
  
  # Breakdown by detector type
  echo "Findings by detector type:"
  echo $RESULTS | jq -r '.findings | group_by(.detector) | .[] | "\(.[0].detector): \(length)"' | sort | uniq -c
else
  echo "⚠ No findings detected"
fi

echo ""

# Step 5: Check Queue Status
echo "=== Step 5: Checking Queue Status ==="

QUEUE_DEPTH=$(aws sqs get-queue-attributes \
  --queue-url ${QUEUE_URL} \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

DLQ_DEPTH=$(aws sqs get-queue-attributes \
  --queue-url ${DLQ_URL} \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

echo "  Main queue depth: $QUEUE_DEPTH messages"
echo "  DLQ depth: $DLQ_DEPTH messages"

if [ "$DLQ_DEPTH" -gt 0 ]; then
  echo "  ⚠ Warning: $DLQ_DEPTH messages in DLQ (some processing failed)"
else
  echo "  ✓ No messages in DLQ (all processing successful)"
fi

echo ""

# Step 6: Summary
echo "=== Test Summary ==="
echo "✓ Integration test completed successfully"
echo ""
echo "Job Details:"
echo "  Job ID: $JOB_ID"
echo "  Status: $STATUS"
echo "  Total files: $TOTAL"
echo "  Successfully processed: $SUCCEEDED"
echo "  Failed: $FAILED"
echo ""
echo "Queue Status:"
echo "  Main queue: $QUEUE_DEPTH messages remaining"
echo "  Dead letter queue: $DLQ_DEPTH messages"
echo ""

if [ "$SUCCEEDED" -gt 450 ] && [ "$TOTAL_FINDINGS" -gt 0 ]; then
  echo "✅ TEST PASSED - System working as expected!"
  exit 0
else
  echo "⚠ TEST WARNING - Review results above"
  exit 1
fi

