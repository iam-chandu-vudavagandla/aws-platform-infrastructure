resource "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-actions-oidc"
    Project     = var.project_name
    Environment = var.environment
  }
}

data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    sid     = "AllowProtectedGitHubEnvironment"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type = "Federated"
      identifiers = [
        aws_iam_openid_connect_provider.github_actions.arn
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:environment:${var.github_environment}"
      ]
    }
  }
}

resource "aws_iam_role" "github_actions_deployer" {
  name = "${var.project_name}-${var.environment}-github-deployer-role"

  assume_role_policy   = data.aws_iam_policy_document.github_actions_assume_role.json
  max_session_duration = 3600

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-deployer-role"
    Project     = var.project_name
    Environment = var.environment
  }
}

data "aws_iam_policy_document" "github_actions_deployment" {
  statement {
    sid       = "GetECRAuthorizationToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PushApplicationImage"
    effect = "Allow"

    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart"
    ]

    resources = [
      module.ecr.repository_arn
    ]
  }

  statement {
    sid       = "DescribeTargetCluster"
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = [module.eks.cluster_arn]
  }
}

resource "aws_iam_policy" "github_actions_deployment" {
  name = "${var.project_name}-${var.environment}-github-deployment"

  description = "Allow GitHub Actions to push application images and discover the target EKS cluster"
  policy      = data.aws_iam_policy_document.github_actions_deployment.json

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-deployment"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "github_actions_deployment" {
  role       = aws_iam_role.github_actions_deployer.name
  policy_arn = aws_iam_policy.github_actions_deployment.arn
}

resource "aws_eks_access_entry" "github_actions_deployer" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.github_actions_deployer.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "github_actions_deployer" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.github_actions_deployer.arn

  policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"

  access_scope {
    type       = "namespace"
    namespaces = [var.environment]
  }

  depends_on = [
    aws_eks_access_entry.github_actions_deployer
  ]
}
