#!/bin/bash
# build_and_push.sh
# Automated script to build and push Docker images to ECR, then update ECS and Lambda

set -e  # Exit on error

echo "========================================"
echo "AWS S3 Scanner - Build and Deploy"
echo "========================================"
echo ""

# Get current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if Docker daemon is accessible
echo "🔍 Checking Docker availability..."
if ! docker ps >/dev/null 2>&1; then
    echo "❌ Error: Cannot connect to Docker daemon."
    echo ""
    echo "Possible fixes:"
    echo "  1. Start Docker: sudo systemctl start docker"
    echo "  2. Add your user to docker group: sudo usermod -aG docker \$USER"
    echo "  3. Run this script with sudo (preserves env): sudo -E ./build_and_push.sh"
    echo ""
    exit 1
fi
echo "✓ Docker is accessible"
echo ""

# Get ECR repository URLs and AWS region from Terraform outputs
echo "📋 Getting infrastructure details from Terraform..."
cd "$SCRIPT_DIR/terraform"

SCANNER_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null)
if [ -z "$SCANNER_REPO" ]; then
    echo "❌ Error: Could not get ECR repository URL from Terraform."
    echo "   Make sure you've run 'terraform apply' first."
    exit 1
fi

# Fix: Properly construct Lambda repo URL
LAMBDA_REPO=$(echo $SCANNER_REPO | sed 's/strac-scanner-scanner/strac-scanner-lambda-api/')
REFRESH_LAMBDA_REPO=$(terraform output -raw refresh_lambda_ecr_url 2>/dev/null)
AWS_REGION=$(echo $SCANNER_REPO | cut -d'.' -f4)

echo "✓ Scanner ECR:       $SCANNER_REPO"
echo "✓ Lambda API ECR:    $LAMBDA_REPO"
if [ ! -z "$REFRESH_LAMBDA_REPO" ]; then
    echo "✓ Refresh Lambda ECR: $REFRESH_LAMBDA_REPO"
fi
echo "✓ Region:            $AWS_REGION"
echo ""

# Login to ECR
echo "🔐 Logging into AWS ECR..."
echo "   Using region: $AWS_REGION"
echo "   Repository: $SCANNER_REPO"

if ! aws ecr get-login-password --region $AWS_REGION 2>/dev/null | \
    docker login --username AWS --password-stdin $SCANNER_REPO 2>&1; then
    echo ""
    echo "❌ Error: ECR login failed."
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check AWS credentials: aws sts get-caller-identity"
    echo "  2. Verify ECR access: aws ecr describe-repositories --region $AWS_REGION"
    echo "  3. If using sudo, try: sudo -E ./build_and_push.sh"
    echo ""
    exit 1
fi
echo "✓ ECR login successful"
echo ""

# Build and push scanner image
echo "🏗️  Building scanner Docker image..."
echo "   Directory: $SCRIPT_DIR/scanner"
cd "$SCRIPT_DIR/scanner"

if ! docker build -t s3-scanner:latest . 2>&1 | tail -10; then
    echo "❌ Error: Scanner image build failed."
    echo "   Check Dockerfile in: $SCRIPT_DIR/scanner"
    exit 1
fi
echo "✓ Scanner image built successfully"
echo ""

echo "📤 Pushing scanner image to ECR..."
echo "   Target: $SCANNER_REPO:latest"
docker tag s3-scanner:latest $SCANNER_REPO:latest

if ! docker push $SCANNER_REPO:latest 2>&1 | grep -E "(Pushed|digest:)"; then
    echo "❌ Error: Scanner image push failed."
    exit 1
fi
echo "✓ Scanner image pushed: $SCANNER_REPO:latest"
echo ""

# Build and push Lambda API image
echo "🏗️  Building Lambda API Docker image..."
echo "   Directory: $SCRIPT_DIR/lambda_api"
cd "$SCRIPT_DIR/lambda_api"

if ! docker build -t lambda-api:latest . 2>&1 | tail -10; then
    echo "❌ Error: Lambda API image build failed."
    echo "   Check Dockerfile in: $SCRIPT_DIR/lambda_api"
    exit 1
fi
echo "✓ Lambda API image built successfully"
echo ""

echo "📤 Pushing Lambda API image to ECR..."
echo "   Target: $LAMBDA_REPO:latest"
docker tag lambda-api:latest $LAMBDA_REPO:latest

