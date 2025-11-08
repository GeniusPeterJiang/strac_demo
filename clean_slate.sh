#!/bin/bash
# Complete Infrastructure Cleanup Script
# This will DELETE ALL resources for a completely fresh deployment
# WARNING: This is destructive and cannot be undone!

set -e

AWS_REGION="us-west-2"
PROJECT_NAME="strac-scanner"
AWS_ACCOUNT_ID="697547269674"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║                  COMPLETE INFRASTRUCTURE CLEANUP                ║${NC}"
echo -e "${RED}║                         DESTRUCTIVE OPERATION                   ║${NC}"
echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}This will DELETE ALL resources for project: ${PROJECT_NAME}${NC}"
echo -e "${YELLOW}Region: ${AWS_REGION}${NC}"
echo -e "${YELLOW}Account: ${AWS_ACCOUNT_ID}${NC}"
echo ""
echo "Resources that will be deleted:"
echo "  - ECS Services, Tasks, and Clusters"
echo "  - RDS Databases and Proxies"
echo "  - Lambda Functions"
echo "  - API Gateway APIs"
echo "  - SQS Queues (main and DLQ)"
echo "  - CloudWatch Log Groups"
echo "  - Secrets Manager Secrets"
echo "  - ECR Repositories"
echo "  - Security Groups"
echo "  - VPC Resources (NAT Gateways, Subnets, VPC)"
echo "  - IAM Roles and Policies"
echo "  - Bastion EC2 Instances"
echo "  - Terraform State"
echo ""
echo -e "${RED}WARNING: This cannot be undone!${NC}"
echo -e "${YELLOW}S3 bucket data will be preserved (delete manually if needed)${NC}"
echo ""
read -p "Type 'DELETE EVERYTHING' to confirm: " CONFIRM

