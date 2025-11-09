# S3 Scanner Web UI

A simple, modern web interface for the S3 Scanner demo application.

## Features

- **Start Scans**: Submit new scan jobs with bucket name and optional prefix
- **Real-time Job Status**: Auto-updating job status with progress bar and statistics
- **Findings Display**: Paginated table showing all detected findings
- **View Findings by Bucket**: Directly view findings for any bucket without starting a scan
- **Auto-refresh**: Job status updates every 3 seconds automatically
- **Context Modal**: Click "View Context" to see full context in a readable text box

## Deployment to AWS S3

The web UI can be hosted on AWS S3 as a static website.

### Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform installed
- Access to the AWS account where the infrastructure is deployed

### Steps

1. **Apply Terraform to create S3 bucket** (if not already done):
   ```bash
   cd ../terraform
   terraform apply
   ```

2. **Deploy the web UI**:
   ```bash
   cd ../webui
   ./deploy.sh
   ```

   The script will:
   - Get the S3 bucket name from Terraform output
   - Upload `index.html` to the bucket
   - Display the public website URL

3. **Access the website**:
   The deployment script will output the website URL, which will look like:
   ```
   http://strac-scanner-webui-<account-id>.s3-website-<region>.amazonaws.com
   ```

### Manual Deployment

If you prefer to deploy manually:

```bash
# Get bucket name
BUCKET_NAME=$(cd ../terraform && terraform output -raw webui_bucket_name)

# Upload file
aws s3 cp index.html s3://$BUCKET_NAME/index.html \
    --content-type "text/html" \
    --cache-control "no-cache"

# Get website URL
cd ../terraform
terraform output webui_website_url
```

### Updating the Website

To update the website after making changes:

```bash
./deploy.sh
```

The script will re-upload the HTML file to S3.

## Configuration

### API URL

The API Gateway URL is hard-coded in the JavaScript. To update it:

1. Open `index.html` in a text editor
2. Find the line: `const API_BASE_URL = '...';`
3. Replace with your API Gateway URL
4. Redeploy using `./deploy.sh`

### Getting the API Gateway URL

```bash
cd ../terraform
terraform output api_gateway_url
```

## Browser Compatibility

Works in all modern browsers:
- Chrome/Edge (recommended)
- Firefox
- Safari

## Local Storage

The web UI uses browser local storage to remember the current job ID and bucket. If you refresh the page, it will automatically resume showing the status of the last job you started.

## API Endpoints Used

- `POST /scan` - Create a new scan job
- `GET /jobs/{job_id}?real_time=true` - Get job status (real-time)
- `GET /results?bucket={bucket}&limit={limit}&offset={offset}` - Get findings with pagination

## Notes

- The website uses HTTP (not HTTPS) by default. For production, consider using CloudFront with an SSL certificate for HTTPS.
- CORS must be enabled on your API Gateway (already configured in the Terraform setup)
- The UI works best with the default API Gateway CORS configuration

## Troubleshooting

### Website not accessible

1. Check that the bucket policy allows public read access:
   ```bash
   aws s3api get-bucket-policy --bucket <bucket-name>
   ```

2. Verify static website hosting is enabled:
   ```bash
   aws s3api get-bucket-website --bucket <bucket-name>
   ```

3. Check public access block settings:
   ```bash
   aws s3api get-public-access-block --bucket <bucket-name>
   ```

### API calls failing

- Verify the API Gateway URL in `index.html` is correct
- Check browser console for CORS errors
- Ensure API Gateway CORS is properly configured
