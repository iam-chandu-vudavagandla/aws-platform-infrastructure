variable "aws_region" {
  description = "AWS Region"
  type        = string
}

variable "backend_bucket_name" {
  description = "Terraform state bucket name"
  type        = string
}

variable "dynamodb_table_name" {
  description = "Terraform lock table"
  type        = string
}
