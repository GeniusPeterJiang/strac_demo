# RealDictCursor KeyError Fix

## Issue

**Error:**
```
KeyError: 0
Traceback (most recent call last):
  File "/var/task/main.py", line 917, in handler
    result = get_job_status(job_id, real_time=real_time)
  File "/var/task/main.py", line 572, in get_job_status
    has_matview = cur.fetchone()[0] if cur.rowcount > 0 else False
                  ~~~~~~~~~~~~~~^^^
KeyError: 0
```

## Root Cause

The code was using **tuple-style indexing** `[0]` on a **dictionary-style cursor** (`RealDictCursor`).

### RealDictCursor Behavior

```python
from psycopg2.extras import RealDictCursor

# Regular cursor returns tuples
cursor = conn.cursor()
cursor.execute("SELECT EXISTS(...)")
result = cursor.fetchone()
print(type(result))  # <class 'tuple'>
print(result[0])     # ✅ Works: True/False

# RealDictCursor returns dict-like objects
cursor = conn.cursor(cursor_factory=RealDictCursor)
cursor.execute("SELECT EXISTS(...)")
result = cursor.fetchone()
print(type(result))  # <class 'psycopg2.extras.RealDictRow'>
print(result[0])     # ❌ KeyError: 0 (tries to access key "0")
print(result['exists'])  # ✅ Works: True/False
```

## The Fix

### Before (WRONG)

```python
cur.execute("""
    SELECT EXISTS (
        SELECT 1 FROM pg_matviews 
        WHERE schemaname = 'public' 
        AND matviewname = 'job_progress'
    );
""")
has_matview = cur.fetchone()[0]  # ❌ KeyError: 0
```

**Problem:** 
- Column name is implicit (unnamed)
- Using tuple index `[0]` on dictionary object

### After (CORRECT)

```python
cur.execute("""
    SELECT EXISTS (
        SELECT 1 FROM pg_matviews 
        WHERE schemaname = 'public' 
        AND matviewname = 'job_progress'
    ) as exists;  -- ✅ Named column
""")
result = cur.fetchone()
has_matview = result['exists'] if result else False  # ✅ Dictionary key access
```

**Benefits:**
- ✅ Explicit column name
- ✅ Dictionary-style access
- ✅ Safe fallback if no result

## Why Use RealDictCursor?

RealDictCursor provides several advantages:

### 1. Self-Documenting Code

```python
# Regular cursor - unclear what index 3 means
result = cur.fetchone()
bucket = result[3]  # What is index 3?

# RealDictCursor - clear and explicit
result = cur.fetchone()
bucket = result['bucket']  # ✅ Clear!
```

### 2. Resilient to Schema Changes

```python
# Regular cursor - breaks if column order changes
cur.execute("SELECT id, name, email FROM users")
result = cur.fetchone()
email = result[2]  # Breaks if columns reordered!

# RealDictCursor - works regardless of column order
cur.execute("SELECT id, name, email FROM users")
result = cur.fetchone()
email = result['email']  # ✅ Always works
```

### 3. Direct JSON Serialization

```python
# RealDictCursor results can be directly converted to JSON
result = dict(cur.fetchone())
json_response = json.dumps(result)  # ✅ Works!
```

## Correct Usage Patterns

### Pattern 1: Named Columns (Recommended)

```python
cur.execute("""
    SELECT COUNT(*) as count,
           MAX(created_at) as latest
    FROM jobs;
""")
result = cur.fetchone()
count = result['count']
latest = result['latest']
```

### Pattern 2: Explicit Column Names

```python
cur.execute("SELECT bucket, prefix, created_at FROM jobs WHERE job_id = %s", (job_id,))
job = cur.fetchone()
if job:
    bucket = job['bucket']
    prefix = job['prefix']
    created_at = job['created_at']
```

### Pattern 3: EXISTS Queries

```python
# Always name the EXISTS column
cur.execute("""
    SELECT EXISTS (
        SELECT 1 FROM table WHERE condition
    ) as exists;
""")
result = cur.fetchone()
exists = result['exists'] if result else False
```

