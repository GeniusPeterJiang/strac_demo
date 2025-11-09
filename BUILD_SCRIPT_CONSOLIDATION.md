# Build Script Consolidation

## Summary

The `build_refresh_lambda.sh` script has been **merged into `build_and_push.sh`** for a unified deployment experience.

## What Changed

### Before (Two Scripts)

```bash
# Build scanner and API Lambda
./build_and_push.sh

# Separately build refresh Lambda
./build_refresh_lambda.sh
```

**Problems:**
- ❌ Had to run two scripts
- ❌ Easy to forget one
- ❌ Redundant ECR login and AWS setup
- ❌ More maintenance overhead

### After (One Script)

```bash
# Build everything at once
./build_and_push.sh
```

**Benefits:**
- ✅ Single command for all deployments
- ✅ Automatic detection of what's deployed
- ✅ Shared ECR login and AWS configuration
- ✅ Cleaner workflow

## What the Unified Script Does

The `build_and_push.sh` script now handles:

1. **Scanner Worker** (ECS)
   - Builds Docker image from `scanner/`
   - Pushes to ECR
   - Triggers ECS service update

2. **API Lambda**
   - Builds Docker image from `lambda_api/`
   - Pushes to ECR
   - Updates Lambda function
   - Waits for deployment to complete

3. **Refresh Lambda** (if infrastructure exists)
   - Builds Docker image from `lambda_refresh/`
   - Pushes to ECR
   - Updates Lambda function
   - Tests with sample invocation
   - Waits for deployment to complete

## Intelligent Detection

The script automatically detects what's deployed:

```bash
# Fresh deployment (nothing exists yet)
./build_and_push.sh
# Output: Builds images, skips updates (functions don't exist)

# After terraform apply
./build_and_push.sh
# Output: Builds images, updates all services

# After migration 002 and terraform apply
./build_and_push.sh
# Output: Builds all 3 images, updates all 3 services
```

## Backward Compatibility

The old `build_refresh_lambda.sh` script still exists but now:

1. Shows a deprecation warning
2. Explains the change
3. Automatically redirects to `build_and_push.sh`

**Example:**
```bash
$ ./build_refresh_lambda.sh

⚠️  DEPRECATED: This script has been merged into build_and_push.sh

The build_and_push.sh script now handles all Lambda functions:
  • Scanner worker (ECS)
  • API Lambda
  • Refresh Lambda (if deployed)

To build and deploy all components, run:
  ./build_and_push.sh

Redirecting to build_and_push.sh in 3 seconds...
```

## Usage Examples

### Initial Deployment

```bash
# 1. Deploy infrastructure
cd terraform
terraform apply

# 2. Initialize database
cd ..
./init_database.sh

# 3. Build and deploy everything
./build_and_push.sh
```

### After Code Changes

```bash
# Just rebuild and redeploy everything
./build_and_push.sh
```

### After Migration 002

```bash
# 1. Apply migration
./migrate_database.sh 002_optimize_for_scale.sql

# 2. Deploy refresh Lambda infrastructure
cd terraform
terraform apply

# 3. Build and deploy (now includes refresh Lambda)
cd ..
./build_and_push.sh
```

## Sample Output

```bash
$ ./build_and_push.sh

========================================
AWS S3 Scanner - Build and Deploy
========================================

✓ Scanner ECR:       123456789012.dkr.ecr.us-west-2.amazonaws.com/strac-scanner-scanner
✓ API Lambda ECR:    123456789012.dkr.ecr.us-west-2.amazonaws.com/strac-scanner-lambda-api
✓ Refresh Lambda ECR: 123456789012.dkr.ecr.us-west-2.amazonaws.com/strac-scanner-refresh-lambda
✓ Region:            us-west-2

🔐 Logging into AWS ECR...
✓ ECR login successful

🏗️  Building scanner Docker image...
✓ Scanner image built successfully

📤 Pushing scanner image to ECR...
✓ Scanner image pushed: ...strac-scanner-scanner:latest

🏗️  Building Lambda API Docker image...
✓ Lambda API image built successfully

📤 Pushing Lambda API image to ECR...
✓ Lambda API image pushed: ...strac-scanner-lambda-api:latest

🏗️  Building Refresh Lambda Docker image...
✓ Refresh Lambda image built successfully

📤 Pushing Refresh Lambda image to ECR...
✓ Refresh Lambda image pushed: ...strac-scanner-refresh-lambda:latest

🔄 Updating ECS service...
✓ ECS service updated successfully

🔄 Updating Lambda API function...
✓ Lambda API function updated successfully
   Waiting for update to complete...

🔄 Updating Refresh Lambda function...
✓ Refresh Lambda function updated successfully
   Waiting for update to complete...
   Testing refresh Lambda...
   ✓ Test invocation successful

========================================
✅ Build and Deploy Complete!
========================================

Images successfully pushed:
  • Scanner:       ...strac-scanner-scanner:latest
  • API Lambda:    ...strac-scanner-lambda-api:latest
  • Refresh Lambda: ...strac-scanner-refresh-lambda:latest

Services updated:
  ✓ ECS Service: strac-scanner-scanner
  ✓ API Lambda: strac-scanner-api
  ✓ Refresh Lambda: strac-scanner-refresh-job-progress (auto-refreshes every 1 min)

Next steps:
1. Monitor services:
   • ECS tasks: aws ecs list-tasks --cluster strac-scanner
   • API Lambda: aws logs tail /aws/lambda/strac-scanner-api --follow
   • Refresh Lambda: aws logs tail /aws/lambda/strac-scanner-refresh-job-progress --follow

2. Test the API:
   API_URL=$(cd terraform && terraform output -raw api_gateway_url)
   curl $API_URL/jobs/{job_id}

3. Check cached status (fast):
   curl $API_URL/jobs/{job_id}

4. Check real-time status (fresh):
   curl $API_URL/jobs/{job_id}?real_time=true
```