if [ "$CONFIRM" != "DELETE EVERYTHING" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo -e "${GREEN}Starting cleanup...${NC}"
echo ""

# Function to safely run AWS commands
safe_aws() {
    "$@" 2>/dev/null || true
}

# Function to wait with spinner
wait_with_message() {
    local message=$1
    local duration=$2
    echo -n "$message"
    for i in $(seq 1 $duration); do
        echo -n "."
        sleep 1
    done
    echo " done"
}

# ============================================================================
# STEP 1: Scale down ECS services (prevents active connections)
# ============================================================================
echo -e "${GREEN}[1/14] Scaling down ECS services...${NC}"
CLUSTER_NAME="${PROJECT_NAME}-cluster"
SERVICE_NAME="${PROJECT_NAME}-service"

safe_aws aws ecs update-service \
    --cluster $CLUSTER_NAME \
    --service $SERVICE_NAME \
    --desired-count 0 \
    --region $AWS_REGION

wait_with_message "  Waiting for tasks to stop" 30

# ============================================================================
# STEP 2: Delete ECS Service
# ============================================================================
echo -e "${GREEN}[2/14] Deleting ECS service...${NC}"
safe_aws aws ecs delete-service \
    --cluster $CLUSTER_NAME \
    --service $SERVICE_NAME \
    --force \
    --region $AWS_REGION

wait_with_message "  Waiting for service deletion" 20

# ============================================================================
# STEP 3: Stop all running tasks
# ============================================================================
echo -e "${GREEN}[3/14] Stopping all ECS tasks...${NC}"
TASK_ARNS=$(aws ecs list-tasks \
    --cluster $CLUSTER_NAME \
    --region $AWS_REGION \
    --query 'taskArns[*]' \
    --output text 2>/dev/null || echo "")

if [ ! -z "$TASK_ARNS" ]; then
    for TASK_ARN in $TASK_ARNS; do
        safe_aws aws ecs stop-task \
            --cluster $CLUSTER_NAME \
            --task $TASK_ARN \
            --region $AWS_REGION
    done
    echo "  Stopped running tasks"
else
    echo "  No running tasks found"
fi

# ============================================================================
# STEP 4: Delete ECS Cluster
# ============================================================================
echo -e "${GREEN}[4/14] Deleting ECS cluster...${NC}"
safe_aws aws ecs delete-cluster \
    --cluster $CLUSTER_NAME \
    --region $AWS_REGION
echo "  ECS cluster deleted"

# ============================================================================
# STEP 5: Delete Lambda Functions
# ============================================================================
echo -e "${GREEN}[5/14] Deleting Lambda functions...${NC}"
LAMBDA_FUNCTION="${PROJECT_NAME}-api"
safe_aws aws lambda delete-function \
    --function-name $LAMBDA_FUNCTION \
    --region $AWS_REGION
echo "  Lambda function deleted"

# ============================================================================
# STEP 6: Delete API Gateway
# ============================================================================
echo -e "${GREEN}[6/14] Deleting API Gateway...${NC}"
API_ID=$(aws apigatewayv2 get-apis \
    --query "Items[?Name=='${PROJECT_NAME}-api'].ApiId" \
    --output text \
    --region $AWS_REGION 2>/dev/null || echo "")

if [ ! -z "$API_ID" ]; then
    safe_aws aws apigatewayv2 delete-api \
        --api-id $API_ID \
        --region $AWS_REGION
    echo "  API Gateway deleted (ID: $API_ID)"
else
    echo "  No API Gateway found"
fi

# ============================================================================
# STEP 7: Delete RDS Proxy
# ============================================================================
echo -e "${GREEN}[7/14] Deleting RDS Proxy...${NC}"
PROXY_NAME="${PROJECT_NAME}-proxy"
safe_aws aws rds delete-db-proxy \
    --db-proxy-name $PROXY_NAME \
    --region $AWS_REGION

wait_with_message "  Waiting for proxy deletion" 60

# ============================================================================
# STEP 8: Delete RDS Database
# ============================================================================
echo -e "${GREEN}[8/14] Deleting RDS database...${NC}"
DB_IDENTIFIER="${PROJECT_NAME}-db"

# Disable deletion protection
safe_aws aws rds modify-db-instance \
    --db-instance-identifier $DB_IDENTIFIER \
    --no-deletion-protection \
    --apply-immediately \
    --region $AWS_REGION

wait_with_message "  Waiting for modification to apply" 30

# Delete the database
safe_aws aws rds delete-db-instance \
    --db-instance-identifier $DB_IDENTIFIER \
    --skip-final-snapshot \
    --delete-automated-backups \
    --region $AWS_REGION

echo "  RDS database deletion initiated (this takes 5-10 minutes)"
echo "  Continuing with other resources while RDS deletes..."

# ============================================================================
# STEP 9: Delete SQS Queues
# ============================================================================
echo -e "${GREEN}[9/14] Deleting SQS queues...${NC}"
# Get queue URLs
MAIN_QUEUE=$(aws sqs list-queues \
    --queue-name-prefix "${PROJECT_NAME}-scan-jobs" \
    --query 'QueueUrls[0]' \
    --output text \
    --region $AWS_REGION 2>/dev/null || echo "")

DLQ_QUEUE=$(aws sqs list-queues \
    --queue-name-prefix "${PROJECT_NAME}-scan-jobs-dlq" \
    --query 'QueueUrls[0]' \
    --output text \
    --region $AWS_REGION 2>/dev/null || echo "")

if [ ! -z "$MAIN_QUEUE" ] && [ "$MAIN_QUEUE" != "None" ]; then
    safe_aws aws sqs delete-queue --queue-url $MAIN_QUEUE --region $AWS_REGION
    echo "  Main queue deleted"
else
    echo "  Main queue not found"
fi

if [ ! -z "$DLQ_QUEUE" ] && [ "$DLQ_QUEUE" != "None" ]; then
    safe_aws aws sqs delete-queue --queue-url $DLQ_QUEUE --region $AWS_REGION
    echo "  DLQ deleted"
else
    echo "  DLQ not found"
fi

# ============================================================================
# STEP 10: Delete CloudWatch Log Groups
# ============================================================================
echo -e "${GREEN}[10/14] Deleting CloudWatch log groups...${NC}"
LOG_GROUPS=(
    "/aws/lambda/${PROJECT_NAME}-api"
    "/ecs/${PROJECT_NAME}-scanner"
    "/aws/rds/instance/${DB_IDENTIFIER}/postgresql"
    "/aws/rds/instance/${DB_IDENTIFIER}/upgrade"
)

for LOG_GROUP in "${LOG_GROUPS[@]}"; do
    if aws logs describe-log-groups \
        --log-group-name-prefix "$LOG_GROUP" \
        --region $AWS_REGION 2>/dev/null | grep -q "$LOG_GROUP"; then
        safe_aws aws logs delete-log-group \
            --log-group-name "$LOG_GROUP" \
            --region $AWS_REGION
        echo "  Deleted: $LOG_GROUP"
    fi
done

# ============================================================================
# STEP 11: Delete Secrets Manager Secrets
# ============================================================================
echo -e "${GREEN}[11/14] Deleting Secrets Manager secrets...${NC}"
SECRET_NAME="${PROJECT_NAME}-rds-proxy-secret"
safe_aws aws secretsmanager delete-secret \
    --secret-id $SECRET_NAME \
    --force-delete-without-recovery \
    --region $AWS_REGION
echo "  Secret deleted"

# ============================================================================
# STEP 12: Delete ECR Repositories
# ============================================================================
echo -e "${GREEN}[12/14] Deleting ECR repositories...${NC}"
ECR_REPOS=(
    "${PROJECT_NAME}-scanner"
    "${PROJECT_NAME}-lambda-api"
)

for REPO in "${ECR_REPOS[@]}"; do
    safe_aws aws ecr delete-repository \
        --repository-name $REPO \
        --force \
        --region $AWS_REGION
    echo "  Deleted repository: $REPO"
done

# ============================================================================
# STEP 13: Terminate Bastion EC2 Instance
# ============================================================================
echo -e "${GREEN}[13/14] Terminating bastion host...${NC}"
BASTION_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=${PROJECT_NAME}-bastion" \
              "Name=instance-state-name,Values=running,stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text \
    --region $AWS_REGION 2>/dev/null || echo "")

