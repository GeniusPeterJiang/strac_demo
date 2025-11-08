"""
Lambda API handler for S3 Scanner.
Provides endpoints for triggering scans, checking job status, and retrieving results.
"""
import os
import json
import uuid
import logging
import boto3
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError
import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AWS clients
sqs_client = boto3.client('sqs', region_name=os.getenv('AWS_REGION', 'us-west-2'))
s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-west-2'))


def get_db_connection():
    """Get database connection."""
    host = os.getenv("RDS_PROXY_ENDPOINT", "").split(":")[0]
    port = os.getenv("RDS_PORT", "5432")
    dbname = os.getenv("RDS_DBNAME", "scanner_db")
    user = os.getenv("RDS_USERNAME", "scanner_admin")
    password = os.getenv("RDS_PASSWORD", "")
    
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode='require'
    )


def create_response(status_code: int, body: Dict[str, Any], 
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Create API Gateway response."""
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
    }
    
    if headers:
        default_headers.update(headers)
    
    return {
        "statusCode": status_code,
        "headers": default_headers,
        "body": json.dumps(body)
    }


def list_s3_objects(bucket: str, prefix: str = "", max_keys: int = 1000) -> list:
    """
    List S3 objects with prefix fan-out for scalability.
    
    Args:
        bucket: S3 bucket name
        prefix: Object key prefix
        max_keys: Maximum number of keys to return
        
    Returns:
        List of object dictionaries with bucket, key, etag
    """
    objects = []
    paginator = s3_client.get_paginator('list_objects_v2')
    
    try:
        page_iterator = paginator.paginate(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=1000  # S3 API limit per page
        )
        
        for page in page_iterator:
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects.append({
                        'bucket': bucket,
                        'key': obj['Key'],
                        'etag': obj.get('ETag', '').strip('"'),
                        'size': obj.get('Size', 0)
                    })
                    
                    if len(objects) >= max_keys:
                        return objects
        
        return objects
    except ClientError as e:
        logger.error(f"Error listing S3 objects: {e}")
        raise


def prefix_fanout_list(bucket: str, prefix: str = "") -> list:
    """
    Use prefix fan-out to parallelize S3 listing.
    For very large buckets, this can be extended to use S3 Inventory.
    
    Args:
        bucket: S3 bucket name
        prefix: Object key prefix
        
    Returns:
        List of object dictionaries
    """
    # For now, use standard listing
    # In production, you might want to:
    # 1. Use S3 Inventory for very large buckets
    # 2. Use prefix fan-out (a-z, 0-9) for parallel listing
    # 3. Use S3 Batch Operations for massive scale
    
    return list_s3_objects(bucket, prefix, max_keys=100000)


def create_scan_job(bucket: str, prefix: str = "") -> Dict[str, Any]:
    """
    Create a new scan job and enqueue S3 objects.
    
    Args:
        bucket: S3 bucket name
        prefix: Object key prefix (optional)
        
    Returns:
        Job information dictionary
    """
    job_id = str(uuid.uuid4())
    queue_url = os.getenv("SQS_QUEUE_URL")
    
    if not queue_url:
        raise ValueError("SQS_QUEUE_URL environment variable not set")
    
    # List S3 objects
    logger.info(f"Listing objects in s3://{bucket}/{prefix}")
    objects = prefix_fanout_list(bucket, prefix)
    logger.info(f"Found {len(objects)} objects")
    
    # Create job record in database
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Insert job (job_id is UUID)
            cur.execute("""
                INSERT INTO jobs (job_id, bucket, prefix, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (job_id, bucket, prefix))
            
            # Insert job objects
            if objects:
                insert_query = """
                    INSERT INTO job_objects (job_id, bucket, key, etag, status, updated_at)
                    VALUES (%s, %s, %s, %s, 'queued', NOW())
                """
                values = [(job_id, obj['bucket'], obj['key'], obj['etag']) for obj in objects]
                
                from psycopg2.extras import execute_batch
                execute_batch(cur, insert_query, values, page_size=1000)
            
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error creating job: {e}")
        raise
    finally:
        if conn:
            conn.close()
    
    # Enqueue messages to SQS
    messages_sent = 0
    batch_size = 10  # SQS batch limit
    
    for i in range(0, len(objects), batch_size):
        batch = objects[i:i + batch_size]
        
        entries = [
            {
                'Id': str(j),
                'MessageBody': json.dumps({
                    'job_id': job_id,
                    'bucket': obj['bucket'],
                    'key': obj['key'],
                    'etag': obj['etag']
                })
            }
            for j, obj in enumerate(batch)
        ]
        
        try:
            response = sqs_client.send_message_batch(
                QueueUrl=queue_url,
                Entries=entries
            )
            messages_sent += len(entries) - len(response.get('Failed', []))
        except ClientError as e:
            logger.error(f"Error sending messages to SQS: {e}")
            # Continue with next batch
    
    logger.info(f"Created job {job_id} with {messages_sent} messages enqueued")
    
    return {
        "job_id": job_id,
        "bucket": bucket,
        "prefix": prefix,
        "total_objects": len(objects),
        "messages_enqueued": messages_sent,
        "status": "queued"
    }


def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get status of a scan job.
    
    Args:
        job_id: Job ID
        
    Returns:
        Job status dictionary
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get job info
            cur.execute("""
                SELECT job_id, bucket, prefix, created_at, updated_at
                FROM jobs
                WHERE job_id = %s
            """, (job_id,))
            
            job = cur.fetchone()
            
            if not job:
                return None
            
            # Get job statistics
            cur.execute("""
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'queued') as queued,
                    COUNT(*) FILTER (WHERE status = 'processing') as processing,
                    COUNT(*) FILTER (WHERE status = 'succeeded') as succeeded,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) as total
                FROM job_objects
                WHERE job_id = %s
            """, (job_id,))
            
            stats = cur.fetchone()
            
            # Get total findings count
            cur.execute("""
                SELECT COUNT(*) as total_findings
                FROM findings
                WHERE job_id = %s
            """, (job_id,))
            
            findings_result = cur.fetchone()
            
            result = dict(job)
            result.update(dict(stats) if stats else {})
            result['total_findings'] = findings_result['total_findings'] if findings_result else 0
            
            # Calculate progress percentage
            total = result.get('total', 0)
            completed = (result.get('succeeded', 0) or 0) + (result.get('failed', 0) or 0)
            result['progress_percent'] = (completed / total * 100) if total > 0 else 0
            
            return result
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise
    finally:
        if conn:
            conn.close()


def get_results(job_id: Optional[str] = None, bucket: Optional[str] = None,
                key: Optional[str] = None, limit: int = 100,
                cursor: Optional[str] = None, offset: Optional[int] = None) -> Dict[str, Any]:
    """
    Retrieve scan results with pagination (supports both cursor and offset).
    
    Args:
        job_id: Optional job ID filter
        bucket: Optional bucket filter
        key: Optional key filter
        limit: Maximum number of results
        cursor: Cursor for pagination (ID of last item from previous page)
        offset: Offset for pagination (fallback if cursor not provided)
        
    Returns:
        Results dictionary with findings and pagination info
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = []
            params = []
            
            if job_id:
                conditions.append("job_id = %s")
                params.append(job_id)
            
            if bucket:
                conditions.append("bucket = %s")
                params.append(bucket)
            
            if key:
                # Support prefix filtering (if key ends with /, treat as prefix)
                if key.endswith('/'):
                    conditions.append("key LIKE %s")
                    params.append(key + "%")
                else:
                    # Exact match or prefix match
                    conditions.append("key LIKE %s")
                    params.append(key + "%")
            
            # Cursor-based pagination (more efficient for large datasets)
            if cursor:
                try:
                    cursor_id = int(cursor)
                    conditions.append("id < %s")
                    params.append(cursor_id)
                except ValueError:
                    # Invalid cursor, ignore it
                    pass
            
            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)
            
            # Get total count
            count_query = f"SELECT COUNT(*) as total FROM findings {where_clause}"
            cur.execute(count_query, params)
            total = cur.fetchone()['total']
            
            # Get findings with cursor-based pagination
            if cursor:
                query = f"""
                    SELECT 
                        id, job_id, bucket, key, detector,
                        masked_match, context, byte_offset, created_at
                    FROM findings
                    {where_clause}
                    ORDER BY id DESC
                    LIMIT %s
                """
                params.append(limit)
            else:
                # Fallback to offset-based pagination
                offset_val = offset if offset is not None else 0
                query = f"""
                    SELECT 
                        id, job_id, bucket, key, detector,
                        masked_match, context, byte_offset, created_at
                    FROM findings
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([limit, offset_val])
            
            cur.execute(query, params)
            findings = [dict(row) for row in cur.fetchall()]
            
            # Generate next cursor (ID of last item)
            next_cursor = None
            if findings:
                next_cursor = str(findings[-1]['id'])
            
            result = {
                "findings": findings,
                "total": total,
                "limit": limit,
                "has_more": len(findings) == limit
            }
            
            if cursor:
                result["cursor"] = cursor
                if next_cursor:
                    result["next_cursor"] = next_cursor
            else:
                offset_val = offset if offset is not None else 0
                result["offset"] = offset_val
                result["has_more"] = (offset_val + limit) < total
            
            return result
    except Exception as e:
        logger.error(f"Error getting results: {e}")
        raise
    finally:
        if conn:
            conn.close()


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for API Gateway requests.
    
    Args:
        event: API Gateway event
        context: Lambda context
        
    Returns:
        API Gateway response
    """
    try:
        # Parse request
        http_method = event.get('requestContext', {}).get('http', {}).get('method', '')
        path = event.get('rawPath', '')
        query_params = event.get('queryStringParameters') or {}
        body_str = event.get('body', '{}')
        
        # Parse body if present
        body = {}
        if body_str:
            try:
                body = json.loads(body_str)
            except json.JSONDecodeError:
                pass
        
        logger.info(f"Request: {http_method} {path}")
        
        # Route requests
        if http_method == 'POST' and path == '/scan':
            # Create scan job
            bucket = body.get('bucket')
            prefix = body.get('prefix', '')
            
            if not bucket:
                return create_response(400, {"error": "bucket is required"})
            
            try:
                result = create_scan_job(bucket, prefix)
                return create_response(200, result)
            except Exception as e:
                logger.error(f"Error creating scan job: {e}")
                return create_response(500, {"error": str(e)})
        
        elif http_method == 'GET' and path.startswith('/jobs/'):
            # Get job status
            job_id = path.split('/')[-1]
            
            try:
                result = get_job_status(job_id)
                if not result:
                    return create_response(404, {"error": "Job not found"})
                return create_response(200, result)
            except Exception as e:
                logger.error(f"Error getting job status: {e}")
                return create_response(500, {"error": str(e)})
        
        elif http_method == 'GET' and path == '/results':
            # Get results (supports bucket, prefix via key filter, limit, cursor)
            job_id = query_params.get('job_id')
            bucket = query_params.get('bucket')
            key = query_params.get('key')  # Can be used as prefix filter
            limit = int(query_params.get('limit', 100))
            cursor = query_params.get('cursor')
            offset = query_params.get('offset')
            offset_int = int(offset) if offset else None
            
            try:
                result = get_results(job_id, bucket, key, limit, cursor, offset_int)
                return create_response(200, result)
            except Exception as e:
                logger.error(f"Error getting results: {e}")
                return create_response(500, {"error": str(e)})
        
        elif http_method == 'OPTIONS':
            # CORS preflight
            return create_response(200, {})
        
        else:
            return create_response(404, {"error": "Not found"})
    
    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        return create_response(500, {"error": "Internal server error"})


# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "rawPath": "/scan",
        "body": json.dumps({
            "bucket": "test-bucket",
            "prefix": "test/"
        })
    }
    
    result = handler(test_event, None)
    print(json.dumps(result, indent=2))

