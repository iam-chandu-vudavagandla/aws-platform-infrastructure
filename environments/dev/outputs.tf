output "aws_region" {
  description = "AWS Region containing the development environment"
  value       = var.aws_region
}

output "vpc_id" {
  description = "ID of the dev VPC"
  value       = module.vpc.vpc_id
}

output "vpc_arn" {
  description = "ARN of the dev VPC"
  value       = module.vpc.vpc_arn
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = module.vpc.private_subnet_ids
}

output "internet_gateway_id" {
  description = "ID of the Internet Gateway"
  value       = module.vpc.internet_gateway_id
}

output "nat_gateway_id" {
  description = "ID of the NAT Gateway"
  value       = module.vpc.nat_gateway_id
}

output "public_route_table_id" {
  description = "ID of the public route table"
  value       = module.vpc.public_route_table_id
}

output "private_route_table_id" {
  description = "ID of the private route table"
  value       = module.vpc.private_route_table_id
}

output "alb_security_group_id" {
  description = "ALB security group ID"
  value       = module.security_groups.alb_security_group_id
}

output "eks_security_group_id" {
  description = "EKS security group ID"
  value       = module.security_groups.eks_security_group_id
}

output "rds_security_group_id" {
  description = "RDS security group ID"
  value       = module.security_groups.rds_security_group_id
}

output "eks_cluster_role_arn" {
  description = "ARN of the EKS cluster IAM role"
  value       = module.iam.eks_cluster_role_arn
}

output "eks_node_role_arn" {
  description = "ARN of the EKS node IAM role"
  value       = module.iam.eks_node_role_arn
}

output "eks_cluster_id" {
  description = "EKS cluster ID"
  value       = module.eks.cluster_id
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_arn" {
  description = "EKS cluster ARN"
  value       = module.eks.cluster_arn
}

output "eks_cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_version" {
  description = "EKS cluster Kubernetes version"
  value       = module.eks.cluster_version
}

output "eks_oidc_provider_arn" {
  description = "ARN of the EKS IAM OIDC provider"
  value       = module.eks.oidc_provider_arn
}

output "eks_oidc_provider_url" {
  description = "EKS OIDC issuer URL without HTTPS"
  value       = module.eks.oidc_provider_url
}

output "aws_load_balancer_controller_role_arn" {
  description = "IRSA role ARN for the AWS Load Balancer Controller"
  value       = aws_iam_role.aws_load_balancer_controller.arn
}

output "ecr_repository_name" {
  description = "Name of the application ECR repository"
  value       = module.ecr.repository_name
}

output "ecr_repository_url" {
  description = "URL of the application ECR repository"
  value       = module.ecr.repository_url
}

output "ecr_repository_arn" {
  description = "ARN of the application ECR repository"
  value       = module.ecr.repository_arn
}

output "ecr_registry_id" {
  description = "AWS account ID containing the ECR repository"
  value       = module.ecr.registry_id
}

output "rds_instance_id" {
  description = "RDS PostgreSQL instance ID"
  value       = module.rds.db_instance_id
}

output "rds_instance_arn" {
  description = "RDS PostgreSQL instance ARN"
  value       = module.rds.db_instance_arn
}

output "rds_database_name" {
  description = "Initial PostgreSQL database name"
  value       = module.rds.database_name
}

output "rds_endpoint" {
  description = "PostgreSQL endpoint including port"
  value       = module.rds.endpoint
}

output "rds_address" {
  description = "PostgreSQL DNS address"
  value       = module.rds.address
}

output "rds_port" {
  description = "PostgreSQL listener port"
  value       = module.rds.port
}

output "rds_master_user_secret_arn" {
  description = "ARN of the RDS-managed master-user secret"
  value       = module.rds.master_user_secret_arn
}

output "application_iam_role_arn" {
  description = "IRSA role ARN for the application ServiceAccount"
  value       = aws_iam_role.application.arn
}

output "application_secret_access_policy_arn" {
  description = "IAM policy allowing access to the RDS-managed secret"
  value       = aws_iam_policy.application_secret_access.arn
}

output "application_database_secret_arn" {
  description = "ARN of the dedicated application database secret"
  value       = aws_secretsmanager_secret.application_database.arn
}

output "application_database_secret_name" {
  description = "Name of the dedicated application database secret"
  value       = aws_secretsmanager_secret.application_database.name
}

output "github_actions_oidc_provider_arn" {
  description = "ARN of the GitHub Actions IAM OIDC provider"
  value       = aws_iam_openid_connect_provider.github_actions.arn
}

output "github_actions_deployer_role_arn" {
  description = "IAM role ARN assumed by the protected GitHub deployment environment"
  value       = aws_iam_role.github_actions_deployer.arn
}

output "github_actions_deployment_policy_arn" {
  description = "IAM policy ARN granting deployment access to ECR and EKS"
  value       = aws_iam_policy.github_actions_deployment.arn
}

output "codebuild_github_connection_arn" {
  description = "ARN of the GitHub App connection used by the CodeBuild runner"
  value       = aws_codeconnections_connection.github_actions_runner.arn
}

output "codebuild_github_runner_security_group_id" {
  description = "Security group ID used by the CodeBuild-hosted GitHub Actions runner"
  value       = aws_security_group.codebuild_github_runner.id
}

output "codebuild_github_runner_role_arn" {
  description = "IAM role ARN used by the CodeBuild-hosted GitHub Actions runner"
  value       = aws_iam_role.codebuild_github_runner.arn
}

output "codebuild_github_runner_log_group_name" {
  description = "CloudWatch log group for the CodeBuild-hosted GitHub Actions runner"
  value       = aws_cloudwatch_log_group.codebuild_github_runner.name
}

output "codebuild_github_runner_project_name" {
  description = "Name of the CodeBuild-hosted GitHub Actions runner project"
  value       = aws_codebuild_project.github_actions_runner.name
}

output "codebuild_github_runner_project_arn" {
  description = "ARN of the CodeBuild-hosted GitHub Actions runner project"
  value       = aws_codebuild_project.github_actions_runner.arn
}
