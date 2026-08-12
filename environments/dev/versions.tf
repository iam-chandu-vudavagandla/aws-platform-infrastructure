terraform {
  required_version = ">= 1.8.0"

  backend "s3" {
    bucket       = "chandu-platform-tf-backend-267753040218"
    key          = "dev/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
    encrypt      = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