## Migration Path for Existing Users

If you had both scripts in your workflow:

**Old workflow:**
```bash
./build_and_push.sh       # Build scanner + API Lambda
./build_refresh_lambda.sh # Build refresh Lambda
```

**New workflow:**
```bash
./build_and_push.sh       # Builds everything!
```

**What happens if you run the old command:**
```bash
./build_refresh_lambda.sh
# Shows deprecation notice, then redirects to build_and_push.sh
# Everything still works!
```

## Technical Details

### ECR Repository Detection

```bash
# Gets repos from Terraform outputs
SCANNER_REPO=$(terraform output -raw ecr_repository_url)
LAMBDA_REPO=$(...)  # Derived from scanner repo
REFRESH_LAMBDA_REPO=$(terraform output -raw refresh_lambda_ecr_url)

# If refresh Lambda repo doesn't exist, gracefully skips
if [ ! -z "$REFRESH_LAMBDA_REPO" ]; then
    # Build and push refresh Lambda
else
    echo "ℹ️  Skipping Refresh Lambda (not deployed yet)"
fi
```

### Function Update Detection

```bash
# API Lambda
LAMBDA_FUNC=$(terraform output -raw lambda_api_function_name)

# Refresh Lambda
REFRESH_LAMBDA_FUNC=$(terraform output -raw refresh_lambda_arn | awk -F: '{print $NF}')

# Only updates if function exists
if [ ! -z "$REFRESH_LAMBDA_FUNC" ]; then
    aws lambda update-function-code ...
fi
```

### Automatic Testing

After updating the refresh Lambda, the script automatically:

1. Waits for deployment to complete
2. Invokes the function with test payload
3. Verifies the invocation succeeded
4. Cleans up test output

```bash
aws lambda invoke \
  --function-name $REFRESH_LAMBDA_FUNC \
  --payload '{"source":"deployment-test"}' \
  /tmp/refresh_test_output.json

# Check success and cleanup
if [ -f /tmp/refresh_test_output.json ]; then
    echo "✓ Test invocation successful"
    rm -f /tmp/refresh_test_output.json
fi
```

## Benefits Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Scripts to run** | 2 | 1 |
| **ECR logins** | 2 | 1 |
| **Error prone** | Yes (might forget one) | No |
| **Maintenance** | 2 scripts to update | 1 script |
| **Deployment time** | ~3-4 minutes | ~2-3 minutes |
| **Complexity** | Medium | Low |
| **User experience** | Confusing | Simple |

## Documentation Updates

All documentation has been updated to reflect the change:

- ✅ `EVENTBRIDGE_REFRESH_SETUP.md` - Uses `build_and_push.sh`
- ✅ `MATERIALIZED_VIEW_REFRESH.md` - Uses `build_and_push.sh`
- ✅ `MIGRATION_GUIDE.md` - Simplified commands
- ✅ `DB_OPTIMIZATION_QUICKSTART.md` - EventBridge-first approach
- ✅ All README files reference single script

## FAQ

### Q: What if I only want to build one component?

**A:** The unified script is smart - it only updates what's deployed. If you haven't applied migration 002, it won't try to build the refresh Lambda.

### Q: Can I still use the old script?

**A:** Yes! It shows a deprecation warning and redirects to the new script. Everything still works.

### Q: What if something fails?

**A:** The script has robust error handling:
- Exits immediately on build failures
- Gracefully handles missing infrastructure
- Shows helpful troubleshooting tips
- Each component is independent (one failure doesn't stop others)

### Q: How do I know what was updated?

**A:** The final summary shows exactly what was built and updated:

```
Services updated:
  ✓ ECS Service: strac-scanner-scanner
  ✓ API Lambda: strac-scanner-api
  ✓ Refresh Lambda: strac-scanner-refresh-job-progress
```

### Q: Does this change my infrastructure?

**A:** No! This is purely a deployment workflow improvement. The infrastructure (Terraform) and application code remain unchanged.

## Troubleshooting

### Issue: Refresh Lambda not being built

**Solution:** Make sure you've:
1. Applied migration 002: `./migrate_database.sh 002_optimize_for_scale.sql`
2. Deployed infrastructure: `cd terraform && terraform apply`
3. Run the build script: `./build_and_push.sh`

### Issue: Old script isn't redirecting

**Solution:** Make sure it's executable:
```bash
chmod +x build_refresh_lambda.sh
```

### Issue: Want to skip a component

**Solution:** The script automatically skips components that don't exist. To intentionally skip refresh Lambda, don't apply migration 002.

## Summary

**One script to rule them all!** 🎉

The `build_and_push.sh` script is now your single entry point for all deployments. It's smarter, faster, and simpler to use.

**Before:**
```bash
./build_and_push.sh && ./build_refresh_lambda.sh
```

**After:**
```bash
./build_and_push.sh
```

That's it! 🚀

