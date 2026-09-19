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