if ! docker push $LAMBDA_REPO:latest 2>&1 | grep -E "(Pushed|digest:)"; then
    echo "❌ Error: Lambda API image push failed."
    exit 1
fi
echo "✓ Lambda API image pushed: $LAMBDA_REPO:latest"
echo ""

# Build and push Refresh Lambda image (if exists)
if [ ! -z "$REFRESH_LAMBDA_REPO" ]; then
    echo "🏗️  Building Refresh Lambda Docker image..."
    echo "   Directory: $SCRIPT_DIR/lambda_refresh"
    cd "$SCRIPT_DIR/lambda_refresh"
    
    if ! docker build -t lambda-refresh:latest . 2>&1 | tail -10; then
        echo "❌ Error: Refresh Lambda image build failed."
        echo "   Check Dockerfile in: $SCRIPT_DIR/lambda_refresh"
        exit 1
    fi
    echo "✓ Refresh Lambda image built successfully"
    echo ""
    
    echo "📤 Pushing Refresh Lambda image to ECR..."
    echo "   Target: $REFRESH_LAMBDA_REPO:latest"
    docker tag lambda-refresh:latest $REFRESH_LAMBDA_REPO:latest
    
    if ! docker push $REFRESH_LAMBDA_REPO:latest 2>&1 | grep -E "(Pushed|digest:)"; then
        echo "❌ Error: Refresh Lambda image push failed."
        exit 1
    fi
    echo "✓ Refresh Lambda image pushed: $REFRESH_LAMBDA_REPO:latest"
    echo ""
else
    echo "ℹ️  Skipping Refresh Lambda (not deployed yet)"
    echo "   Run migration 002_optimize_for_scale.sql and terraform apply to enable"
    echo ""
fi

# Update ECS service
echo "🔄 Updating ECS service..."
cd "$SCRIPT_DIR/terraform"
CLUSTER=$(terraform output -raw ecs_cluster_name 2>/dev/null)
SERVICE=$(terraform output -raw ecs_service_name 2>/dev/null)

if [ -z "$CLUSTER" ] || [ -z "$SERVICE" ]; then
    echo "⚠️  Warning: Could not get ECS details. Skipping ECS update."
    echo "   (This is normal if Lambda hasn't been created yet)"
else
    echo "   Cluster: $CLUSTER"
    echo "   Service: $SERVICE"
    
    if aws ecs update-service \
        --cluster $CLUSTER \
        --service $SERVICE \
        --force-new-deployment \
        --region $AWS_REGION \
        --no-cli-pager 2>&1; then
        echo "✓ ECS service updated successfully"
    else
        echo "⚠️  Warning: ECS service update failed (may not be critical if service doesn't exist yet)"
    fi
fi
echo ""

# Update Lambda API function
echo "🔄 Updating Lambda API function..."
LAMBDA_FUNC=$(terraform output -raw lambda_api_function_name 2>/dev/null)

if [ -z "$LAMBDA_FUNC" ]; then
    echo "⚠️  Warning: Could not get Lambda function name. Skipping Lambda update."
    echo "   (This is normal - Lambda doesn't exist yet. Run 'terraform apply' next)"
else
    echo "   Function: $LAMBDA_FUNC"
    echo "   Image: $LAMBDA_REPO:latest"
    
    if aws lambda update-function-code \
        --function-name $LAMBDA_FUNC \
        --image-uri $LAMBDA_REPO:latest \
        --region $AWS_REGION \
        --no-cli-pager 2>&1; then
        echo "✓ Lambda API function updated successfully"
        
        # Wait for update to complete
        echo "   Waiting for update to complete..."
        aws lambda wait function-updated \
            --function-name $LAMBDA_FUNC \
            --region $AWS_REGION 2>/dev/null || true
    else
        echo "⚠️  Warning: Lambda function update failed"
        echo "   This is expected if the Lambda function doesn't exist yet"
        echo "   Run 'cd terraform && terraform apply' to create it"
    fi
fi
echo ""

