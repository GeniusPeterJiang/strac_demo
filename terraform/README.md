# Terraform Infrastructure

This directory contains Terraform configuration for deploying the S3 Sensitive Data Scanner infrastructure on AWS.

## Structure

- `main.tf` - Main infrastructure configuration
- `provider.tf` - AWS provider configuration
- `variables.tf` - Input variables
- `outputs.tf` - Output values
- `database_schema.sql` - PostgreSQL database schema
- `modules/` - Reusable Terraform modules
  - `vpc/` - VPC, subnets, NAT gateways, VPC endpoints
  - `rds/` - RDS PostgreSQL with RDS Proxy
  - `sqs/` - SQS queues and dead-letter queue
  - `ecs/` - ECS Fargate cluster and service
  - `api/` - API Gateway and Lambda function
  - `bastion/` - EC2 bastion host for database access

## Quick Start

1. **Create `terraform.tfvars`:**

```hcl
aws_region      = "us-west-2"
aws_account_id  = "697547269674"
environment     = "dev"
project_name    = "strac-scanner"

rds_master_username = "scanner_admin"
rds_master_password = "YourSecurePassword123!"

# Optional: Adjust these for your needs
ecs_min_capacity = 1
ecs_max_capacity = 50
scanner_batch_size = 10
```

2. **Initialize Terraform:**

```bash
terraform init
```

3. **Plan deployment:**

```bash
terraform plan
```

4. **Apply configuration:**

```bash
terraform apply
```

5. **Initialize database:**

After deployment, connect to RDS and run the schema:

```bash
RDS_ENDPOINT=$(terraform output -raw rds_proxy_endpoint)
psql -h $RDS_ENDPOINT -U scanner_admin -d scanner_db -f database_schema.sql
```

## Variables

See `variables.tf` for all available variables. Key variables:

- `aws_region` - AWS region (default: us-west-2)
- `aws_account_id` - AWS account ID
- `rds_master_password` - RDS master password (required)
- `ecs_min_capacity` - Minimum ECS tasks (default: 1)
- `ecs_max_capacity` - Maximum ECS tasks (default: 50)
- `scanner_batch_size` - Files per batch (default: 10)

## Outputs

After deployment, get important values:

```bash
# API Gateway URL
terraform output api_gateway_url

# SQS Queue URL
terraform output sqs_queue_url

# RDS Proxy Endpoint
terraform output rds_proxy_endpoint

# ECR Repository URLs
terraform output ecr_repository_url
```

## Multi-Region Support

To deploy to additional regions:

1. Update `aws_region` in `terraform.tfvars`
2. Update `availability_zones` to match the region
3. Run `terraform apply`

## Cost Considerations

- **NAT Gateways**: ~$32/month each (2 in this setup = ~$64/month)
- **RDS**: Depends on instance class (db.t3.medium ~$60/month)
- **ECS Fargate**: Pay per task hour (~$0.04/vCPU-hour, ~$0.004/GB-hour)
- **SQS**: First 1M requests/month free, then $0.40 per million
- **VPC Endpoints**: S3 endpoint is free, SQS endpoint ~$7/month + data processing

**Estimated monthly cost for small deployment**: ~$150-200/month

## Destroying Infrastructure

To tear down all resources:

```bash
terraform destroy
```

**Warning**: This will delete all data including RDS database. Make sure to backup data first if needed.

## Troubleshooting

### Terraform Apply Fails

- Check AWS credentials: `aws sts get-caller-identity`
- Verify account ID matches `variables.tf`
- Check IAM permissions for Terraform user
- Review error messages for specific resource issues

### RDS Connection Issues

- Verify security groups allow access from ECS tasks
- Check RDS Proxy is running
- Verify credentials in Secrets Manager
- Test connection from bastion host

### ECS Tasks Not Starting

- Check ECR images are pushed
- Verify IAM roles have correct permissions
- Review CloudWatch Logs for errors
- Check ECS service events: `aws ecs describe-services --cluster <cluster> --services <service>`

## Module Details

### VPC Module

Creates:
- VPC with DNS support
- 2 public subnets (one per AZ)
- 2 private subnets (one per AZ)
- Internet Gateway
- NAT Gateways (one per AZ)
- VPC Endpoints for S3 (Gateway) and SQS (Interface)

### RDS Module

Creates:
- PostgreSQL 15.4 database
- RDS Proxy for connection pooling
- Security groups
- Secrets Manager secret for credentials
- Auto-scaling storage (20GB initial, up to 200GB)

### SQS Module

Creates:
- Main scan jobs queue
- Dead-letter queue
- CloudWatch alarms for queue depth and message age

### ECS Module

Creates:
- ECS Fargate cluster
- Task definition for scanner worker
- ECS service with auto-scaling
- Auto-scaling policies based on CPU and SQS queue depth

### API Module

Creates:
- API Gateway HTTP API
- Lambda function (container image)
- CloudWatch log groups
- IAM roles and policies

### Bastion Module

Creates:
- EC2 t3.micro instance in public subnet
- Elastic IP
- Security group allowing SSH from specified CIDR blocks
- IAM role for EC2 instance

## Security Notes

- RDS password is stored in Secrets Manager (encrypted)
- All resources use least-privilege IAM roles
- VPC endpoints reduce data transfer costs and improve security
- Security groups restrict access to necessary ports only
- Consider enabling deletion protection for production RDS instances

