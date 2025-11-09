# Migration Error Handling

## Overview

The `migrate_database.sh` script now has **robust error handling** that catches and reports all types of migration failures.

## Error Detection Mechanisms

### 1. PostgreSQL ON_ERROR_STOP Flag

```bash
psql -v ON_ERROR_STOP=1 -f migration.sql
```

**What it does:**
- Stops execution immediately on first error
- Returns non-zero exit code
- Prevents partial migrations

### 2. Exit Code Checking

```bash
PSQL_EXIT_CODE=${PIPESTATUS[0]}  # Captures psql exit code, not tee
if [ $PSQL_EXIT_CODE -ne 0 ]; then
    echo "❌ Migration failed with exit code: $PSQL_EXIT_CODE"
    exit 1
fi
```

**Catches:**
- Connection failures
- Permission errors
- SQL syntax errors
- Constraint violations

### 3. ERROR Line Detection

```bash
if grep -q "^psql:.*ERROR:" /tmp/migration_output.log; then
    echo "❌ Migration failed due to errors"
    grep "^psql:.*ERROR:" /tmp/migration_output.log
    exit 1
fi
```

**Catches:**
- Errors that don't cause psql to exit (rare but possible)
- Multiple errors in output
- Provides exact error messages

### 4. Post-Migration Verification

```bash
# For migration 002
HAS_MATVIEW=$(psql -t -c "SELECT EXISTS (...)")
if [ "$HAS_MATVIEW" != "t" ]; then
    echo "❌ ERROR: job_progress not found after migration!"
    exit 1
fi
```

**Catches:**
- Silent failures
- Incomplete migrations
- Missing expected objects

## Error Scenarios Handled

### Scenario 1: Syntax Error

**Problem:**
```sql
CREATE TABLE test (
    id SERIAL PRIMARY KEY,
    name TEXT
-- Missing closing parenthesis
```

**Detection:**
```
psql:migration.sql:4: ERROR:  syntax error at or near ";"
```

**Script Response:**
```bash
❌ Migration failed with exit code: 1

Error details:
psql:migration.sql:4: ERROR:  syntax error at or near ";"

❌ Migration failed due to errors. Please fix and retry.
```

**Exit Code:** 1 ✅

---

### Scenario 2: Missing Table

**Problem:**
```sql
ALTER TABLE nonexistent_table ADD COLUMN new_col TEXT;
```

**Detection:**
```
psql:migration.sql:1: ERROR:  relation "nonexistent_table" does not exist
```

**Script Response:**
```bash
❌ Migration failed with exit code: 1

Error details:
psql:migration.sql:1: ERROR:  relation "nonexistent_table" does not exist

❌ Migration failed due to errors. Please fix and retry.
```

**Exit Code:** 1 ✅

---

### Scenario 3: Permission Denied

**Problem:**
```sql
DROP TABLE system_table;  -- No permission
```

**Detection:**
```
psql:migration.sql:1: ERROR:  must be owner of table system_table
```

**Script Response:**
```bash
❌ Migration failed with exit code: 1

Error details:
psql:migration.sql:1: ERROR:  must be owner of table system_table

❌ Migration failed due to errors. Please fix and retry.
```

**Exit Code:** 1 ✅

---

### Scenario 4: Connection Failure

**Problem:**
- Database is down
- Wrong credentials
- Network issue

**Detection:**
```
psql: error: connection to server at "..." failed: Connection refused
```

**Script Response:**
```bash
❌ Error: Could not connect through SSH tunnel.

Troubleshooting:
  1. Check that the password in terraform.tfvars is correct
  2. Verify RDS security group allows connections from bastion
  3. Verify bastion can reach RDS (check VPC routing)
```

**Exit Code:** 1 ✅

---

### Scenario 5: Materialized View Not Created

**Problem:**
Migration runs but materialized view isn't created (silent failure)

**Detection:**
```sql
SELECT EXISTS (
    SELECT 1 FROM pg_matviews 
    WHERE matviewname = 'job_progress'
);  -- Returns false
```

**Script Response:**
```bash
🔍 Verifying database objects...
   Checking for job_progress materialized view...
❌ ERROR: job_progress materialized view not found after migration!
   Migration failed. Check error messages above.
```

**Exit Code:** 1 ✅

---

### Scenario 6: Refresh Tracking Table Missing

**Problem:**
Materialized view created but tracking table wasn't

**Detection:**
```sql
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables 
    WHERE table_name = 'materialized_view_refresh_log'
);  -- Returns false
```

**Script Response:**
```bash
✓ job_progress materialized view exists
   Checking for materialized_view_refresh_log table...
❌ ERROR: materialized_view_refresh_log table not found!
   Migration failed. Check error messages above.
```

**Exit Code:** 1 ✅

---

### Scenario 7: Initial Refresh Fails

**Problem:**
View created but can't be refreshed (data issues)

**Detection:**
```
REFRESH MATERIALIZED VIEW job_progress;
ERROR: ...
```

**Script Response:**
```bash
🔄 Performing initial refresh of job_progress...
⚠️  Concurrent refresh failed, trying regular refresh...
❌ ERROR: Failed to refresh materialized view
   This is critical. Check database permissions and data.
```

**Exit Code:** 1 ✅

---

## Success Scenarios

### Clean Migration

