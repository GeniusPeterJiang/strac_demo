#!/bin/bash
# monitor_scaling.sh - Monitor ECS auto-scaling during load test

CLUSTER_NAME=$(cd ../terraform && terraform output -raw ecs_cluster_name)
SERVICE_NAME=$(cd ../terraform && terraform output -raw ecs_service_name)
QUEUE_URL=$(cd ../terraform && terraform output -raw sqs_queue_url)

echo "=== Auto-Scaling Monitor ==="
echo "Cluster: $CLUSTER_NAME"
echo "Service: $SERVICE_NAME"
echo ""
echo "Press Ctrl+C to stop"
echo ""

while true; do
  # Get ECS task count
  DESIRED=$(aws ecs describe-services \
    --cluster ${CLUSTER_NAME} \
    --services ${SERVICE_NAME} \
    --query 'services[0].desiredCount' \
    --output text)
  
  RUNNING=$(aws ecs describe-services \
    --cluster ${CLUSTER_NAME} \
    --services ${SERVICE_NAME} \
    --query 'services[0].runningCount' \
    --output text)
  
  # Get queue depth
  QUEUE_DEPTH=$(aws sqs get-queue-attributes \
    --queue-url ${QUEUE_URL} \
    --attribute-names ApproximateNumberOfMessages \
    --query 'Attributes.ApproximateNumberOfMessages' \
    --output text)
  
  # Calculate target (100 messages per task)
  TARGET_TASKS=$(((QUEUE_DEPTH + 99) / 100))
  
  printf "\r[%s] Tasks: %2d/%2d running | Queue: %6d msgs | Target: ~%2d tasks  " \
    "$(date +%T)" "$RUNNING" "$DESIRED" "$QUEUE_DEPTH" "$TARGET_TASKS"
  
  sleep 5
done

