"""
Lambda function to refresh job_progress materialized view.
Triggered by EventBridge every 1 minute.
"""

import os
import json
import logging
from typing import Dict, Any
from datetime import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Import psycopg2 (will be included in Lambda layer or deployment package)
try:
    import psycopg2
    from psycopg2 import Error as PostgresError
except ImportError:
    logger.error("psycopg2 not available - install psycopg2-binary")
    psycopg2 = None
    PostgresError = Exception


def get_db_connection():
    """Get database connection from environment variables."""
    if not psycopg2:
        raise Exception("psycopg2 module not available")
    
    host = os.getenv("RDS_PROXY_ENDPOINT", "").split(":")[0]
    port = int(os.getenv("RDS_PORT", "5432"))
    dbname = os.getenv("RDS_DBNAME", "scanner_db")
    user = os.getenv("RDS_USERNAME")
    password = os.getenv("RDS_PASSWORD")
    
    if not password:
        raise ValueError("RDS_PASSWORD environment variable not set")
    
    logger.info(f"Connecting to database: {host}:{port}/{dbname} as {user}")
    
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode='require',
        connect_timeout=10
    )


def refresh_materialized_view() -> Dict[str, Any]:
    """
    Refresh the job_progress materialized view.
    
    Returns:
        Dict with refresh results and statistics
    """
    conn = None
    try:
        start_time = datetime.now()
        conn = get_db_connection()
        
        with conn.cursor() as cur:
            # Check if materialized view exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_matviews 
                    WHERE schemaname = 'public' 
                    AND matviewname = 'job_progress'
                );
            """)
            exists = cur.fetchone()[0]
            
            if not exists:
                logger.warning("job_progress materialized view does not exist")
                return {
                    'success': False,
                    'error': 'Materialized view job_progress does not exist',
                    'message': 'Run migration 002_optimize_for_scale.sql first'
                }
            
            logger.info("Refreshing job_progress materialized view...")
            
            # Refresh concurrently (doesn't lock the view)
            # Falls back to regular refresh if concurrent fails (first time or no unique index)
            refresh_start = datetime.now()
            try:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;")
                refresh_type = "concurrent"
            except PostgresError as e:
                logger.warning(f"Concurrent refresh failed ({e}), trying regular refresh...")
                cur.execute("REFRESH MATERIALIZED VIEW job_progress;")
                refresh_type = "regular"
            
            refresh_end = datetime.now()
            duration = (refresh_end - refresh_start).total_seconds()
            
            # Get statistics
            cur.execute("""
                SELECT 
                    COUNT(*) as total_jobs,
                    COALESCE(SUM(total_objects), 0) as total_objects,
                    COALESCE(SUM(succeeded_count), 0) as processed_objects,
                    COALESCE(SUM(total_findings), 0) as total_findings,
                    COALESCE(SUM(CASE WHEN queued_count > 0 OR processing_count > 0 THEN 1 ELSE 0 END), 0) as active_jobs
                FROM job_progress;
            """)
            stats = cur.fetchone()
            
            # Update refresh log
            duration_ms = int(duration * 1000)
            cur.execute("""
                INSERT INTO materialized_view_refresh_log 
                (view_name, last_refreshed_at, refresh_duration_ms, total_jobs, total_objects)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (view_name) 
                DO UPDATE SET 
                    last_refreshed_at = EXCLUDED.last_refreshed_at,
                    refresh_duration_ms = EXCLUDED.refresh_duration_ms,
                    total_jobs = EXCLUDED.total_jobs,
                    total_objects = EXCLUDED.total_objects;
            """, ('job_progress', refresh_end, duration_ms, 
                  int(stats[0]) if stats else 0, 
                  int(stats[1]) if stats else 0))
            
            conn.commit()
            
            result = {
                'success': True,
                'duration_seconds': round(duration, 2),
                'refresh_type': refresh_type,
                'timestamp': refresh_end.isoformat(),
                'statistics': {
                    'total_jobs': int(stats[0]) if stats else 0,
                    'total_objects': int(stats[1]) if stats else 0,
                    'processed_objects': int(stats[2]) if stats else 0,
                    'total_findings': int(stats[3]) if stats else 0,
                    'active_jobs': int(stats[4]) if stats else 0
                }
            }
            
            logger.info(f"✓ Refresh completed in {duration:.2f}s ({refresh_type})")
            logger.info(f"  Jobs: {result['statistics']['total_jobs']}")
            logger.info(f"  Total objects: {result['statistics']['total_objects']:,}")
            logger.info(f"  Processed: {result['statistics']['processed_objects']:,}")
            logger.info(f"  Active jobs: {result['statistics']['active_jobs']}")
            logger.info(f"  Refresh timestamp: {refresh_end.isoformat()}")
            
            return result
            
    except PostgresError as e:
        logger.error(f"Database error: {e}")
        return {
            'success': False,
            'error': f'Database error: {str(e)}',
            'error_type': 'PostgresError'
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }
    finally:
        if conn:
            conn.close()


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for EventBridge trigger.
    
    Args:
        event: EventBridge event (contains time, detail-type, etc.)
        context: Lambda context
        
    Returns:
        Response with refresh results
    """
    logger.info(f"Materialized view refresh triggered by EventBridge")
    logger.info(f"Event: {json.dumps(event)}")
    
    try:
        result = refresh_materialized_view()
        
        if result['success']:
            logger.info("✓ Materialized view refresh successful")
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        else:
            logger.error(f"✗ Materialized view refresh failed: {result.get('error')}")
            return {
                'statusCode': 500,
                'body': json.dumps(result)
            }
            
    except Exception as e:
        logger.error(f"Unexpected error in handler: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            })
        }

