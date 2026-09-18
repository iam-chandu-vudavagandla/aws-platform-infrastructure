resource "aws_vpc_security_group_ingress_rule" "rds_from_eks_nodes" {
  security_group_id = module.security_groups.rds_security_group_id

  referenced_security_group_id = module.eks.cluster_security_group_id

  from_port   = 5432
  to_port     = 5432
  ip_protocol = "tcp"

  description = "Allow PostgreSQL traffic from EKS worker nodes"
}
