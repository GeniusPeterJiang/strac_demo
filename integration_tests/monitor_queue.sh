#!/bin/bash
# monitor_queue.sh - Real-time queue monitoring

QUEUE_URL=$(cd ../terraform && terraform output -raw sqs_queue_url)
DLQ_URL=$(cd ../terraform && terraform output -raw sqs_dlq_url)

echo "=== Queue Monitor (Ctrl+C to stop) ==="
echo ""

while true; do
  DEPTH=$(aws sqs get-queue-attributes \
    --queue-url ${QUEUE_URL} \
    --attribute-names ApproximateNumberOfMessages \
    --query 'Attributes.ApproximateNumberOfMessages' \
    --output text)
  
  AGE=$(aws sqs get-queue-attributes \
    --queue-url ${QUEUE_URL} \
    --attribute-names ApproximateAgeOfOldestMessage \
    --query 'Attributes.ApproximateAgeOfOldestMessage' \
    --output text 2>/dev/null || echo "0")
  
  IN_FLIGHT=$(aws sqs get-queue-attributes \
    --queue-url ${QUEUE_URL} \
    --attribute-names ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes.ApproximateNumberOfMessagesNotVisible' \
    --output text)
  
  DLQ_DEPTH=$(aws sqs get-queue-attributes \
    --queue-url ${DLQ_URL} \
    --attribute-names ApproximateNumberOfMessages \
    --query 'Attributes.ApproximateNumberOfMessages' \
    --output text)
  
  printf "\r[%s] Queue: %5d msgs | In-flight: %5d | Oldest: %4ds | DLQ: %3d" \
    "$(date +%T)" "$DEPTH" "$IN_FLIGHT" "$AGE" "$DLQ_DEPTH"
  
  sleep 2
done

