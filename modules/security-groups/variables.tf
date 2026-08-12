variable "project_name" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where security groups will be created"
  type        = string
}

variable "app_port" {
  description = "Application port exposed by the application"
  type        = number
  default     = 8080
}

variable "database_port" {
  description = "Database port"
  type        = number
  default     = 5432
}
