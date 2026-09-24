module "vpc" {
  source = "../../modules/vpc"

  project_name = var.project_name
  environment  = var.environment
  vpc_cidr     = var.vpc_cidr

  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
}

module "security_groups" {
  source = "../../modules/security-groups"

  project_name = var.project_name
  environment  = var.environment
  vpc_id       = module.vpc.vpc_id

  app_port      = 8080
  database_port = 5432
}

module "iam" {
  source = "../../modules/iam"

  project_name = var.project_name
  environment  = var.environment
}

module "eks" {
  source = "../../modules/eks"

  project_name    = var.project_name
  environment     = var.environment
  cluster_name    = var.eks_cluster_name
  cluster_version = var.eks_cluster_version

  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  cluster_role_arn = module.iam.eks_cluster_role_arn
  node_role_arn    = module.iam.eks_node_role_arn

  eks_security_group_id = module.security_groups.eks_security_group_id
  public_access_cidrs   = var.eks_public_access_cidrs

  node_instance_types = ["t3.small"]

  depends_on = [
    module.iam,
    module.security_groups
  ]
}

module "ecr" {
  source = "../../modules/ecr"

  repository_name      = "${var.project_name}-${var.environment}-app"
  image_tag_mutability = "IMMUTABLE"
  scan_on_push         = true
  max_image_count      = 10

  project_name = var.project_name
  environment  = var.environment
}

module "rds" {
  source = "../../modules/rds"

  project_name = var.project_name
  environment  = var.environment

  db_instance_identifier = "${var.project_name}-${var.environment}-postgres"
  database_name          = var.rds_database_name
  master_username        = var.rds_master_username
  engine_version         = var.rds_engine_version
  instance_class         = var.rds_instance_class

  database_port         = 5432
  allocated_storage     = 20
  max_allocated_storage = 100

  private_subnet_ids = module.vpc.private_subnet_ids
  vpc_security_group_ids = [
    module.security_groups.rds_security_group_id
  ]

  multi_az                 = false
  backup_retention_period  = var.rds_backup_retention_period
  deletion_protection      = false
  skip_final_snapshot      = true
  delete_automated_backups = true
  apply_immediately        = true

  depends_on = [
    aws_vpc_security_group_ingress_rule.rds_from_eks_nodes
  ]
}
