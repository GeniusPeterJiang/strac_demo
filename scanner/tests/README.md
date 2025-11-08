# Scanner Tests

Complete unit and integration tests using pytest.

## Test Files

- **test_detectors.py** - Pattern detection tests (25 tests)
- **test_db.py** - Database operations tests (16 tests)  
- **test_batch_processor.py** - Batch processing tests (21 tests)
- **test_integration.py** - Integration workflow tests (10 tests)

## Run Tests

```bash
# All tests
./run_tests.sh

# Specific file
pytest test_detectors.py -v

# With coverage
pytest --cov=../ --cov-report=html

# By marker
pytest -m unit        # Unit tests only
pytest -m integration # Integration tests only
```

## Test Coverage

- ✅ Pattern detection (SSN, credit cards, AWS keys, emails, phones)
- ✅ Database operations (insert, update, query, connection pooling)
- ✅ Batch processing (file filtering, S3 download, error handling)
- ✅ Integration workflows (end-to-end processing)

Total: **72 tests** covering all scanner components.
