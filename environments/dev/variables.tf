variable "aws_region" {
  description = "AWS Region"
  type        = string
}

variable "skip_aws_credential_validation" {
  description = "Skip AWS credential and account validation for offline CI checks"
  type        = bool
  default     = false
}

variable "project_name" {
  description = "Project Name"
  type        = string
}

variable "environment" {
  description = "Environment Name"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
}

variable "availability_zones" {
  type = list(string)
}

variable "public_subnet_cidrs" {
  type = list(string)
}

variable "private_subnet_cidrs" {
  type = list(string)
}

variable "eks_cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "eks_cluster_version" {
  description = "Kubernetes version for EKS"
  type        = string
}

variable "eks_public_access_cidrs" {
  description = "CIDR blocks permitted to access the public EKS API endpoint"
  type        = list(string)

  validation {
    condition = (
      length(var.eks_public_access_cidrs) > 0 &&
      alltrue([
        for cidr in var.eks_public_access_cidrs :
        can(cidrhost(cidr, 0)) &&
        cidr != "0.0.0.0/0" &&
        cidr != "::/0"
      ])
    )

    error_message = "Provide at least one valid restricted CIDR; unrestricted 0.0.0.0/0 and ::/0 access is forbidden."
  }
}

variable "rds_database_name" {
  description = "Initial PostgreSQL database name"
  type        = string
}

variable "rds_master_username" {
  description = "PostgreSQL master username"
  type        = string
}

variable "rds_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
}

variable "rds_instance_class" {
  description = "RDS DB instance class"
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deployment role, in owner/repository format"
  type        = string

  validation {
    condition = can(
      regex(
        "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
        var.github_repository
      )
    )

    error_message = "github_repository must use the owner/repository format."
  }
}

variable "github_environment" {
  description = "Protected GitHub environment allowed to assume the deployment role"
  type        = string
  default     = "dev"

  validation {
    condition     = length(trimspace(var.github_environment)) > 0
    error_message = "github_environment must not be empty."
  }
}
