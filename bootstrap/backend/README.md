# Terraform Backend Bootstrap

## Purpose

This Terraform configuration bootstraps the remote backend required for the AWS Platform project.

## Resources Created

- Amazon S3 bucket for Terraform remote state
- Amazon DynamoDB table for Terraform state locking

## Security

- Versioning enabled
- Server-side encryption enabled
- Public access blocked
- Tagged for governance

## Deployment

```bash
terraform init
terraform plan
terraform apply
```