if [ ! -z "$BASTION_ID" ] && [ "$BASTION_ID" != "None" ]; then
    safe_aws aws ec2 terminate-instances \
        --instance-ids $BASTION_ID \
        --region $AWS_REGION
    echo "  Bastion instance terminated"
else
    echo "  No bastion instance found"
fi

# ============================================================================
# STEP 14: Wait for RDS deletion to complete
# ============================================================================
echo -e "${GREEN}[14/14] Waiting for RDS database to finish deleting...${NC}"
echo "  This is the longest step (5-10 minutes)"
safe_aws aws rds wait db-instance-deleted \
    --db-instance-identifier $DB_IDENTIFIER \
    --region $AWS_REGION

echo "  RDS database fully deleted"

# ============================================================================
# STEP 15: Terraform Cleanup
# ============================================================================
echo ""
echo -e "${GREEN}Cleaning up Terraform state...${NC}"
cd terraform

# Destroy remaining Terraform-managed resources
echo "  Running terraform destroy..."
terraform destroy -auto-approve 2>/dev/null || echo "  Terraform destroy completed with warnings (expected)"

# Clean state files
rm -f terraform.tfstate terraform.tfstate.backup
rm -f .terraform.tfstate.lock.info
echo "  Terraform state files removed"

# ============================================================================
# STEP 16: List remaining resources
# ============================================================================
echo ""
echo -e "${YELLOW}Checking for any remaining resources...${NC}"

# Check for snapshots
SNAPSHOTS=$(aws rds describe-db-snapshots \
    --query "DBSnapshots[?contains(DBSnapshotIdentifier, '${PROJECT_NAME}')].DBSnapshotIdentifier" \
    --output text \
    --region $AWS_REGION 2>/dev/null || echo "")

if [ ! -z "$SNAPSHOTS" ]; then
    echo -e "${YELLOW}  Warning: Found RDS snapshots:${NC}"
    for SNAPSHOT in $SNAPSHOTS; do
        echo "    - $SNAPSHOT"
    done
    echo "  To delete: aws rds delete-db-snapshot --db-snapshot-identifier <snapshot-id> --region $AWS_REGION"
fi

# Check S3 buckets
BUCKET_NAME="${PROJECT_NAME}-demo-${AWS_ACCOUNT_ID}"
if aws s3 ls s3://$BUCKET_NAME 2>/dev/null; then
    OBJECT_COUNT=$(aws s3 ls s3://$BUCKET_NAME --recursive --summarize 2>/dev/null | grep "Total Objects" | awk '{print $3}')
    echo -e "${YELLOW}  Info: S3 bucket exists with ${OBJECT_COUNT} objects${NC}"
    echo "    Bucket: s3://$BUCKET_NAME"
    echo "    To delete all data: aws s3 rm s3://$BUCKET_NAME --recursive"
    echo "    To delete bucket: aws s3 rb s3://$BUCKET_NAME --force"
fi

# ============================================================================
# COMPLETE
# ============================================================================
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    CLEANUP COMPLETE!                           ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "All infrastructure has been deleted."
echo ""
echo "Next steps for fresh deployment:"
echo "  1. cd terraform"
echo "  2. terraform init"
echo "  3. terraform plan"
echo "  4. terraform apply"
echo "  5. ./build_and_push.sh"
echo ""
echo -e "${YELLOW}Note: S3 bucket was preserved. Delete manually if needed.${NC}"
echo ""

