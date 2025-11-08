terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Optional: Backend configuration for state management
  # backend "s3" {
  #   bucket = "your-terraform-state-bucket"
  #   key    = "s3-scanner/terraform.tfstate"
  #   region = "us-west-2"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "s3-sensitive-data-scanner"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

