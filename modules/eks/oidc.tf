resource "aws_iam_openid_connect_provider" "this" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer

  client_id_list = [
    "sts.amazonaws.com"
  ]

  tags = {
    Name        = "${var.cluster_name}-oidc-provider"
    Project     = var.project_name
    Environment = var.environment
  }
}
