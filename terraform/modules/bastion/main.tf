# Security Group for Bastion
resource "aws_security_group" "bastion" {
  name        = "${var.project_name}-bastion-sg"
  description = "Security group for bastion host"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
    description = "SSH from allowed CIDR blocks"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name = "${var.project_name}-bastion-sg"
  }
}

# IAM Role for Bastion
resource "aws_iam_role" "bastion" {
  name = "${var.project_name}-bastion-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-bastion-role"
  }
}

# IAM Instance Profile for Bastion
resource "aws_iam_instance_profile" "bastion" {
  name = "${var.project_name}-bastion-profile"
  role = aws_iam_role.bastion.name

  tags = {
    Name = "${var.project_name}-bastion-profile"
  }
}

# EC2 Key Pair
# Create a key pair first: aws ec2 create-key-pair --key-name strac-scanner-bastion-key --query 'KeyMaterial' --output text > bastion-key.pem
# Or use an existing key pair name
# Use data source if key pair exists, otherwise create a placeholder
# Note: You must create the key pair manually before deploying
data "aws_key_pair" "existing" {
  key_name = var.key_pair_name
}

# EC2 Instance for Bastion
resource "aws_instance" "bastion" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = "t3.micro"
  subnet_id              = var.public_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.bastion.id]
  key_name               = data.aws_key_pair.existing.key_name
  iam_instance_profile   = aws_iam_instance_profile.bastion.name

  user_data = <<-EOF
    #!/bin/bash
    yum update -y
    yum install -y postgresql15
  EOF

  tags = {
    Name = "${var.project_name}-bastion"
  }
}

# Elastic IP for Bastion
resource "aws_eip" "bastion" {
  instance = aws_instance.bastion.id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-bastion-eip"
  }
}

# Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Outputs
output "public_ip" {
  value       = aws_eip.bastion.public_ip
  description = "Bastion host public IP"
}

output "instance_id" {
  value       = aws_instance.bastion.id
  description = "Bastion instance ID"
}

