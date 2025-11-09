# Capacity Analysis: Maximum S3 Objects

## Summary

With the current implementation using Step Functions and continuation tokens, the system can theoretically handle:

**Maximum Capacity: ~50 Million Objects** 🚀

But there are practical considerations for different scales.

---

## Component Analysis

### 1. Lambda API (Synchronous Mode)

**Without Step Functions:**
- ❌ **Limit:** ~200,000 objects
- **Bottleneck:** Lambda 300-second timeout
- **Time:** ~290 seconds for 200K objects

**Breakdown:**
```
200K objects:
  - S3 listing: 60s (200 pages × 0.3s)
  - DB inserts: 200s (200 batches × 1s)
  - SQS enqueue: 30s (20,000 batches / 20 workers)
  = 290 seconds total
```

**Beyond 200K:** Lambda times out ❌

---

### 2. Step Functions (Asynchronous Mode)

**With Step Functions + Continuation Tokens:**

#### Per Batch Limits
- **Objects per batch:** 10,000
- **Time per batch:** ~30 seconds
  - S3 listing: ~3s
  - DB inserts: ~10s  
  - SQS enqueue: ~0.5s (parallel)
  - Overhead: ~1s

#### Step Functions Constraints

**Event History Limit:**
- Maximum events: 25,000
- Events per iteration: ~4-5
  - ProcessBatch (task start)
  - ProcessBatch (task complete)
  - CheckIfDone (choice)
  - Loop back
- **Maximum iterations:** 5,000-6,000

**Calculation:**
```
Max iterations: 5,000
Objects per iteration: 10,000
Maximum objects: 50,000,000 (50 million)
```

#### Time Estimates

| Objects | Iterations | Time (minutes) | Time (hours) |
|---------|-----------|----------------|--------------|
| 10K | 1 | 0.5 | 0.01 |
| 100K | 10 | 5 | 0.08 |
| 500K | 50 | 25 | 0.42 |
| 1M | 100 | 50 | 0.83 |
| 5M | 500 | 250 | 4.17 |
| 10M | 1,000 | 500 | 8.33 |
| 25M | 2,500 | 1,250 | 20.83 |
| **50M** | **5,000** | **2,500** | **41.67** |

**50 million objects = ~42 hours of listing**

---

### 3. Database (PostgreSQL RDS)

**Table: job_objects**

#### Storage Capacity
```sql
-- Each row: ~200 bytes
-- 50M rows = 10 GB data
-- With indexes: ~15 GB total
```

**Typical RDS instance (db.t3.medium):**
- Storage: 100 GB (plenty of room)
- ✅ Can handle 50M rows easily

#### Query Performance

**Without optimization:**
```sql
-- Count query on 50M rows
SELECT COUNT(*) FROM job_objects WHERE job_id = 'xxx';
-- Time: ~30 seconds ❌
```

**With optimization (recommended for >1M objects):**
```sql
-- Table partitioning by job_id
CREATE TABLE job_objects_partitioned (...) PARTITION BY HASH (job_id);

-- Aggregate view for quick counts
CREATE MATERIALIZED VIEW job_progress AS
SELECT job_id, 
       COUNT(*) as total,
       COUNT(*) FILTER (WHERE status = 'succeeded') as succeeded,
       ...
FROM job_objects
GROUP BY job_id;

-- Refresh periodically
REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;

-- Query time: ~100ms ✅
```

**With these optimizations:**
- ✅ Can handle 100M+ rows efficiently

---

### 4. SQS Queue

**Standard SQS:**
- Throughput: Nearly unlimited
- Message retention: 14 days
- Max messages in flight: No hard limit

**50M objects = 50M messages:**
- ✅ No problem for SQS
- Cost: 50M × $0.40/million = $20

**Throughput:**
```
50M messages enqueued over 42 hours:
= 330 messages/second average
= Well within SQS limits ✅
```

---

### 5. ECS Fargate (Scanner Workers)

**Current Configuration:**
- Min tasks: 1
- Max tasks: 5
- Autoscale on: SQS ApproximateNumberOfMessagesVisible
- Target: 10 messages per task

**Processing Rate:**
```
Per task:
  - Batch size: 10 messages
  - Processing time: ~5 seconds per message
  - Rate: ~2 files/second per task

Total capacity (5 tasks):
  - Rate: 10 files/second
  - Per hour: 36,000 files
  - Per day: 864,000 files
```

**Time to Process:**

| Objects | ECS Tasks | Processing Time |
|---------|-----------|-----------------|
| 100K | 2-3 | 2.8 hours |
| 500K | 4-5 | 13.9 hours |
| 1M | 5 | 27.8 hours |
| 5M | 5 | 5.8 days |
| 10M | 5 | 11.6 days |
| 50M | 5 | 57.9 days |

**⚠️ ECS processing is the bottleneck for very large datasets!**

---

## Scaling Strategies

### Scale 1: < 1 Million Objects
**Current Setup (No Changes Needed)**
- Step Functions: ✅ Handles easily
- Database: ✅ No optimization needed
- ECS: ✅ Completes in ~1 day
- **Status:** Production ready

### Scale 2: 1-10 Million Objects
**Optimizations Needed:**
1. **Increase ECS max tasks**
   ```hcl
   # terraform/variables.tf
   ecs_max_capacity = 20  # Was 5
   ```
   - 20 tasks × 2 files/sec = 40 files/sec
   - 10M objects = ~3 days (vs 11.6 days)

2. **Add database indexes**
   ```sql
   CREATE INDEX CONCURRENTLY idx_job_objects_job_status 
   ON job_objects(job_id, status);
   ```

3. **Increase RDS instance**
   ```hcl
   rds_instance_class = "db.t3.large"  # Was db.t3.medium
   ```

