#!/usr/bin/env python3
"""
Refresh job progress materialized view.
This script can be run manually or scheduled via cron/EventBridge.
"""

import os
import sys
import psycopg2
from datetime import datetime

def get_db_connection():
    """Get database connection from environment variables."""
    host = os.getenv("RDS_PROXY_ENDPOINT", "").split(":")[0]
    port = os.getenv("RDS_PORT", "5432")
    dbname = os.getenv("RDS_DBNAME", "scanner_db")
    user = os.getenv("RDS_USERNAME", "scanner_admin")
    password = os.getenv("RDS_PASSWORD", "")
    
    if not password:
        print("Error: RDS_PASSWORD environment variable not set")
        sys.exit(1)
    
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode='require',
        connect_timeout=10
    )

def refresh_materialized_view():
    """Refresh the job_progress materialized view."""
    conn = None
    try:
        print(f"[{datetime.now()}] Connecting to database...")
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
                print("Warning: job_progress materialized view does not exist")
                print("Run migration 002_optimize_for_scale.sql first")
                return False
            
            print(f"[{datetime.now()}] Refreshing job_progress materialized view...")
            start_time = datetime.now()
            
            # Refresh concurrently (doesn't lock the view)
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY job_progress;")
            conn.commit()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Get statistics
            cur.execute("""
                SELECT 
                    COUNT(*) as total_jobs,
                    SUM(total_objects) as total_objects,
                    SUM(succeeded_count) as processed_objects,
                    SUM(total_findings) as total_findings
                FROM job_progress;
            """)
            stats = cur.fetchone()
            
            print(f"[{datetime.now()}] ✓ Refresh completed in {duration:.2f}s")
            print(f"  Jobs: {stats[0]}")
            print(f"  Total objects: {stats[1] or 0:,}")
            print(f"  Processed: {stats[2] or 0:,}")
            print(f"  Findings: {stats[3] or 0:,}")
            
            return True
            
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def main():
    """Main entry point."""
    print("=" * 60)
    print("Job Progress Materialized View Refresh")
    print("=" * 60)
    print("")
    
    success = refresh_materialized_view()
    
    print("")
    if success:
        print("✓ Refresh successful")
        sys.exit(0)
    else:
        print("✗ Refresh failed")
        sys.exit(1)

if __name__ == "__main__":
    main()

