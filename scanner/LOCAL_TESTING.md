# Local Testing Guide for Scanner

This guide explains how to test the scanner locally without deploying to AWS.

## Quick Start

### 1. Install Dependencies

```bash
cd /home/peterjiang/strac_demo/scanner

# Install Python dependencies
pip3 install -r requirements.txt
```

### 2. Run Detector Tests

Test the pattern detection logic without any AWS resources:

```bash
cd tests
python3 test_detectors.py
```

This will test:
- SSN detection and masking
- Credit card detection with Luhn validation
- AWS access key detection
- Email address detection
- Phone number detection
- Multiple pattern detection
- Context extraction

**Expected Output:**
```
======================================================================
RUNNING LOCAL DETECTOR TESTS
======================================================================

=== Testing SSN Detection ===
✓ Found SSN in: 'My SSN is 123-45-6789'
  Masked: XXX-XX-6789
...

TEST RESULTS: 8 passed, 0 failed out of 8 tests
======================================================================
```

### 3. Run Integration Tests

Test the scanner workflow with simulated data:

```bash
cd tests
python3 test_integration.py
```

This will test:
- SQS message parsing
- Batch processor file filtering logic
- End-to-end workflow simulation with local files

**Expected Output:**
```
======================================================================
TEST 3: Simulated End-to-End Workflow
======================================================================

Created test directory: /tmp/scanner_test_XXXXXX
  Created: ssn_test.txt
  Created: credit_card.txt
  ...

📄 ssn_test.txt:
   File size: 47 bytes
   Findings: 1
     - ssn: XXX-XX-6789
...

INTEGRATION TEST RESULTS: 3 passed, 0 failed
======================================================================
```

## Test Details

### Test 1: Detector Tests (`tests/test_detectors.py`)

**What it tests:**
- Pattern matching for all sensitive data types
- Masking of detected sensitive data
- Luhn validation for credit cards
- Context extraction around matches
- Max matches per type limiting

**Requirements:**
- ✅ Python 3.12+
- ✅ Only standard library + regex
- ❌ No AWS credentials needed
- ❌ No database needed
- ❌ No network access needed

**Run individually:**
```bash
cd tests
python3 test_detectors.py
```

### Test 2: Integration Tests (`tests/test_integration.py`)

**What it tests:**
- Scanning real file content
- File extension filtering (.txt, .csv, .json, .log)
- File size limits (100 MB max)
- SQS message format parsing
- Complete workflow simulation

**Requirements:**
- ✅ Python 3.12+
- ✅ boto3 installed (but no AWS credentials needed)
- ❌ No database needed
- ❌ No network access needed

**Run individually:**
```bash
cd tests
python3 test_integration.py
```

## Testing Individual Components

### Test Just the Detector

```python
from utils.detectors import Detector

detector = Detector()
content = "My SSN is 123-45-6789 and email is user@example.com"
findings = detector.detect(content)

for finding in findings:
    print(f"{finding['detector']}: {finding['masked_match']}")
```

### Test File Type Filtering

```python
from batch_processor import BatchProcessor
from utils.detectors import Detector

detector = Detector()
processor = BatchProcessor(db=None, detector=detector)

# Test if file should be processed
print(processor.should_process_file("data.txt", 1000))  # True
print(processor.should_process_file("image.png", 1000))  # False
print(processor.should_process_file("large.txt", 200 * 1024 * 1024))  # False (too large)
```

### Create Custom Test Files

```bash
# Create a test file with sensitive data
cat > test_data.txt <<EOF
Customer Information:
Name: John Doe
SSN: 123-45-6789
Email: john.doe@example.com
Phone: (555) 123-4567
Credit Card: 4532-1234-5678-9010
EOF

# Test it with the detector
python3 -c "
from utils.detectors import Detector

with open('test_data.txt', 'r') as f:
    content = f.read()

detector = Detector()
findings = detector.detect(content)

print(f'Found {len(findings)} sensitive data items:')
for f in findings:
    print(f'  - {f[\"detector\"]}: {f[\"masked_match\"]}')
"
```

## Performance Testing Locally

### Test Detection Speed

```python
import time
from utils.detectors import Detector

# Create large test content
content = "\n".join([
    f"Record {i}: SSN 123-45-{6789+i}, Email: user{i}@example.com"
    for i in range(1000)
])

detector = Detector()

start = time.time()
findings = detector.detect(content)
elapsed = time.time() - start

print(f"Scanned {len(content)} bytes in {elapsed:.2f}s")
print(f"Found {len(findings)} findings")
print(f"Rate: {len(content)/elapsed/1024:.2f} KB/s")
```

## Common Issues

### Import Errors

**Problem:** `ModuleNotFoundError: No module named 'boto3'`

**Solution:**
```bash
pip3 install -r requirements.txt
```

### Missing Python 3.12

**Problem:** `python3: command not found` or wrong version

**Solution:**
```bash
# Check version
python3 --version

# If < 3.12, install Python 3.12
sudo apt update
sudo apt install python3.12 python3.12-venv
```

### File Permission Errors

**Problem:** `PermissionError` when running tests

**Solution:**
```bash
chmod +x test_detector.py test_local_integration.py
```

## Next Steps

After local testing succeeds:

1. **Test with Local Database** (optional):
   - Set up a local PostgreSQL instance
   - Run `database_schema.sql` to create tables
   - Set environment variables to connect to local DB
   - Test full integration with database

2. **Test with AWS Resources**:
   - Configure AWS credentials
   - Upload test files to S3
   - Test with real S3 downloads
   - See `docs/TESTING.md` for full AWS testing

3. **Deploy to AWS**:
   - Follow `QUICKSTART.md` for deployment
   - Run end-to-end tests with deployed infrastructure

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now run your tests
from utils.detectors import Detector
detector = Detector()
findings = detector.detect("SSN: 123-45-6789")
```

### Test Specific Patterns

```python
from utils.detectors import Detector, PATTERNS

# Test just SSN pattern
detector = Detector(patterns={'ssn': PATTERNS['ssn']})
findings = detector.detect("My SSN is 123-45-6789")
print(findings)
```

### Validate Pattern Logic

```python
from utils.detectors import Detector

detector = Detector()

# Test credit card Luhn validation
print(detector.validate_credit_card("4532-1234-5678-9010"))  # True
print(detector.validate_credit_card("1234-5678-9012-3456"))  # False

# Test SSN format
print(detector.validate_ssn("123-45-6789"))  # True
print(detector.validate_ssn("12-345-6789"))  # False
```

## Test Coverage

The local tests cover:

- ✅ Pattern detection for all sensitive data types
- ✅ Masking logic for detected data
- ✅ Luhn validation for credit cards
- ✅ File type filtering
- ✅ File size limits
- ✅ Message parsing
- ✅ Context extraction
- ✅ Multiple pattern detection

Not covered by local tests (requires AWS):
- ❌ S3 file downloads
- ❌ Database operations
- ❌ SQS message processing
- ❌ Auto-scaling behavior
- ❌ Network reliability

For full integration testing, see `docs/TESTING.md`.

