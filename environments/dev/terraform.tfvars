aws_region   = "ap-south-1"
project_name = "aws-platform"
environment  = "dev"
vpc_cidr     = "10.0.0.0/16"
availability_zones = [
  "ap-south-1a",
  "ap-south-1b"
]

public_subnet_cidrs = [
  "10.0.1.0/24",
  "10.0.2.0/24"
]

private_subnet_cidrs = [
  "10.0.11.0/24",
  "10.0.12.0/24"
]

eks_cluster_name    = "aws-platform-dev-eks"
eks_cluster_version = "1.35"


rds_database_name   = "appdb"
rds_master_username = "appadmin"
rds_engine_version  = "18.3"
rds_instance_class  = "db.t3.micro"
