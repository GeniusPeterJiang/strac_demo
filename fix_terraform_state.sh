#!/bin/bash
# Fix Terraform State Issues
# Run this to clean up state before reapplying

set -e

echo "=== Fixing Terraform State Issues ==="
echo ""

cd terraform

# Step 1: Remove service-linked role from state (should never be managed)
echo "Step 1: Removing service-linked role from Terraform state..."
terraform state rm module.rds.aws_iam_service_linked_role.rds 2>/dev/null || echo "  Already removed or doesn't exist"

# Step 2: Delete existing CloudWatch log group
echo ""
echo "Step 2: Deleting existing CloudWatch log groups..."
aws logs delete-log-group \
  --log-group-name /aws/lambda/strac-scanner-api \
  --region us-west-2 2>/dev/null || echo "  Lambda log group not found"

aws logs delete-log-group \
  --log-group-name /ecs/strac-scanner-scanner \
  --region us-west-2 2>/dev/null || echo "  ECS log group not found"

# Step 3: Handle existing RDS resources
echo ""
echo "Step 3: Checking RDS resources..."

# Check if RDS DB exists
RDS_EXISTS=$(aws rds describe-db-instances \
  --db-instance-identifier strac-scanner-db \
  --region us-west-2 2>/dev/null || echo "notfound")

if [ "$RDS_EXISTS" != "notfound" ]; then
    echo "  RDS database exists. Choose an option:"
    echo "  Option A: Delete and recreate (destructive)"
    echo "  Option B: Import into Terraform state (preserves data)"
    echo ""
    read -p "  Enter A or B: " CHOICE
    
    if [ "$CHOICE" = "A" ] || [ "$CHOICE" = "a" ]; then
        echo "  Deleting RDS Proxy first..."
        aws rds delete-db-proxy \
          --db-proxy-name strac-scanner-proxy \
          --region us-west-2 2>/dev/null || echo "  Proxy not found"
        
        echo "  Waiting for proxy deletion..."
        sleep 30
        
        echo "  Disabling deletion protection on RDS..."
        aws rds modify-db-instance \
          --db-instance-identifier strac-scanner-db \
          --no-deletion-protection \
          --apply-immediately \
          --region us-west-2
        
        sleep 30
        
        echo "  Deleting RDS database..."
        aws rds delete-db-instance \
          --db-instance-identifier strac-scanner-db \
          --skip-final-snapshot \
          --delete-automated-backups \
          --region us-west-2
        
        echo "  Waiting for RDS deletion (5-10 minutes)..."
        aws rds wait db-instance-deleted \
          --db-instance-identifier strac-scanner-db \
          --region us-west-2
        
        echo "  RDS deleted successfully!"
        
    elif [ "$CHOICE" = "B" ] || [ "$CHOICE" = "b" ]; then
        echo "  Importing existing RDS resources into Terraform..."
        
        # Import DB instance
        terraform import module.rds.aws_db_instance.main strac-scanner-db 2>/dev/null || echo "  DB already imported"
        
        # Import DB proxy
        terraform import module.rds.aws_db_proxy.main strac-scanner-proxy 2>/dev/null || echo "  Proxy already imported"
        
        # Import DB subnet group
        terraform import module.rds.aws_db_subnet_group.main strac-scanner-db-subnet-group 2>/dev/null || echo "  Subnet group already imported"
        
        echo "  Import complete!"
    fi
else
    echo "  No RDS database found - clean state"
fi

echo ""
echo "=== State Cleanup Complete ==="
echo ""
echo "Next steps:"
echo "1. Run: terraform plan"
echo "2. Review the plan carefully"
echo "3. Run: terraform apply"
echo ""

