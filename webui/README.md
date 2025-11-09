# S3 Scanner Web UI

A simple, modern web interface for the S3 Scanner demo application.

## Features

- **Start Scans**: Submit new scan jobs with bucket name and optional prefix
- **Real-time Job Status**: Auto-updating job status with progress bar and statistics
- **Findings Display**: Paginated table showing all detected findings
- **Auto-refresh**: Job status updates every 3 seconds automatically

## Usage

### Quick Start

1. Open `index.html` in a web browser (Chrome, Firefox, Safari, or Edge)
2. Update the API URL in the JavaScript code (line ~200) if needed:
   ```javascript
   const API_BASE_URL = 'https://your-api-gateway-url.execute-api.region.amazonaws.com';
   ```
3. Enter a bucket name and optional prefix
4. Click "Start Scan"
5. Watch the job status update automatically
6. View findings as they are discovered

### Configuration

The API URL is hard-coded at the top of the JavaScript section. To change it:

1. Open `index.html` in a text editor
2. Find the line: `const API_BASE_URL = '...';`
3. Replace with your API Gateway URL
4. Save and refresh the browser

### Features Explained

#### Scan Form
- **Bucket**: Required S3 bucket name
- **Prefix**: Optional path prefix to limit scan scope (e.g., `path/to/files/`)

#### Job Status
- Shows current job progress with a progress bar
- Displays statistics:
  - Total objects
  - Succeeded/Failed/Processing/Queued counts
  - Total findings discovered
- Auto-updates every 3 seconds
- Stops auto-updating when job completes or fails

#### Findings Table
- Shows all detected sensitive data
- Columns:
  - **Detector**: Type of pattern detected (e.g., API_KEY, PASSWORD)
  - **Bucket**: S3 bucket name
  - **Key**: S3 object key (file path)
  - **Match**: The detected sensitive data (masked)
  - **Context**: Surrounding text context
  - **Found At**: Timestamp when finding was created
- Pagination: Navigate through findings with Previous/Next buttons
- Auto-refreshes when job is processing or completed

## Browser Compatibility

Works in all modern browsers:
- Chrome/Edge (recommended)
- Firefox
- Safari

## Local Storage

The web UI uses browser local storage to remember the current job ID. If you refresh the page, it will automatically resume showing the status of the last job you started.

## API Endpoints Used

- `POST /scan` - Create a new scan job
- `GET /jobs/{job_id}` - Get job status
- `GET /results?job_id={job_id}&limit={limit}&offset={offset}` - Get findings with pagination

## Notes

- This is a pure front-end demo - no backend server required
- All API calls are made directly from the browser
- CORS must be enabled on your API Gateway (already configured in the Terraform setup)
- The UI works best with the default API Gateway CORS configuration