```bash
$ ./migrate_database.sh 002_optimize_for_scale.sql

========================================
Database Migration
========================================

🔍 Checking Terraform deployment...
✓ Terraform deployment found

📋 Getting RDS connection details...
✓ RDS Endpoint: xxx.rds.amazonaws.com
✓ Username: scanner_admin
✓ Password: [hidden]

🔍 Checking for PostgreSQL client...
✓ psql found: psql (PostgreSQL) 15.3

✓ Migration file: migrations/002_optimize_for_scale.sql

🔌 Testing database connection...
✓ Database connection successful

🔍 Migration: 002_optimize_for_scale

🔄 Applying migration...
   File: migrations/002_optimize_for_scale.sql
   
   Note: Migrations are idempotent and safe to run multiple times

CREATE TABLE
INSERT 0 1
NOTICE: Refresh tracking table created
CREATE MATERIALIZED VIEW
CREATE INDEX
NOTICE: Step 2: Materialized view job_progress created
...

✓ Migration applied successfully

🔍 Verifying database objects...
   Checking for job_progress materialized view...
✓ job_progress materialized view exists
   Checking for materialized_view_refresh_log table...
✓ materialized_view_refresh_log table exists
🔄 Performing initial refresh of job_progress...
✓ Initial concurrent refresh complete

========================================
✅ Migration Complete!
========================================
```

**Exit Code:** 0 ✅

### Already Applied

```bash
$ ./migrate_database.sh 002_optimize_for_scale.sql

...
NOTICE:  relation "idx_job_objects_job_status" already exists, skipping
NOTICE:  table "materialized_view_refresh_log" already exists, skipping
...

✓ Migration already applied or completed successfully

🔍 Verifying database objects...
✓ job_progress materialized view exists
✓ materialized_view_refresh_log table exists
...

========================================
✅ Migration Complete!
========================================
```

**Exit Code:** 0 ✅

---

## Testing Error Handling

### Test 1: Force Syntax Error

```bash
# Create a broken migration
cat > terraform/migrations/test_error.sql <<'EOF'
CREATE TABLE test (
    id SERIAL PRIMARY KEY
-- Missing closing parenthesis and semicolon
EOF

# Run it
./migrate_database.sh test_error.sql
```

**Expected:** Exit code 1, shows syntax error

### Test 2: Force Connection Error

```bash
# Wrong password in terraform.tfvars
./migrate_database.sh 002_optimize_for_scale.sql
```

**Expected:** Exit code 1, connection error message

### Test 3: Permission Error

```sql
-- In migration file
GRANT ALL ON DATABASE postgres TO scanner_admin;  -- No permission
```

**Expected:** Exit code 1, permission denied error

### Test 4: Verify Detection Works

```bash
# Manually break the migration (add syntax error to line 50)
vim terraform/migrations/002_optimize_for_scale.sql
# Change line 50 to invalid SQL

# Run migration
./migrate_database.sh 002_optimize_for_scale.sql

# Should fail with clear error message
```

---

## Error Output Format

```
❌ Migration failed with exit code: 1

Error details:
psql:migrations/002_optimize_for_scale.sql:50: ERROR:  syntax error at or near "INVALID"
LINE 50: INVALID SQL HERE;
         ^

❌ Migration failed due to errors. Please fix and retry.
```

**Components:**
1. ❌ Clear failure indicator
2. Exit code shown
3. Exact line number with error
4. SQL context around error
5. Clear next steps

---

## Automated Testing

Add to your CI/CD pipeline:

```bash
#!/bin/bash
# test_migrations.sh

set -e

echo "Testing migration error handling..."

# Test 1: Valid migration should succeed
if ./migrate_database.sh 002_optimize_for_scale.sql; then
    echo "✓ Valid migration succeeded"
else
    echo "✗ Valid migration failed (unexpected)"
    exit 1
fi

# Test 2: Invalid migration should fail
cat > terraform/migrations/test_invalid.sql <<'EOF'
INVALID SQL SYNTAX HERE;
EOF

if ./migrate_database.sh test_invalid.sql; then
    echo "✗ Invalid migration succeeded (should have failed!)"
    exit 1
else
    echo "✓ Invalid migration failed as expected"
fi

rm -f terraform/migrations/test_invalid.sql

echo "All error handling tests passed!"
```

---

## Summary

### ✅ What's Protected

1. **SQL Syntax Errors** - Caught by psql parser
2. **Connection Failures** - Caught by connection test
3. **Permission Errors** - Caught by psql execution
4. **Missing Objects** - Caught by verification
5. **Silent Failures** - Caught by post-migration checks
6. **Partial Migrations** - Prevented by ON_ERROR_STOP

### ✅ Exit Codes

| Scenario | Exit Code | Detection Method |
|----------|-----------|------------------|
| Success | 0 | All checks pass |
| Syntax Error | 1 | psql exit code |
| Connection Error | 1 | Connection test fails |
| Permission Error | 1 | psql exit code |
| Missing Object | 1 | Post-migration verification |
| Refresh Failure | 1 | REFRESH command fails |

### ✅ Best Practices

1. **Always check exit code** in automation
2. **Review full output** for warnings
3. **Test migrations** on staging first
4. **Keep backups** before migrations
5. **Monitor logs** during deployment

### Example CI/CD Integration

```yaml
# .github/workflows/deploy.yml
- name: Run database migration
  run: |
    ./migrate_database.sh 002_optimize_for_scale.sql
    if [ $? -ne 0 ]; then
      echo "Migration failed! Stopping deployment."
      exit 1
    fi
```

All errors are now properly caught and reported! 🛡️