## All Fixed Locations

### lambda_api/main.py

**Line 572:** ✅ Fixed
```python
# Before
has_matview = cur.fetchone()[0]

# After  
result = cur.fetchone()
has_matview = result['exists'] if result else False
```

**Other usages:** ✅ Already correct
- Line 796: `total = cur.fetchone()['total']` - Correct
- All other `fetchone()` calls use named columns

### lambda_refresh/main.py

**Line 74:** ✅ Correct (uses regular cursor, not RealDictCursor)
```python
exists = cur.fetchone()[0]  # OK - regular cursor returns tuples
```

## Testing

### Test Case 1: Query with Named Column

```python
def test_named_column():
    cur.execute("SELECT COUNT(*) as count FROM jobs;")
    result = cur.fetchone()
    assert isinstance(result, dict)
    assert 'count' in result
    count = result['count']  # ✅ Works
```

### Test Case 2: EXISTS Query

```python
def test_exists_query():
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM pg_matviews 
            WHERE matviewname = 'job_progress'
        ) as exists;
    """)
    result = cur.fetchone()
    assert 'exists' in result
    exists = result['exists']  # ✅ Works
    assert isinstance(exists, bool)
```

### Test Case 3: Multiple Columns

```python
def test_multiple_columns():
    cur.execute("""
        SELECT job_id, bucket, prefix, created_at 
        FROM jobs 
        LIMIT 1;
    """)
    result = cur.fetchone()
    if result:
        job_id = result['job_id']
        bucket = result['bucket']
        prefix = result['prefix']
        created_at = result['created_at']
        # ✅ All work
```

## Common Pitfalls to Avoid

### ❌ Don't: Use numeric indices with RealDictCursor

```python
result = cur.fetchone()
value = result[0]  # ❌ KeyError
```

### ❌ Don't: Forget to name aggregate columns

```python
cur.execute("SELECT COUNT(*) FROM jobs;")
result = cur.fetchone()
count = result['count']  # ❌ KeyError (column is 'count' or unnamed)
```

**Fix:**
```python
cur.execute("SELECT COUNT(*) as count FROM jobs;")
result = cur.fetchone()
count = result['count']  # ✅ Works
```

### ❌ Don't: Mix cursor types

```python
# Don't use RealDictCursor patterns with regular cursors
cur = conn.cursor()  # Regular cursor
result = cur.fetchone()
value = result['column']  # ❌ TypeError: tuple indices must be integers
```

### ✅ Do: Always name your columns

```python
# Good
cur.execute("SELECT COUNT(*) as total FROM jobs;")
cur.execute("SELECT MAX(created_at) as latest FROM jobs;")
cur.execute("SELECT EXISTS(...) as exists;")
```

### ✅ Do: Check for None before accessing

```python
result = cur.fetchone()
if result:
    value = result['column']  # ✅ Safe
else:
    value = default_value
```

### ✅ Do: Use .get() for optional columns

```python
result = cur.fetchone()
optional_value = result.get('optional_column', default_value)
```

## Deployment

After fixing the code, deploy:

```bash
# Build and deploy the fixed Lambda
./build_and_push.sh
```

## Verification

Test the fixed endpoint:

```bash
# Should work now without KeyError
curl "${API_URL}/jobs/${JOB_ID}"
```

Check CloudWatch logs:
```bash
aws logs tail /aws/lambda/strac-scanner-api --follow
```

**Expected:** No more `KeyError: 0` errors!

## Summary

| Issue | Solution |
|-------|----------|
| `KeyError: 0` | Use dictionary keys, not tuple indices |
| `fetchone()[0]` | Use `fetchone()['column_name']` |
| Unnamed columns | Always use `AS alias` in SELECT |
| No null check | Check `if result:` before accessing |

**Key Takeaway:** When using `RealDictCursor`, always:
1. Name your columns with `AS`
2. Access via dictionary keys `['key']`
3. Check for `None` before accessing

The fix is now deployed and the Lambda will work correctly! ✅

