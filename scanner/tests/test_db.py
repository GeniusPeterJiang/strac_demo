#!/usr/bin/env python3
"""
Unit tests for database operations using pytest.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from utils.db import Database


@pytest.fixture
def mock_psycopg2():
    """Mock psycopg2 module."""
    with patch('utils.db.psycopg2') as mock:
        yield mock


@pytest.fixture
def mock_pool():
    """Mock database connection pool."""
    pool = Mock()
    mock_conn = Mock()
    mock_cursor = Mock()
    
    pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    
    return pool, mock_conn, mock_cursor


@pytest.mark.unit
class TestDatabaseInitialization:
    """Test database initialization and connection."""
    
    def test_init_with_connection_string(self, mock_psycopg2):
        """Should initialize with provided connection string."""
        conn_string = "host=localhost port=5432 dbname=test"
        
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            db = Database(connection_string=conn_string)
            
            assert db.connection_string == conn_string
            mock_pool_class.assert_called_once()
    
    def test_init_from_environment(self, mock_psycopg2):
        """Should build connection string from environment variables."""
        env_vars = {
            'RDS_PROXY_ENDPOINT': 'test-proxy.example.com:5432',
            'RDS_PORT': '5432',
            'RDS_DBNAME': 'scanner_db',
            'RDS_USERNAME': 'test_user',
            'RDS_PASSWORD': 'test_pass'
        }
        
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class, \
             patch.dict('os.environ', env_vars):
            db = Database()
            
            assert 'test-proxy.example.com' in db.connection_string
            assert 'scanner_db' in db.connection_string
            assert 'test_user' in db.connection_string


@pytest.mark.unit
class TestInsertFindings:
    """Test inserting findings into database."""
    
    def test_insert_findings_success(self, mock_psycopg2):
        """Should insert findings and return count."""
        findings = [
            {
                'detector': 'ssn',
                'masked_match': 'XXX-XX-6789',
                'context': 'My SSN is...',
                'byte_offset': 10
            },
            {
                'detector': 'email',
                'masked_match': '***MASKED***',
                'context': 'Email: user@example.com',
                'byte_offset': 50
            }
        ]
        
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            
            with patch('utils.db.execute_batch') as mock_execute_batch:
                result = db.insert_findings(
                    findings=findings,
                    job_id='job-123',
                    bucket='test-bucket',
                    key='test/file.txt',
                    etag='abc123'
                )
                
                assert result == 2
                mock_execute_batch.assert_called_once()
                mock_conn.commit.assert_called_once()
    
    def test_insert_empty_findings(self, mock_psycopg2):
        """Should handle empty findings list."""
        with patch('utils.db.ThreadedConnectionPool'):
            db = Database()
            result = db.insert_findings([], 'job-123', 'bucket', 'key', 'etag')
            assert result == 0
    
    def test_insert_findings_handles_duplicate_context(self, mock_psycopg2):
        """Should handle findings without context field."""
        findings = [
            {
                'detector': 'ssn',
                'masked_match': 'XXX-XX-6789',
                'byte_offset': 10
                # No 'context' field
            }
        ]
        
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            
            with patch('utils.db.execute_batch') as mock_execute_batch:
                result = db.insert_findings(findings, 'job-123', 'bucket', 'key', 'etag')
                
                # Should use empty string for missing context
                call_args = mock_execute_batch.call_args[0]
                values = call_args[2][0]
                assert values[6] == ''  # context field


@pytest.mark.unit
class TestUpdateJobObjectStatus:
    """Test updating job object status."""
    
    def test_update_status_success(self, mock_psycopg2):
        """Should update job object status."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.rowcount = 1
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            result = db.update_job_object_status(
                job_id='job-123',
                bucket='test-bucket',
                key='test/file.txt',
                status='succeeded',
                etag='abc123'
            )
            
            assert result is True
            mock_cursor.execute.assert_called_once()
            mock_conn.commit.assert_called_once()
    
    def test_update_status_with_error(self, mock_psycopg2):
        """Should update status with error message."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.rowcount = 1
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            result = db.update_job_object_status(
                job_id='job-123',
                bucket='test-bucket',
                key='test/file.txt',
                status='failed',
                etag='abc123',
                last_error='Connection timeout'
            )
            
            assert result is True
            call_args = mock_cursor.execute.call_args[0]
            assert 'Connection timeout' in call_args[1]
    
    def test_update_status_no_rows_affected(self, mock_psycopg2):
        """Should return False when no rows updated."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.rowcount = 0
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            result = db.update_job_object_status(
                'job-123', 'bucket', 'key', 'succeeded', 'etag'
            )
            
            assert result is False


