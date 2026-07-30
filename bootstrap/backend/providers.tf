provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "aws-platform"
      Environment = "bootstrap"
      ManagedBy   = "Terraform"
      Owner       = "Chandu"
    }
  }
}