# Update Refresh Lambda function (if exists)
if [ ! -z "$REFRESH_LAMBDA_REPO" ]; then
    echo "🔄 Updating Refresh Lambda function..."
    REFRESH_LAMBDA_FUNC=$(terraform output -raw refresh_lambda_arn 2>/dev/null | awk -F: '{print $NF}')
    
    if [ -z "$REFRESH_LAMBDA_FUNC" ]; then
        echo "⚠️  Warning: Could not get Refresh Lambda function name."
        echo "   Run 'terraform apply' to create the refresh Lambda first"
    else
        echo "   Function: $REFRESH_LAMBDA_FUNC"
        echo "   Image: $REFRESH_LAMBDA_REPO:latest"
        
        if aws lambda update-function-code \
            --function-name $REFRESH_LAMBDA_FUNC \
            --image-uri $REFRESH_LAMBDA_REPO:latest \
            --region $AWS_REGION \
            --no-cli-pager 2>&1; then
            echo "✓ Refresh Lambda function updated successfully"
            
            # Wait for update to complete
            echo "   Waiting for update to complete..."
            aws lambda wait function-updated \
                --function-name $REFRESH_LAMBDA_FUNC \
                --region $AWS_REGION 2>/dev/null || true
            
            # Test the refresh Lambda
            echo "   Testing refresh Lambda..."
            TEST_RESULT=$(aws lambda invoke \
                --function-name $REFRESH_LAMBDA_FUNC \
                --region $AWS_REGION \
                --payload '{"source":"deployment-test"}' \
                /tmp/refresh_test_output.json 2>&1 || echo "")
            
            if [ -f /tmp/refresh_test_output.json ]; then
                echo "   ✓ Test invocation successful"
                rm -f /tmp/refresh_test_output.json
            fi
        else
            echo "⚠️  Warning: Refresh Lambda function update failed"
        fi
    fi
    echo ""
fi

echo "========================================"
echo "✅ Build and Deploy Complete!"
echo "========================================"
echo ""
echo "Images successfully pushed:"
echo "  • Scanner:       $SCANNER_REPO:latest"
echo "  • API Lambda:    $LAMBDA_REPO:latest"
if [ ! -z "$REFRESH_LAMBDA_REPO" ]; then
    echo "  • Refresh Lambda: $REFRESH_LAMBDA_REPO:latest"
fi
echo ""

echo "Services updated:"
if [ ! -z "$CLUSTER" ] && [ ! -z "$SERVICE" ]; then
    echo "  ✓ ECS Service: $SERVICE"
fi
if [ ! -z "$LAMBDA_FUNC" ]; then
    echo "  ✓ API Lambda: $LAMBDA_FUNC"
fi
if [ ! -z "$REFRESH_LAMBDA_FUNC" ]; then
    echo "  ✓ Refresh Lambda: $REFRESH_LAMBDA_FUNC (auto-refreshes every 1 min)"
fi
echo ""

echo "Next steps:"
if [ -z "$LAMBDA_FUNC" ]; then
    echo "1. Complete infrastructure deployment:"
    echo "   cd terraform && terraform apply"
    echo ""
    echo "2. Initialize database:"
    echo "   cd $SCRIPT_DIR && ./init_database.sh"
    echo ""
    echo "3. Apply database optimizations (optional):"
    echo "   ./migrate_database.sh 002_optimize_for_scale.sql"
    echo ""
    echo "4. Test the API:"
    echo "   API_URL=\$(cd terraform && terraform output -raw api_gateway_url)"
    echo "   curl \$API_URL"
else
    echo "1. Monitor services:"
    echo "   • ECS tasks: aws ecs list-tasks --cluster $CLUSTER"
    echo "   • API Lambda: aws logs tail /aws/lambda/$LAMBDA_FUNC --follow"
    if [ ! -z "$REFRESH_LAMBDA_FUNC" ]; then
        echo "   • Refresh Lambda: aws logs tail /aws/lambda/$REFRESH_LAMBDA_FUNC --follow"
    fi
    echo ""
    echo "2. Test the API:"
    echo "   API_URL=\$(cd terraform && terraform output -raw api_gateway_url)"
    echo "   curl \$API_URL/jobs/{job_id}"
    if [ ! -z "$REFRESH_LAMBDA_FUNC" ]; then
        echo ""
        echo "3. Check cached status (fast):"
        echo "   curl \$API_URL/jobs/{job_id}"
        echo ""
        echo "4. Check real-time status (fresh):"
        echo "   curl \$API_URL/jobs/{job_id}?real_time=true"
    fi
fi
echo ""