@pytest.mark.unit
class TestGetJobStats:
    """Test retrieving job statistics."""
    
    def test_get_job_stats_success(self, mock_psycopg2):
        """Should return job statistics."""
        mock_stats = {
            'queued': 5,
            'processing': 2,
            'succeeded': 10,
            'failed': 1,
            'total': 18,
            'total_findings': 45
        }
        
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.return_value = mock_stats
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            result = db.get_job_stats('job-123')
            
            assert result['queued'] == 5
            assert result['succeeded'] == 10
            assert result['total'] == 18
            assert result['total_findings'] == 45
    
    def test_get_job_stats_no_data(self, mock_psycopg2):
        """Should return zeros when job not found."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.return_value = None
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            result = db.get_job_stats('nonexistent-job')
            
            assert result['queued'] == 0
            assert result['total'] == 0


@pytest.mark.unit
class TestGetFindings:
    """Test retrieving findings with pagination."""
    
    def test_get_findings_with_pagination(self, mock_psycopg2):
        """Should retrieve findings with limit and offset."""
        mock_findings = [
            {'id': 1, 'detector': 'ssn', 'masked_match': 'XXX-XX-6789'},
            {'id': 2, 'detector': 'email', 'masked_match': '***MASKED***'}
        ]
        
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = mock_findings
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            result = db.get_findings(limit=10, offset=0)
            
            assert len(result) == 2
            mock_cursor.execute.assert_called_once()
    
    def test_get_findings_with_filters(self, mock_psycopg2):
        """Should filter findings by job_id, bucket, key."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchall.return_value = []
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            result = db.get_findings(
                job_id='job-123',
                bucket='test-bucket',
                key='test/file.txt',
                limit=100,
                offset=0
            )
            
            # Check that WHERE clause was added
            call_args = mock_cursor.execute.call_args[0]
            sql = call_args[0]
            assert 'WHERE' in sql
            assert 'job_id = %s' in sql
            assert 'bucket = %s' in sql
            assert 'key = %s' in sql


@pytest.mark.unit
class TestDatabaseConnectionPool:
    """Test connection pool management."""
    
    def test_connection_pool_initialized(self, mock_psycopg2):
        """Should initialize connection pool with correct parameters."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            db = Database()
            
            # Should be called with minconn=2, maxconn=10 (defaults)
            mock_pool_class.assert_called_once()
            call_args = mock_pool_class.call_args[0]
            assert call_args[0] == 2  # minconn
            assert call_args[1] == 10  # maxconn
    
    def test_connection_returned_to_pool(self, mock_psycopg2):
        """Should return connection to pool after use."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.return_value = None
            
            mock_pool_class.return_value = mock_pool
            mock_pool.getconn.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            
            db = Database()
            db.get_job_stats('job-123')
            
            # Connection should be returned to pool
            mock_pool.putconn.assert_called_once_with(mock_conn)
    
    def test_close_pool(self, mock_psycopg2):
        """Should close all connections in pool."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_pool_class.return_value = mock_pool
            
            db = Database()
            db.close()
            
            mock_pool.closeall.assert_called_once()


@pytest.mark.integration
class TestDatabaseErrorHandling:
    """Test database error handling."""
    
    def test_handles_connection_error(self, mock_psycopg2):
        """Should handle connection errors gracefully."""
        with patch('utils.db.ThreadedConnectionPool') as mock_pool_class:
            mock_pool = Mock()
            mock_pool.getconn.side_effect = Exception('Connection failed')
            mock_pool_class.return_value = mock_pool
            
            db = Database()
            
            with pytest.raises(Exception):
                db.get_job_stats('job-123')

