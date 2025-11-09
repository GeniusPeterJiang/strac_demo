# SQS Fair Queue Implementation

## Overview

This document describes the implementation of AWS SQS Fair Queue feature in the Strac Demo project to prevent noisy neighbor problems in multi-tenant scan job processing.

## What is Fair Queue?

Amazon SQS Fair Queues automatically mitigate the noisy-neighbor impact in multi-tenant queues. When multiple scan jobs are running simultaneously, one large job (with millions of files) could potentially monopolize the processing queue, causing smaller jobs to experience high dwell times (the time messages wait in the queue before processing).

### The Problem: Noisy Neighbor

**Scenario without Fair Queue:**
- Bucket A (production-logs): 10 million files
- Bucket B (test-data): 100 files
- Bucket C (user-uploads): 500 files

Without fair queuing, Bucket A's messages would dominate the queue, and scans of Buckets B & C would experience significant delays even though they have far fewer files to process.

### The Solution: Fair Queue

With Fair Queue enabled, AWS SQS automatically:
1. Monitors message distribution among different buckets during processing (in-flight state)
2. Detects when one bucket has disproportionately many in-flight messages
3. Prioritizes message delivery from other buckets to maintain fair processing

**Result:** Buckets B and C maintain low dwell times while Bucket A continues processing at full capacity when workers are available.

## Implementation

### Changes Made

Modified the `send_sqs_batch()` function in `lambda_api/main.py` to include `MessageGroupId` in each SQS message:

```python
entries = [
    {
        'Id': f"{batch_index}-{j}",
        'MessageBody': json.dumps({
            'job_id': job_id,
            'bucket': obj['bucket'],
            'key': obj['key'],
            'etag': obj['etag']
        }),
        # Enable SQS Fair Queue feature by setting MessageGroupId to bucket name
        # This ensures fair processing across different S3 buckets (tenants)
        # Different buckets represent different teams/projects/applications
        # This prevents one large bucket from monopolizing processing capacity
        'MessageGroupId': obj['bucket']
    }
    for j, obj in enumerate(batch_objects)
]
```

### Key Points

1. **Tenant Identifier**: We use `bucket` (S3 bucket name) as the `MessageGroupId` to identify each bucket as a separate tenant
2. **Natural Boundary**: Different S3 buckets typically represent different teams, projects, or applications
3. **Automatic Activation**: The fair queue feature is automatically enabled for all standard SQS queues when messages include `MessageGroupId`
4. **No Consumer Changes**: The scanner workers (`scanner/main.py`) require no modifications
5. **No Performance Impact**: Fair queues have no impact on API latency or throughput limitations
6. **Unlimited Throughput**: Unlike FIFO queues, standard queues with fair queuing maintain unlimited throughput

### Why Bucket (Not Job ID)?

Using `bucket` as the MessageGroupId is superior to `job_id` because:

- **Reflects Real Tenants**: Different buckets represent different logical entities (teams/projects/apps)
- **Related Work Grouped**: Multiple scans of the same bucket are related and should share fair allocation
- **Prevents Bucket Monopolization**: One large bucket won't starve other buckets from processing
- **Intuitive Fairness**: Users expect "fairness per bucket" rather than "fairness per scan job"

## Benefits

### 1. Improved User Experience
- Small scan jobs complete quickly even when large jobs are running
- Predictable processing times for all job sizes

### 2. Resource Efficiency
- Better utilization of ECS task capacity across all jobs
- Prevents one job from starving others

### 3. Scalability
- System can handle concurrent jobs from multiple users/applications
- No throughput limitations per job

## Monitoring

### CloudWatch Metrics

AWS provides additional CloudWatch metrics to monitor fair queue behavior:

- `ApproximateNumberOfMessagesVisible`: Standard queue backlog metric
- `ApproximateNumberOfMessagesVisibleInQuietGroups`: Backlog for non-noisy jobs

**Use Case:** During a traffic surge for a specific job, the general queue-level metrics might show increasing backlogs. However, the quiet groups metric will reveal that most other jobs are not impacted.

### Recommended Alarms

Consider setting up CloudWatch alarms for:

1. **Queue Backlog for Quiet Groups**
   - Metric: `ApproximateNumberOfMessagesVisibleInQuietGroups`
   - Threshold: Alert if quiet groups also experience high backlog
   - This indicates a system-wide capacity issue, not a noisy neighbor problem

