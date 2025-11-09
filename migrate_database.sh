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

# Get migration file from argument or default
MIGRATION_FILE="${1:-migrations/001_add_execution_arn.sql}"

# If only filename given, prepend migrations/
if [[ "$MIGRATION_FILE" != *"/"* ]]; then
    MIGRATION_FILE="migrations/$MIGRATION_FILE"
fi

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Error: Migration file not found: $MIGRATION_FILE"
    echo "   Expected location: $SCRIPT_DIR/terraform/$MIGRATION_FILE"
    echo ""
    echo "Available migrations:"
    if [ -d "migrations" ]; then
        ls -1 migrations/*.sql 2>/dev/null || echo "  No migrations found"
    else
        echo "  migrations/ directory not found"
    fi
    echo ""
    echo "Usage: $0 [migration_file]"
    echo "  Example: $0 001_add_execution_arn.sql"
    echo "  Example: $0 migrations/002_optimize_for_scale.sql"
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

# Extract migration name for display
MIGRATION_NAME=$(basename "$MIGRATION_FILE" .sql)
echo "🔍 Migration: $MIGRATION_NAME"
echo ""

# Run migration (migrations are idempotent)
echo "🔄 Applying migration..."
echo "   File: $MIGRATION_FILE"
echo ""
echo "   Note: Migrations are idempotent and safe to run multiple times"
echo ""

# Run psql and capture output
PGPASSWORD="$RDS_PASSWORD" psql \
    -h "$RDS_ENDPOINT" \
    -p "$PSQL_PORT" \
    -U "$RDS_USERNAME" \
    -d scanner_db \
    -v ON_ERROR_STOP=1 \
    -f "$MIGRATION_FILE" 2>&1 | tee /tmp/migration_output.log

# Check exit code from PIPESTATUS (captures psql exit code, not tee)
PSQL_EXIT_CODE=${PIPESTATUS[0]}

if [ $PSQL_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Migration failed with exit code: $PSQL_EXIT_CODE"
    echo ""
    echo "Error details:"
    grep -i "error" /tmp/migration_output.log | head -20 || echo "No specific error messages found"
    echo ""
    rm -f /tmp/migration_output.log
    exit 1
fi

# Check for ERROR lines in output (even if psql exit code is 0)
if grep -q "^psql:.*ERROR:" /tmp/migration_output.log 2>/dev/null; then
    echo ""
    echo "⚠️  WARNING: Errors detected in migration output"
    echo ""
    echo "Errors found:"
    grep "^psql:.*ERROR:" /tmp/migration_output.log
    echo ""
    echo "❌ Migration failed due to errors. Please fix and retry."
    rm -f /tmp/migration_output.log
    exit 1
fi

# Check for common success indicators in output
if grep -q "NOTICE.*already exists\|Migration complete\|already applied" /tmp/migration_output.log 2>/dev/null; then
    echo ""
    echo "✓ Migration already applied or completed successfully"
else
    echo ""
    echo "✓ Migration applied successfully"
fi

rm -f /tmp/migration_output.log
echo ""

# Verify some key objects exist based on migration
echo "🔍 Verifying database objects..."

case "$MIGRATION_FILE" in
    *"001_add_execution_arn"*)
        # Check execution_arn column
        echo "   Checking for execution_arn column..."
        HAS_COLUMN=$(PGPASSWORD="$RDS_PASSWORD" psql \
            -h "$RDS_ENDPOINT" \
            -p "$PSQL_PORT" \
            -U "$RDS_USERNAME" \
            -d scanner_db \
            -t -c "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jobs' AND column_name = 'execution_arn');" 2>/dev/null | tr -d ' ')
        
        if [ "$HAS_COLUMN" = "t" ]; then
            echo "✓ execution_arn column exists"
        else
            echo "❌ ERROR: execution_arn column not found after migration!"
            echo "   Migration may have failed. Check logs above."
            exit 1
        fi
        ;;
    
    *"002_optimize_for_scale"*)
        # Check materialized view
        echo "   Checking for job_progress materialized view..."
        HAS_MATVIEW=$(PGPASSWORD="$RDS_PASSWORD" psql \
            -h "$RDS_ENDPOINT" \
            -p "$PSQL_PORT" \
            -U "$RDS_USERNAME" \
            -d scanner_db \
            -t -c "SELECT EXISTS (SELECT 1 FROM pg_matviews WHERE schemaname = 'public' AND matviewname = 'job_progress');" 2>/dev/null | tr -d ' ')
        
        if [ "$HAS_MATVIEW" = "t" ]; then
            echo "✓ job_progress materialized view exists"
        else
            echo "❌ ERROR: job_progress materialized view not found after migration!"
            echo "   Migration failed. Check error messages above."
            exit 1
        fi
        
        # Check refresh tracking table
        echo "   Checking for materialized_view_refresh_log table..."
        HAS_LOG_TABLE=$(PGPASSWORD="$RDS_PASSWORD" psql \
            -h "$RDS_ENDPOINT" \
            -p "$PSQL_PORT" \
            -U "$RDS_USERNAME" \
            -d scanner_db \
            -t -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'materialized_view_refresh_log');" 2>/dev/null | tr -d ' ')
        
        if [ "$HAS_LOG_TABLE" = "t" ]; then
            echo "✓ materialized_view_refresh_log table exists"
        else
            echo "❌ ERROR: materialized_view_refresh_log table not found!"
            echo "   Migration failed. Check error messages above."
            exit 1
        fi
        
        # Initial refresh
        echo "🔄 Performing initial refresh of job_progress..."
        if PGPASSWORD="$RDS_PASSWORD" psql \
            -h "$RDS_ENDPOINT" \
            -p "$PSQL_PORT" \
            -U "$RDS_USERNAME" \
            -d scanner_db \
            -v ON_ERROR_STOP=1 \
            -c "REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;" 2>&1; then
            echo "✓ Initial concurrent refresh complete"
        else
            echo "⚠️  Concurrent refresh failed, trying regular refresh..."
            if PGPASSWORD="$RDS_PASSWORD" psql \
                -h "$RDS_ENDPOINT" \
                -p "$PSQL_PORT" \
                -U "$RDS_USERNAME" \
                -d scanner_db \
                -v ON_ERROR_STOP=1 \
                -c "REFRESH MATERIALIZED VIEW job_progress;" 2>&1; then
                echo "✓ Initial refresh complete (non-concurrent)"
            else
                echo "❌ ERROR: Failed to refresh materialized view"
                echo "   This is critical. Check database permissions and data."
                exit 1
            fi
        fi
        ;;
    
    *)
        echo "✓ Migration completed (no specific verification for this migration)"
        ;;
esac

echo ""

# Trap will automatically cleanup SSH tunnel on exit
echo "========================================"
echo "✅ Migration Complete!"
echo "========================================"
echo ""
echo "Migration applied: $MIGRATION_NAME"
echo ""
echo "Next steps:"
if [[ "$MIGRATION_FILE" == *"002_optimize_for_scale"* ]]; then
    echo "  1. Deploy EventBridge refresh Lambda: terraform apply"
    echo "  2. Verify materialized view is refreshing: Check CloudWatch logs"
    echo "  3. Test API with ?real_time=false (cached) and ?real_time=true"
elif [[ "$MIGRATION_FILE" == *"001_add_execution_arn"* ]]; then
    echo "  1. Deploy updated Lambda: ./build_and_push.sh"
    echo "  2. Test job status API: curl \${API_URL}/jobs/{job_id}"
    echo "  3. Verify execution_arn is populated in new jobs"
else
    echo "  1. Deploy updated Lambda if needed: ./build_and_push.sh"
    echo "  2. Test the changes"
fi
echo ""

