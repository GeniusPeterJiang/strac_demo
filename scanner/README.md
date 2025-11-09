# Scanner Component

This directory contains the scanner worker that processes S3 objects to detect sensitive data.

## Quick Local Testing

### Run All Tests

```bash
cd tests
./run_tests.sh
```

This will run both detector tests and integration tests without requiring AWS infrastructure.

### Run Individual Tests

**Detector tests only:**
```bash
cd tests
python3 test_detectors.py
```

**Integration tests only:**
```bash
cd tests
python3 test_integration.py
```

## What Gets Tested Locally

✅ **Pattern Detection** - All sensitive data patterns (SSN, credit cards, AWS keys, emails, phones)  
✅ **Masking Logic** - Proper masking of detected sensitive data  
✅ **Luhn Validation** - Credit card validation using Luhn algorithm  
✅ **File Filtering** - File type and size filtering logic  
✅ **Message Parsing** - SQS message format handling  
✅ **Workflow Simulation** - End-to-end processing with local test files  

## Components

### Core Files

- **`main.py`** - Entry point for the scanner worker
- **`batch_processor.py`** - Batch processing logic for S3 objects
- **`utils/detectors.py`** - Pattern detection and validation
- **`utils/db.py`** - Database operations
- **`requirements.txt`** - Python dependencies

### Test Files

- **`tests/test_detectors.py`** - Unit tests for pattern detection
- **`tests/test_integration.py`** - Integration tests with simulated workflow
- **`tests/run_tests.sh`** - Convenience script to run all tests
- **`tests/__init__.py`** - Test package initialization
- **`LOCAL_TESTING.md`** - Detailed local testing guide

## Supported File Types

The scanner processes the following text file types:
- `.txt` - Text files
- `.csv` - CSV files
- `.json` - JSON files
- `.log` - Log files

Maximum file size: **100 MB** (configurable via `MAX_FILE_SIZE_MB` environment variable)

## Sensitive Data Patterns Detected

| Pattern | Description | Example | Validation |
|---------|-------------|---------|------------|
| SSN | Social Security Number | 123-45-6789 | Format check |
| Credit Card | Credit card numbers | 4111-1111-1111-1111 | Luhn algorithm |
| AWS Key | AWS access keys | AKIAIOSFODNN7EXAMPLE | Format check |
| AWS Secret | AWS secret keys | (40 chars) | Format check |
| Email | Email addresses | user@example.com | Format check |
| Phone | US phone numbers | (555) 123-4567 | Format check |

## Environment Variables

When running in AWS, the scanner requires these environment variables:

```bash
# Required
SQS_QUEUE_URL=https://sqs.us-west-2.amazonaws.com/...
RDS_PROXY_ENDPOINT=scanner-proxy.proxy-xxx.us-west-2.rds.amazonaws.com:5432
RDS_USERNAME=scanner_admin
RDS_PASSWORD=***
RDS_DBNAME=scanner_db

# Optional (with defaults)
AWS_REGION=us-west-2
BATCH_SIZE=40
MAX_WORKERS=20
MAX_FILE_SIZE_MB=100
```

## Local Development

### Install Dependencies

```bash
pip3 install -r requirements.txt
```

### Test Pattern Detection Interactively

```python
from utils.detectors import Detector

detector = Detector()
content = "My SSN is 123-45-6789"
findings = detector.detect(content)

for f in findings:
    print(f"{f['detector']}: {f['masked_match']}")
```

### Test with Custom Files

```python
from utils.detectors import Detector

# Read your file
with open('myfile.txt', 'r') as f:
    content = f.read()

# Scan it
detector = Detector()
findings = detector.detect(content)

print(f"Found {len(findings)} sensitive data items")
```

## Docker Build

The scanner is containerized for deployment to AWS ECS:

```bash
# Build image
docker build -t scanner:latest .

# Run locally (requires env vars)
docker run --env-file .env scanner:latest
```

## Running in AWS

The scanner runs as an ECS Fargate service that:
1. Polls SQS queue for scan jobs
2. Downloads S3 objects
3. Scans content for sensitive data
4. Stores findings in RDS PostgreSQL
5. Updates job status

See the main project `QUICKSTART.md` for deployment instructions.

## Performance

**Local Test Results:**
- Detector tests: ~0.5 seconds
- Integration tests: ~1-2 seconds
- Pattern matching: ~100+ KB/s per core

**AWS Performance:**
- Depends on ECS task count and file sizes
- Auto-scales based on SQS queue depth
- Typical: 10-50 files/second with default configuration

## Troubleshooting

### Import Errors

```bash
pip3 install -r requirements.txt
```

### Pattern Not Detecting

Check the pattern in `utils/detectors.py` - patterns use Python regex with `re.IGNORECASE` and `re.MULTILINE` flags.

### Credit Card False Positives

Credit cards are validated using the Luhn algorithm. Only valid card numbers are detected.

### File Not Processed

Check file extension (must be .txt, .csv, .json, or .log) and size (must be < 100 MB).

## Next Steps

1. ✅ **Local Testing** - Use `./run_local_tests.sh` (you are here)
2. **AWS Testing** - See `../integration_tests/TESTING.md` for full integration testing
3. **Deployment** - See `../QUICKSTART.md` for AWS deployment

## Documentation

- **`LOCAL_TESTING.md`** - Detailed local testing guide
- **`../integration_tests/TESTING.md`** - Full AWS integration testing
- **`../QUICKSTART.md`** - Quick start deployment guide
- **`../DEPLOYMENT.md`** - Detailed deployment guide
- **`../README.md`** - Project overview and architecture

