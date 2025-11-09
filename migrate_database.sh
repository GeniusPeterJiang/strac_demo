#!/bin/bash
# migrate_database.sh
# Apply database migrations automatically with SSH tunnel support

set -e

# Global variables for cleanup
USE_BASTION=false
PSQL_PORT=""
BASTION_IP=""

# Cleanup function
cleanup() {
    if [ "$USE_BASTION" = true ] && [ ! -z "$PSQL_PORT" ] && [ ! -z "$BASTION_IP" ]; then
        echo ""
        echo "🔌 Cleaning up SSH tunnel..."
        pkill -f "ssh.*-L ${PSQL_PORT}:.*:5432.*ec2-user@${BASTION_IP}" 2>/dev/null || true
        echo "✓ SSH tunnel closed"
    fi
}

# Set trap to cleanup on exit (success or failure)
trap cleanup EXIT

echo "========================================"
echo "Database Migration"
echo "========================================"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/terraform"

# Check if terraform has been applied
echo "🔍 Checking Terraform deployment..."
if ! terraform output rds_proxy_endpoint >/dev/null 2>&1; then
    echo "❌ Error: Terraform outputs not available."
    echo "   Run 'terraform apply' first to create the infrastructure."
    exit 1
fi
echo "✓ Terraform deployment found"
echo ""

# Get RDS endpoint from Terraform output
echo "📋 Getting RDS connection details..."
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint 2>/dev/null | cut -d: -f1)
if [ -z "$RDS_ENDPOINT" ]; then
    echo "❌ Error: Could not get RDS endpoint from Terraform output."
    exit 1
fi
echo "✓ RDS Endpoint: $RDS_ENDPOINT"

# Extract credentials from terraform.tfvars
if [ ! -f "terraform.tfvars" ]; then
    echo "❌ Error: terraform.tfvars not found."
    echo "   Expected location: $SCRIPT_DIR/terraform/terraform.tfvars"
    exit 1
fi

RDS_USERNAME=$(grep -E "^rds_master_username" terraform.tfvars | sed 's/.*=[ ]*"\(.*\)".*/\1/' | tr -d ' ')
RDS_PASSWORD=$(grep -E "^rds_master_password" terraform.tfvars | sed 's/.*=[ ]*"\(.*\)".*/\1/' | tr -d ' ')

if [ -z "$RDS_USERNAME" ] || [ -z "$RDS_PASSWORD" ]; then
    echo "❌ Error: Could not extract database credentials from terraform.tfvars"
    echo "   Make sure rds_master_username and rds_master_password are set."
    exit 1
fi
echo "✓ Username: $RDS_USERNAME"
echo "✓ Password: [hidden]"
echo ""

# Check if psql is available
echo "🔍 Checking for PostgreSQL client..."
if ! command -v psql >/dev/null 2>&1; then
    echo "❌ Error: psql command not found."
    echo ""
    echo "Install PostgreSQL client:"
    echo "  Ubuntu/Debian: sudo apt-get install postgresql-client"
    echo "  macOS: brew install postgresql"
    echo "  Amazon Linux: sudo yum install postgresql"
    echo ""
    exit 1
fi
echo "✓ psql found: $(psql --version)"
echo ""

# Check if migration file exists
MIGRATION_FILE="migrations/001_add_execution_arn.sql"
if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Error: Migration file not found: $MIGRATION_FILE"
    echo "   Expected location: $SCRIPT_DIR/terraform/$MIGRATION_FILE"
    exit 1
fi
echo "✓ Migration file: $MIGRATION_FILE"
echo ""

# Test connection first
echo "🔌 Testing database connection..."

