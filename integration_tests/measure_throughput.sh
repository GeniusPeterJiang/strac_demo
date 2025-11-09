#!/bin/bash
# measure_throughput.sh - Calculate processing throughput

if [ -z "$1" ]; then
  echo "Usage: ./measure_throughput.sh <job_id>"
  exit 1
fi

JOB_ID="$1"
API_URL=$(cd ../terraform && terraform output -raw api_gateway_url)

echo "=== Throughput Measurement ==="
echo "Job ID: $JOB_ID"
echo ""

# Initial state
START_TIME=$(date +%s)
START_RESPONSE=$(curl -s "${API_URL}/jobs/${JOB_ID}")
START_COUNT=$(echo $START_RESPONSE | jq -r '.succeeded // 0')

echo "Initial processed: $START_COUNT"
echo "Starting timer..."
echo ""

# Wait 60 seconds
sleep 60

# Final state
END_TIME=$(date +%s)
END_RESPONSE=$(curl -s "${API_URL}/jobs/${JOB_ID}")
END_COUNT=$(echo $END_RESPONSE | jq -r '.succeeded // 0')

# Calculate throughput
ELAPSED=$((END_TIME - START_TIME))
PROCESSED=$((END_COUNT - START_COUNT))
RATE=$(echo "scale=2; $PROCESSED / $ELAPSED" | bc)

echo "Final processed: $END_COUNT"
echo "Time elapsed: ${ELAPSED}s"
echo "Files processed: $PROCESSED"
echo ""
echo "Throughput: ${RATE} files/second"
echo "Projected hourly: $(echo "$RATE * 3600" | bc) files/hour"

