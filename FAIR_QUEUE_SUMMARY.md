# SQS Fair Queue Implementation - Summary

## What Was Changed

### Code Change (lambda_api/main.py)
Added `MessageGroupId: obj['bucket']` to SQS messages in the `send_sqs_batch()` function:

```python
'MessageGroupId': obj['bucket']  # Line 164
```

## Why Bucket Name (Not Job ID)?

**Decision: Use S3 bucket name as the tenant identifier**

### Reasoning

| Approach | Pros | Cons |
|----------|------|------|
| ✅ **bucket** | • Natural tenant boundary<br>• Different buckets = different teams/projects<br>• Prevents bucket monopolization<br>• Related work stays grouped | None |
| ❌ job_id | • Simple | • Doesn't reflect logical boundaries<br>• Multiple scans of same bucket treated separately |

### Real-World Example

**Scenario:**
```
Bucket A (production-logs): 10M files - scanning in progress
Bucket B (test-data):       100 files - new scan started
```

**With Fair Queue (bucket-based):**
- Bucket A continues processing at full capacity when workers available
- Bucket B gets prioritized to maintain low dwell time
- Both buckets receive fair share of processing capacity

**Without Fair Queue:**
- Bucket A monopolizes the queue
- Bucket B waits hours for Bucket A to finish

## Key Benefits

✅ **Automatic**: Enabled for all standard SQS queues with MessageGroupId  
✅ **Zero Consumer Changes**: Scanner workers require no modifications  
✅ **No Performance Impact**: No API latency or throughput limitations  
✅ **Natural Fairness**: Buckets are the logical tenant boundary in S3  
✅ **Prevents Starvation**: Large bucket scans don't block small bucket scans  

## How It Works

1. AWS SQS monitors the in-flight message distribution per bucket
2. When one bucket has disproportionately many in-flight messages, it's identified as "noisy"
3. SQS prioritizes returning messages from other buckets
4. All buckets maintain consistent low dwell times

## Testing

Test the implementation:

```bash
# 1. Start a large bucket scan
curl -X POST http://api-url/scan -d '{"bucket": "large-bucket", "prefix": ""}'

# 2. Start a small bucket scan (should complete quickly despite #1 running)
curl -X POST http://api-url/scan -d '{"bucket": "small-bucket", "prefix": ""}'
```

Monitor CloudWatch metrics:
- `ApproximateNumberOfMessagesVisible` - total queue backlog
- `ApproximateNumberOfMessagesVisibleInQuietGroups` - backlog for non-noisy buckets (should stay low)

## Documentation

See `FAIR_QUEUE_IMPLEMENTATION.md` for complete details including:
- Architecture diagrams
- Comparison with FIFO queues
- CloudWatch monitoring setup
- Alternative grouping strategies

## Reference

[AWS SQS Fair Queues Documentation](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-fair-queues.html)