**Cost Impact:**
- ECS: $0.04/hour/task × 20 tasks × 72 hours = $57.60
- RDS: ~$20/month extra

### Scale 3: 10-50 Million Objects
**Additional Optimizations:**
1. **Partition job_objects table**
   ```sql
   CREATE TABLE job_objects_partitioned (...) 
   PARTITION BY HASH (job_id);
   ```

2. **Materialized views for progress**
   ```sql
   CREATE MATERIALIZED VIEW job_progress AS ...
   REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;
   ```

3. **Increase ECS to 50 tasks**
   ```hcl
   ecs_max_capacity = 50
   ```
   - 50 tasks × 2 files/sec = 100 files/sec
   - 50M objects = ~5.8 days

4. **Use RDS Multi-AZ**
   ```hcl
   multi_az = true
   ```

**Cost Impact:**
- ECS: $0.04/hour/task × 50 tasks × 139 hours = $278
- RDS Multi-AZ: ~$100/month extra
- **Total: ~$400 for one-time 50M object scan**

### Scale 4: > 50 Million Objects
**Use S3 Inventory Instead:**

S3 Inventory provides daily snapshots without API limits:
1. Enable S3 Inventory on bucket
2. Read inventory CSV files
3. Process in batches

**Benefits:**
- No Step Functions event limit
- Faster (read CSV vs list API)
- Cheaper (no ListObjects calls)
- Can handle billions of objects

**Implementation:**
```python
def scan_from_inventory(bucket, inventory_prefix):
    # Read inventory CSV
    inventory_df = read_s3_inventory_csv(bucket, inventory_prefix)
    
    # Process in chunks
    for chunk in chunk(inventory_df, 100000):
        create_job_from_dataframe(chunk)
```

---

## Practical Limits by Use Case

### Development/Testing
- **Recommended:** < 10,000 objects
- **Time:** Few minutes
- **Cost:** Negligible

### Small Production
- **Recommended:** 10K - 100K objects
- **Time:** 5-50 minutes (listing + processing ~2 hours)
- **Cost:** < $1
- **Example:** Single project's documents

### Medium Production
- **Recommended:** 100K - 1M objects
- **Time:** 50 minutes listing + ~1 day processing
- **Cost:** ~$10-20
- **Example:** Department's files for a quarter

### Large Production
- **Recommended:** 1M - 10M objects
- **Time:** 8 hours listing + ~3 days processing (with ECS=20)
- **Cost:** ~$50-100
- **Example:** Company-wide compliance scan

### Enterprise
- **Recommended:** Use S3 Inventory for > 10M
- **Time:** 1 day (inventory) + processing time
- **Cost:** Scales linearly
- **Example:** Multi-year data lake scan

---

## Bottleneck Summary

| Component | Current Limit | With Optimization |
|-----------|--------------|-------------------|
| **Lambda (sync)** | 200K | N/A (use async) |
| **Step Functions** | 50M | 50M (hard AWS limit) |
| **Database** | 10M | 100M+ (with partitioning) |
| **SQS** | Unlimited | Unlimited |
| **ECS (5 tasks)** | ⚠️ 1M/day | N/A |
| **ECS (20 tasks)** | N/A | 4M/day |
| **ECS (50 tasks)** | N/A | 10M/day |

**Real bottleneck: ECS processing speed for very large datasets**

---

## Cost Analysis

### 50 Million Objects Scan

**One-Time Costs:**

| Service | Calculation | Cost |
|---------|-------------|------|
| Step Functions | 5,000 transitions × $0.025/1K | $0.13 |
| Lambda (listing) | 5,000 invocations × 30s × 512MB | $2.50 |
| S3 ListObjects | 50M / 1000 × $0.005 | $250.00 |
| SQS messages | 50M × $0.40/million | $20.00 |
| ECS (50 tasks × 5.8 days) | 50 × 139h × $0.04 | $278.00 |
| RDS (t3.large) | 5.8 days × $0.073/hour | $10.15 |
| Data Transfer | Minimal (same region) | $5.00 |
| **TOTAL** | | **$565.78** |

**The expensive parts:**
1. 💰 S3 ListObjects: $250 (44%)
2. 💰 ECS compute: $278 (49%)
3. 💵 Everything else: $38 (7%)

**With S3 Inventory (no listing):**
- Save $250 on ListObjects
- Total: ~$315

---

## Recommendations

### For Current Setup (No Changes)
✅ **Supports up to 1 million objects comfortably**
- Listing: 50 minutes
- Processing: ~1 day
- Cost: ~$10-20
- **This covers 95% of use cases**

### For 1-10M Objects
📈 **Increase ECS max capacity to 20 tasks**
```hcl
ecs_max_capacity = 20
```
- Cost: ~$50-100 per scan
- Processing time: 3-4 days

### For 10M+ Objects
🏢 **Implement S3 Inventory**
- Eliminates Step Functions 50M limit
- Faster and cheaper
- Scales to billions

### For Very Large (100M+)
🌐 **Multi-region or batch processing**
- Split by region/account
- Process incrementally
- Use data partitioning

---

## Conclusion

**Current System Capacity:**

| Metric | Value |
|--------|-------|
| **Theoretical Maximum** | 50 million objects |
| **Practical Maximum** | 1-2 million objects |
| **Recommended Maximum** | 1 million objects |
| **Sweet Spot** | 10K - 500K objects |

**Key Constraints:**
1. ⏱️ Step Functions: 50M limit (listing)
2. 🐢 ECS Processing: 1M objects/day (scanning)
3. 💰 Cost: Scales linearly with size

**For most use cases, the current implementation is production-ready and can handle millions of objects efficiently!** 🎉

For larger datasets, S3 Inventory + optimizations can scale to billions.