2. **Dwell Time by Message Group**
   - Monitor processing times for different job_ids
   - Identify if fair queuing is working as expected

## Comparison with FIFO Queues

| Feature | Standard Queue with Fair Queues | FIFO Queue |
|---------|--------------------------------|------------|
| **Ordering** | Best-effort ordering | Strict ordering |
| **Throughput** | Unlimited | Limited (300 TPS or 3000 TPS with batching) |
| **Concurrency** | Multiple consumers per job | Limited in-flight messages per group |
| **Use Case** | High throughput, fair resource allocation | Strict ordering requirements |

**Decision**: We chose Fair Queues over FIFO queues because:
- We need unlimited throughput for large scan jobs
- Strict ordering is not required for file scanning
- We want fair resource allocation without throughput limits

## Testing Recommendations

To verify fair queue behavior:

1. **Create Test Jobs Scanning Different Buckets with Different Sizes**
   ```bash
   # Large bucket scan (10K+ files)
   curl -X POST http://api-url/scan -d '{"bucket": "production-logs", "prefix": ""}'
   
   # Small bucket scan (10 files) - start this AFTER the large scan is running
   curl -X POST http://api-url/scan -d '{"bucket": "test-data", "prefix": ""}'
   ```

2. **Monitor Processing Times**
   - Track when each bucket's scan starts and completes
   - Verify the small bucket scan completes quickly even though the large bucket scan is running
   - Without fair queues, the small bucket would wait for most of the large bucket to finish

3. **Check CloudWatch Metrics**
   - Compare `ApproximateNumberOfMessagesVisible` vs `ApproximateNumberOfMessagesVisibleInQuietGroups`
   - During the large bucket scan, `ApproximateNumberOfMessagesVisible` will be high
   - But `ApproximateNumberOfMessagesVisibleInQuietGroups` should remain low, showing the small bucket isn't blocked

4. **Multi-Scan Same Bucket Test**
   ```bash
   # Start two scans of the same bucket
   curl -X POST http://api-url/scan -d '{"bucket": "shared-bucket", "prefix": "batch1/"}'
   curl -X POST http://api-url/scan -d '{"bucket": "shared-bucket", "prefix": "batch2/"}'
   ```
   - Both should share the same MessageGroupId (bucket name)
   - They'll be treated as the same tenant, which is correct since they're the same logical entity

## References

- [AWS SQS Fair Queues Documentation](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-fair-queues.html)
- [CloudWatch Metrics for Amazon SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-monitoring-using-cloudwatch.html)

## Future Considerations

### Alternative Grouping Strategies

Depending on your use case, you might consider different `MessageGroupId` strategies:

1. **By Bucket** (Current Implementation) ✅
   - Fair processing across different S3 buckets
   - Best for scenarios where buckets represent different teams/projects
   - Natural tenant boundary

2. **By Bucket + Prefix**
   - Fair processing for different prefixes within the same bucket
   - Use case: `my-bucket/team-a/` vs `my-bucket/team-b/` as separate tenants
   - Implementation: `MessageGroupId': f"{obj['bucket']}-{prefix}"`
   - More granular but creates more groups

3. **By Customer/Organization ID** (if multi-tenant SaaS)
   - Fair processing across different customers
   - Requires adding customer_id to the data model
   - Use case: Multiple customers each scanning multiple buckets
   - Ensures Customer A doesn't starve Customer B

4. **By Priority Level**
   - Group by priority tiers (high, medium, low)
   - Ensures fair processing within each priority tier
   - Use case: Premium customers get priority tier

5. **Hybrid Approach**
   - Combine multiple factors: `{customer_id}-{bucket}` or `{priority}-{bucket}`
   - Most granular fairness control
   - Use case: Fair allocation per customer per bucket

## Conclusion

The Fair Queue feature provides automatic noisy neighbor mitigation without sacrificing throughput or requiring complex code changes. By using **bucket name** as the `MessageGroupId`, we ensure that:

- ✅ Different S3 buckets (representing different teams/projects) get fair processing capacity
- ✅ Large bucket scans don't starve small bucket scans
- ✅ Multiple scans of the same bucket are logically grouped (same tenant)
- ✅ No code changes needed in scanner workers
- ✅ No performance impact or throughput limitations

This improves overall user experience and system efficiency while maintaining the simplicity and scalability of standard SQS queues.

