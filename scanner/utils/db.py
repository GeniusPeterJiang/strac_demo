"""
Database utilities for storing scan results and job status.
"""
import os
import psycopg2
from psycopg2.extras import execute_batch, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from typing import List, Dict, Optional
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    """Database connection and operation handler."""
    
    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize database connection.
        
        Args:
            connection_string: PostgreSQL connection string.
                              If None, constructs from environment variables.
        """
        if connection_string:
            self.connection_string = connection_string
        else:
            # Construct from environment variables
            host = os.getenv("RDS_PROXY_ENDPOINT", "").split(":")[0]
            port = os.getenv("RDS_PORT", "5432")
            dbname = os.getenv("RDS_DBNAME", "scanner_db")
            user = os.getenv("RDS_USERNAME", "scanner_admin")
            password = os.getenv("RDS_PASSWORD", "")
            
            self.connection_string = (
                f"host={host} port={port} dbname={dbname} "
                f"user={user} password={password} sslmode=require"
            )
        
        # Connection pool for better performance
        self.pool = None
        self._init_pool()
    
    def _init_pool(self, minconn: int = 2, maxconn: int = 10):
        """Initialize connection pool."""
        try:
            self.pool = ThreadedConnectionPool(
                minconn, maxconn, self.connection_string
            )
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        conn = None
        try:
            conn = self.pool.getconn()
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                self.pool.putconn(conn)
    
    def insert_findings(self, findings: List[Dict], job_id: str, 
                       bucket: str, key: str, etag: str) -> int:
        """
        Batch insert findings into database.
        
        Args:
            findings: List of finding dictionaries with detector, masked_match, context, byte_offset
            job_id: Job ID (UUID)
            bucket: S3 bucket name
            key: S3 object key
            etag: S3 object ETag for deduplication
            
        Returns:
            Number of findings inserted
        """
        if not findings:
            return 0
        
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                insert_query = """
                    INSERT INTO findings (
                        job_id, bucket, key, etag, detector, 
                        masked_match, context, byte_offset, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (bucket, key, etag, detector, byte_offset) 
                    DO NOTHING
                """
                
                values = [
                    (
                        job_id, bucket, key, etag,
                        f["detector"], f["masked_match"], 
                        f.get("context", ""), f["byte_offset"]
                    )
                    for f in findings
                ]
                
                execute_batch(cur, insert_query, values, page_size=100)
                conn.commit()
                
                logger.info(f"Inserted {len(findings)} findings for {bucket}/{key}")
                return len(findings)
    
    def update_job_object_status(self, job_id: str, bucket: str, key: str,
                                status: str, etag: str, last_error: Optional[str] = None) -> bool:
        """
        Update status of a job object.
        
        Args:
            job_id: Job ID (UUID)
            bucket: S3 bucket name
            key: S3 object key
            status: Status ('queued', 'processing', 'succeeded', 'failed')
            etag: S3 object ETag
            last_error: Optional error message
            
        Returns:
            True if successful
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                update_query = """
                    UPDATE job_objects
                    SET status = %s, 
                        last_error = %s,
                        updated_at = NOW()
                    WHERE job_id = %s AND bucket = %s AND key = %s AND etag = %s
                """
                
                cur.execute(update_query, (
                    status, last_error, job_id, bucket, key, etag
                ))
                conn.commit()
                
                return cur.rowcount > 0
    
    def get_job_stats(self, job_id: str) -> Dict:
        """
        Get statistics for a job.
        
        Args:
            job_id: Job ID
            
        Returns:
            Dictionary with job statistics
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT 
                        COUNT(*) FILTER (WHERE status = 'queued') as queued,
                        COUNT(*) FILTER (WHERE status = 'processing') as processing,
                        COUNT(*) FILTER (WHERE status = 'succeeded') as succeeded,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed,
                        COUNT(*) as total,
                        SUM(findings_count) as total_findings
                    FROM job_objects
                    WHERE job_id = %s
                """
                
                cur.execute(query, (job_id,))
                result = cur.fetchone()
                
                if result:
                    return dict(result)
                return {
                    "queued": 0,
                    "processing": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "total": 0,
                    "total_findings": 0
                }
    
    def get_findings(self, job_id: Optional[str] = None, 
                    bucket: Optional[str] = None,
                    key: Optional[str] = None,
                    limit: int = 100,
                    offset: int = 0) -> List[Dict]:
        """
        Retrieve findings with pagination.
        
        Args:
            job_id: Optional job ID filter
            bucket: Optional bucket filter
            key: Optional key filter
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            List of finding dictionaries
        """
        with self.get_connection() as conn:
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
                    conditions.append("key = %s")
                    params.append(key)
                
                where_clause = ""
                if conditions:
                    where_clause = "WHERE " + " AND ".join(conditions)
                
                query = f"""
                    SELECT 
                        id, job_id, bucket, key, finding_type,
                        pattern, match_text, position, description, created_at
                    FROM findings
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """
                
                params.extend([limit, offset])
                cur.execute(query, params)
                
                results = cur.fetchall()
                return [dict(row) for row in results]
    
    def close(self):
        """Close connection pool."""
        if self.pool:
            self.pool.closeall()
            logger.info("Database connection pool closed")


def get_db() -> Database:
    """Factory function to get a database instance."""
    return Database()

