data "aws_iam_policy_document" "aws_load_balancer_controller_assume_role" {
  statement {
    sid     = "AllowAWSLoadBalancerController"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type = "Federated"
      identifiers = [
        module.eks.oidc_provider_arn
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:sub"
      values = [
        "system:serviceaccount:kube-system:aws-load-balancer-controller"
      ]
    }
  }
}

resource "aws_iam_policy" "aws_load_balancer_controller" {
  name = "${var.project_name}-${var.environment}-AWSLoadBalancerControllerIAMPolicy"

  description = "Permissions for the AWS Load Balancer Controller"

  policy = file(
    "${path.module}/../../policies/aws-load-balancer-controller-v2.14.1.json"
  )

  tags = {
    Name        = "${var.project_name}-${var.environment}-AWSLoadBalancerControllerIAMPolicy"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role" "aws_load_balancer_controller" {
  name = "${var.project_name}-${var.environment}-aws-load-balancer-controller-role"

  assume_role_policy = data.aws_iam_policy_document.aws_load_balancer_controller_assume_role.json

  tags = {
    Name        = "${var.project_name}-${var.environment}-aws-load-balancer-controller-role"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "aws_load_balancer_controller" {
  role       = aws_iam_role.aws_load_balancer_controller.name
  policy_arn = aws_iam_policy.aws_load_balancer_controller.arn
}
