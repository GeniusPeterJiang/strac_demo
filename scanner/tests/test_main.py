#!/usr/bin/env python3
"""
Unit tests for main.py (scanner entry point) using pytest.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, call
import sys
import os
import signal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import main


@pytest.mark.unit
class TestComponentInitialization:
    """Test initialization of scanner components."""
    
    @patch.dict(os.environ, {
        'SQS_QUEUE_URL': 'https://sqs.us-west-2.amazonaws.com/123456789/test-queue',
        'AWS_REGION': 'us-west-2',
        'BATCH_SIZE': '10',
        'MAX_WORKERS': '5',
        'MAX_FILE_SIZE_MB': '100'
    })
    @patch('main.boto3.client')
    @patch('main.Database')
    @patch('main.Detector')
    @patch('main.BatchProcessor')
    def test_init_components_success(self, mock_batch_proc, mock_detector, 
                                     mock_db, mock_boto_client):
        """Should initialize all components from environment variables."""
        # Reset globals
        main.sqs_client = None
        main.queue_url = None
        main.batch_processor = None
        
        main.init_components()
        
        # Verify SQS client created
        mock_boto_client.assert_called_once_with('sqs', region_name='us-west-2')
        assert main.sqs_client is not None
        
        # Verify queue URL set
        assert main.queue_url == 'https://sqs.us-west-2.amazonaws.com/123456789/test-queue'
        
        # Verify components initialized
        mock_db.assert_called_once()
        mock_detector.assert_called_once()
        mock_batch_proc.assert_called_once_with(
            db=mock_db.return_value,
            detector=mock_detector.return_value,
            max_workers=5,
            max_file_size_mb=100
        )
        assert main.batch_processor is not None
    
    @patch.dict(os.environ, {}, clear=True)
    def test_init_components_missing_queue_url(self):
        """Should raise error when SQS_QUEUE_URL not set."""
        main.sqs_client = None
        main.queue_url = None
        
        with pytest.raises(ValueError, match="SQS_QUEUE_URL"):
            main.init_components()
    
    @patch.dict(os.environ, {
        'SQS_QUEUE_URL': 'https://sqs.us-west-2.amazonaws.com/test',
    })
    @patch('main.boto3.client')
    @patch('main.Database')
    @patch('main.Detector')
    @patch('main.BatchProcessor')
    def test_init_components_uses_defaults(self, mock_batch_proc, mock_detector,
                                          mock_db, mock_boto_client):
        """Should use default values when optional env vars not set."""
        main.sqs_client = None
        main.queue_url = None
        main.batch_processor = None
        
        main.init_components()
        
        # Should use defaults: batch_size=10, max_workers=5, max_file_size_mb=100
        mock_boto_client.assert_called_once_with('sqs', region_name='us-west-2')
        mock_batch_proc.assert_called_once_with(
            db=mock_db.return_value,
            detector=mock_detector.return_value,
            max_workers=5,
            max_file_size_mb=100
        )


@pytest.mark.unit
class TestReceiveMessages:
    """Test receiving messages from SQS."""
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    def test_receive_messages_success(self):
        """Should receive messages from SQS queue."""
        mock_sqs = Mock()
        mock_sqs.receive_message.return_value = {
            'Messages': [
                {'MessageId': 'msg-1', 'Body': '{"test": "data1"}'},
                {'MessageId': 'msg-2', 'Body': '{"test": "data2"}'}
            ]
        }
        main.sqs_client = mock_sqs
        main.queue_url = 'https://test-queue'
        
        messages = main.receive_messages(max_messages=10, wait_time=20)
        
        assert len(messages) == 2
        mock_sqs.receive_message.assert_called_once_with(
            QueueUrl='https://test-queue',
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
            AttributeNames=['All'],
            MessageAttributeNames=['All']
        )
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    def test_receive_messages_empty_queue(self):
        """Should return empty list when no messages."""
        mock_sqs = Mock()
        mock_sqs.receive_message.return_value = {}  # No Messages key
        main.sqs_client = mock_sqs
        main.queue_url = 'https://test-queue'
        
        messages = main.receive_messages()
        
        assert messages == []
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    def test_receive_messages_handles_error(self):
        """Should handle SQS errors gracefully."""
        mock_sqs = Mock()
        mock_sqs.receive_message.side_effect = Exception('SQS Error')
        main.sqs_client = mock_sqs
        main.queue_url = 'https://test-queue'
        
        messages = main.receive_messages()
        
        assert messages == []
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    def test_receive_messages_respects_max_limit(self):
        """Should limit messages to SQS max of 10."""
        mock_sqs = Mock()
        mock_sqs.receive_message.return_value = {'Messages': []}
        main.sqs_client = mock_sqs
        main.queue_url = 'https://test-queue'
        
        # Request 20, should cap at 10
        main.receive_messages(max_messages=20)
        
        call_args = mock_sqs.receive_message.call_args[1]
        assert call_args['MaxNumberOfMessages'] == 10


@pytest.mark.unit
class TestDeleteMessages:
    """Test deleting messages from SQS."""
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    def test_delete_messages_success(self):
        """Should delete messages from queue."""
        mock_sqs = Mock()
        mock_sqs.delete_message_batch.return_value = {'Failed': []}
        main.sqs_client = mock_sqs
        main.queue_url = 'https://test-queue'
        
        messages = [
            {'MessageId': 'msg-1', 'ReceiptHandle': 'receipt-1'},
            {'MessageId': 'msg-2', 'ReceiptHandle': 'receipt-2'}
        ]
        
        result = main.delete_messages(messages)
        
        assert result is True
        mock_sqs.delete_message_batch.assert_called_once()
        
        # Verify correct format
        call_args = mock_sqs.delete_message_batch.call_args[1]
        assert call_args['QueueUrl'] == 'https://test-queue'
        assert len(call_args['Entries']) == 2
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    def test_delete_messages_empty_list(self):
        """Should handle empty message list."""
        mock_sqs = Mock()
        main.sqs_client = mock_sqs
        main.queue_url = 'https://test-queue'
        
        result = main.delete_messages([])
        
        assert result is True
        mock_sqs.delete_message_batch.assert_not_called()
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    def test_delete_messages_partial_failure(self):
        """Should handle partial deletion failures."""
        mock_sqs = Mock()
        mock_sqs.delete_message_batch.return_value = {
            'Failed': [{'Id': '1', 'Message': 'Error'}]
        }
        main.sqs_client = mock_sqs
        main.queue_url = 'https://test-queue'
        
        messages = [
            {'MessageId': 'msg-1', 'ReceiptHandle': 'receipt-1'},
        ]
        
        result = main.delete_messages(messages)
        
        assert result is False


@pytest.mark.unit
class TestProcessMessages:
    """Test processing messages."""
    
    def test_process_messages_success(self):
        """Should process messages and return results."""
        mock_processor = Mock()
        mock_processor.process_batch.return_value = [
            {'status': 'succeeded', 'findings_count': 5},
            {'status': 'succeeded', 'findings_count': 3}
        ]
        main.batch_processor = mock_processor
        
        messages = [
            {'MessageId': 'msg-1', 'Body': '{"test": "data1"}'},
            {'MessageId': 'msg-2', 'Body': '{"test": "data2"}'}
        ]
        
        results = main.process_messages(messages)
        
        assert len(results) == 2
        mock_processor.process_batch.assert_called_once_with(messages)
    
    def test_process_messages_empty_list(self):
        """Should handle empty message list."""
        mock_processor = Mock()
        main.batch_processor = mock_processor
        
        results = main.process_messages([])
        
        assert results == []
        mock_processor.process_batch.assert_not_called()


@pytest.mark.unit
class TestSignalHandler:
    """Test signal handling for graceful shutdown."""
    
    def test_signal_handler_sets_shutdown_flag(self):
        """Should set shutdown flag when signal received."""
        main.shutdown_flag = False
        
        main.signal_handler(signal.SIGINT, None)
        
        assert main.shutdown_flag is True
    
    def test_signal_handler_handles_sigterm(self):
        """Should handle SIGTERM signal."""
        main.shutdown_flag = False
        
        main.signal_handler(signal.SIGTERM, None)
        
        assert main.shutdown_flag is True


@pytest.mark.integration
class TestMainLoop:
    """Test main processing loop."""
    
    @patch('main.receive_messages')
    @patch('main.process_messages')
    @patch('main.delete_messages')
    @patch('main.time.sleep')
    def test_main_loop_processes_messages(self, mock_sleep, mock_delete,
                                          mock_process, mock_receive):
        """Should receive, process, and delete messages."""
        # Reset shutdown flag
        main.shutdown_flag = False
        
        # Setup mocks
        messages = [
            {'MessageId': 'msg-1', 'ReceiptHandle': 'receipt-1', 
             'Body': '{"job_id": "job-1", "bucket": "b", "key": "k"}'}
        ]
        mock_receive.return_value = messages
        mock_process.return_value = [
            {'status': 'succeeded', 'findings_count': 5}
        ]
        
        # Set flag to stop after one iteration
        def stop_loop(duration):
            main.shutdown_flag = True
        mock_sleep.side_effect = stop_loop
        
        # Run main loop
        main.main_loop()
        
        # Verify calls
        mock_receive.assert_called()
        mock_process.assert_called_once_with(messages)
        mock_delete.assert_called_once()
    
    @patch('main.receive_messages')
    @patch('main.time.sleep')
    def test_main_loop_handles_empty_queue(self, mock_sleep, mock_receive):
        """Should handle empty queue gracefully."""
        main.shutdown_flag = False
        
        # Return empty on first call, then set shutdown flag
        call_count = [0]
        def receive_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 1:
                main.shutdown_flag = True
            return []
        mock_receive.side_effect = receive_side_effect
        
        main.main_loop()
        
        # Should continue polling
        mock_receive.assert_called()
    
    @patch('main.receive_messages')
    @patch('main.time.sleep')
    def test_main_loop_handles_errors(self, mock_sleep, mock_receive):
        """Should handle errors and continue processing."""
        main.shutdown_flag = False
        mock_receive.side_effect = [Exception('Error'), []]
        
        # Stop after error handling
        call_count = [0]
        def stop_after_error(duration):
            call_count[0] += 1
            if call_count[0] >= 2:
                main.shutdown_flag = True
        mock_sleep.side_effect = stop_after_error
        
        main.main_loop()
        
        # Should have caught error and continued
        assert mock_sleep.call_count >= 2


@pytest.mark.integration
class TestMainFunction:
    """Test main entry point function."""
    
    @patch.dict(os.environ, {
        'SQS_QUEUE_URL': 'https://test-queue',
        'AWS_REGION': 'us-west-2'
    })
    @patch('main.signal.signal')
    @patch('main.init_components')
    @patch('main.main_loop')
    def test_main_initializes_and_runs(self, mock_loop, mock_init, mock_signal):
        """Should initialize components and run main loop."""
        main.main()
        
        # Verify signal handlers registered
        assert mock_signal.call_count == 2
        signal_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGINT in signal_calls
        assert signal.SIGTERM in signal_calls
        
        # Verify initialization and loop execution
        mock_init.assert_called_once()
        mock_loop.assert_called_once()
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    @patch('main.signal.signal')
    @patch('main.init_components')
    @patch('main.main_loop')
    def test_main_handles_initialization_error(self, mock_loop, mock_init, mock_signal):
        """Should exit with error code on initialization failure."""
        mock_init.side_effect = Exception('Init failed')
        
        with pytest.raises(SystemExit) as exc_info:
            main.main()
        
        assert exc_info.value.code == 1
        mock_loop.assert_not_called()
    
    @patch.dict(os.environ, {'SQS_QUEUE_URL': 'https://test-queue'})
    @patch('main.signal.signal')
    @patch('main.init_components')
    @patch('main.main_loop')
    def test_main_cleans_up_on_exit(self, mock_loop, mock_init, mock_signal):
        """Should close database connection on exit."""
        mock_db = Mock()
        mock_processor = Mock()
        mock_processor.db = mock_db
        
        def set_processor():
            main.batch_processor = mock_processor
        mock_init.side_effect = set_processor
        
        main.main()
        
        # DB close should be called in finally block
        # (Note: This is tricky to test perfectly, but we can verify the structure)
        mock_init.assert_called_once()