if ! PGPASSWORD="$RDS_PASSWORD" psql \
    -h "$RDS_ENDPOINT" \
    -U "$RDS_USERNAME" \
    -d scanner_db \
    -c "SELECT version();" >/dev/null 2>&1; then
    echo "⚠️  Direct connection failed (RDS is in private subnet)"
    echo ""
    echo "Checking for bastion host..."
    
    # Try to get bastion host IP
    BASTION_IP=$(terraform output -raw bastion_public_ip 2>/dev/null)
    
    if [ -z "$BASTION_IP" ] || [ "$BASTION_IP" = "" ]; then
        echo "❌ Error: No bastion host found."
        echo ""
        echo "Options:"
        echo "  1. Enable bastion in terraform.tfvars: enable_bastion = true"
        echo "  2. Run terraform apply to create bastion host"
        echo "  3. Connect from within the VPC (e.g., from an EC2 instance)"
        echo ""
        exit 1
    fi
    
    echo "✓ Bastion host found: $BASTION_IP"
    echo ""
    echo "Setting up SSH tunnel automatically..."
    echo ""
    
    # Check for SSH key
    SSH_KEY=""
    for key in ~/.ssh/strac-scanner-bastion-key.pem ~/strac-scanner-bastion-key.pem; do
        if [ -f "$key" ]; then
            SSH_KEY="$key"
            break
        fi
    done
    
    if [ -z "$SSH_KEY" ]; then
        echo "❌ Error: SSH key not found."
        echo ""
        echo "Expected locations:"
        echo "  - ~/.ssh/strac-scanner-bastion-key.pem"
        echo "  - ~/strac-scanner-bastion-key.pem"
        echo ""
        exit 1
    fi
    
    echo "✓ SSH key found: $SSH_KEY"
    echo ""
    echo "Creating SSH tunnel to RDS through bastion..."
    echo "  Bastion: ec2-user@$BASTION_IP"
    echo "  Tunnel: localhost:5432 -> $RDS_ENDPOINT:5432"
    echo ""
    
    # Check if port 5432 is already in use
    if lsof -Pi :5432 -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "⚠️  Port 5432 is already in use on localhost"
        echo "   Using alternative port 15432 for tunnel..."
        LOCAL_PORT=15432
    else
        LOCAL_PORT=5432
    fi
    
    # Verify SSH key permissions
    KEY_PERMS=$(stat -c %a "$SSH_KEY" 2>/dev/null || stat -f %A "$SSH_KEY" 2>/dev/null)
    if [ "$KEY_PERMS" != "400" ] && [ "$KEY_PERMS" != "600" ]; then
        echo "⚠️  Fixing SSH key permissions..."
        chmod 400 "$SSH_KEY"
    fi
    
    # Start SSH tunnel in background
    echo "   Starting SSH tunnel..."
    SSH_OUTPUT=$(ssh -i "$SSH_KEY" \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 \
        -o ExitOnForwardFailure=yes \
        -f -N \
        -L ${LOCAL_PORT}:${RDS_ENDPOINT}:5432 \
        ec2-user@$BASTION_IP 2>&1)
    
    SSH_EXIT_CODE=$?
    
    if [ $SSH_EXIT_CODE -ne 0 ]; then
        echo "❌ Error: Failed to create SSH tunnel (exit code: $SSH_EXIT_CODE)"
        echo ""
        if [ ! -z "$SSH_OUTPUT" ]; then
            echo "SSH error output:"
            echo "$SSH_OUTPUT"
            echo ""
        fi
        echo "Possible issues:"
        echo "  1. Bastion security group doesn't allow SSH from your IP"
        echo "  2. SSH key doesn't match the key pair used for bastion"
        echo "  3. Bastion host is not running"
        echo ""
        exit 1
    fi
    
    # Give tunnel time to establish
    echo "   Waiting for tunnel to establish..."
    sleep 3
    
    echo "✓ SSH tunnel established on port $LOCAL_PORT"
    echo ""
    
    # Update RDS_ENDPOINT to use localhost
    RDS_ENDPOINT="localhost"
    USE_BASTION=true
    
    # Test connection through tunnel
    echo "🔍 Testing connection through tunnel..."
    if ! timeout 10 bash -c "PGPASSWORD='$RDS_PASSWORD' psql -h localhost -p $LOCAL_PORT -U '$RDS_USERNAME' -d scanner_db -c 'SELECT version();'" >/dev/null 2>&1; then
        echo "❌ Error: Could not connect through SSH tunnel."
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check that the password in terraform.tfvars is correct"
        echo "  2. Verify RDS security group allows connections from bastion"
        echo "  3. Verify bastion can reach RDS (check VPC routing)"
        echo ""
        exit 1
    fi
    
    # Store the port for later use
    PSQL_PORT=$LOCAL_PORT
fi

echo "✓ Database connection successful"
echo ""

# Set default port if not using bastion
if [ -z "$PSQL_PORT" ]; then
    PSQL_PORT=5432
fi

# Check current schema version
echo "🔍 Checking current database schema..."
HAS_EXECUTION_ARN=$(PGPASSWORD="$RDS_PASSWORD" psql \
    -h "$RDS_ENDPOINT" \
    -p "$PSQL_PORT" \
    -U "$RDS_USERNAME" \
    -d scanner_db \
    -t -c "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jobs' AND column_name = 'execution_arn');" 2>/dev/null | tr -d ' ')

if [ "$HAS_EXECUTION_ARN" = "t" ]; then
    echo "✓ execution_arn column already exists"
    echo ""
    echo "========================================"
    echo "ℹ️  Migration Already Applied"
    echo "========================================"
    echo ""
    echo "The database is already up to date."
    echo "No migration needed."
    echo ""
    exit 0
fi

echo "⚠️  execution_arn column not found - migration needed"
echo ""

# Run migration
echo "🔄 Applying migration..."
echo "   Migration: 001_add_execution_arn.sql"
echo ""

if PGPASSWORD="$RDS_PASSWORD" psql \
    -h "$RDS_ENDPOINT" \
    -p "$PSQL_PORT" \
    -U "$RDS_USERNAME" \
    -d scanner_db \
    -f "$MIGRATION_FILE" 2>&1; then
    echo ""
    echo "✓ Migration applied successfully"
else
    echo ""
    echo "❌ Migration failed. Please check the error message above."
    exit 1
fi
echo ""

# Verify migration was applied
echo "🔍 Verifying migration..."
HAS_EXECUTION_ARN=$(PGPASSWORD="$RDS_PASSWORD" psql \
    -h "$RDS_ENDPOINT" \
    -p "$PSQL_PORT" \
    -U "$RDS_USERNAME" \
    -d scanner_db \
    -t -c "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jobs' AND column_name = 'execution_arn');" 2>/dev/null | tr -d ' ')

if [ "$HAS_EXECUTION_ARN" = "t" ]; then
    echo "✓ execution_arn column confirmed"
else
    echo "❌ Warning: Could not verify execution_arn column was added"
fi
echo ""

# Trap will automatically cleanup SSH tunnel on exit
echo "========================================"
echo "✅ Migration Complete!"
echo "========================================"
echo ""
echo "Database changes:"
echo "  ✓ Added execution_arn column to jobs table"
echo "  ✓ Added index for efficient lookups"
echo ""
echo "Next steps:"
echo "  1. Deploy updated Lambda: ./build_and_push.sh"
echo "  2. Test job status API: curl \${API_URL}/jobs/{job_id}"
echo "  3. Verify execution_arn is populated in new jobs"
echo ""

