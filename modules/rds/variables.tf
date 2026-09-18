variable "project_name" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "db_instance_identifier" {
  description = "Unique RDS DB instance identifier"
  type        = string
}

variable "database_name" {
  description = "Initial PostgreSQL database name"
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9_]*$", var.database_name))
    error_message = "database_name must begin with a letter and contain only letters, numbers, or underscores."
  }
}

variable "master_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "appadmin"
}

variable "engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "18.3"
}

variable "instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "database_port" {
  description = "PostgreSQL listener port"
  type        = number
  default     = 5432
}

variable "allocated_storage" {
  description = "Initial database storage in GiB"
  type        = number
  default     = 20

  validation {
    condition     = var.allocated_storage >= 20
    error_message = "allocated_storage must be at least 20 GiB for this gp3 configuration."
  }
}

variable "max_allocated_storage" {
  description = "Maximum storage autoscaling limit in GiB"
  type        = number
  default     = 100

  validation {
    condition     = var.max_allocated_storage >= 20
    error_message = "max_allocated_storage must be at least 20 GiB."
  }
}

variable "private_subnet_ids" {
  description = "Private subnet IDs used by the DB subnet group"
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "At least two private subnets are required."
  }
}

variable "vpc_security_group_ids" {
  description = "Security group IDs assigned to RDS"
  type        = list(string)
}

variable "multi_az" {
  description = "Whether to deploy a synchronous Multi-AZ standby"
  type        = bool
  default     = false
}

variable "backup_retention_period" {
  description = "Automated backup retention in days"
  type        = number
  default     = 7

  validation {
    condition = (
      var.backup_retention_period >= 0 &&
      var.backup_retention_period <= 35
    )
    error_message = "backup_retention_period must be between 0 and 35."
  }
}

variable "deletion_protection" {
  description = "Protect the DB instance from accidental deletion"
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Whether to skip the final snapshot during deletion"
  type        = bool
  default     = true
}

variable "delete_automated_backups" {
  description = "Delete automated backups when the DB instance is removed"
  type        = bool
  default     = true
}

variable "apply_immediately" {
  description = "Apply database modifications immediately"
  type        = bool
  default     = true
}
