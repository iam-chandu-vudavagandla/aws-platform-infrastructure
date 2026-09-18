data "aws_iam_policy_document" "application_assume_role" {
  statement {
    sid     = "AllowApplicationServiceAccount"
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
        "system:serviceaccount:dev:aws-platform-app"
      ]
    }
  }
}

data "aws_iam_policy_document" "application_secret_access" {
  statement {
    sid    = "ReadDatabaseSecretsDuringMigration"
    effect = "Allow"

    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue"
    ]

    resources = [
      module.rds.master_user_secret_arn,
      aws_secretsmanager_secret.application_database.arn
    ]
  }
}

resource "aws_iam_policy" "application_secret_access" {
  name = "${var.project_name}-${var.environment}-application-secret-access"

  description = "Allow the EKS application to read its RDS-managed database secret"
  policy      = data.aws_iam_policy_document.application_secret_access.json

  tags = {
    Name        = "${var.project_name}-${var.environment}-application-secret-access"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role" "application" {
  name = "${var.project_name}-${var.environment}-application-role"

  assume_role_policy = data.aws_iam_policy_document.application_assume_role.json

  tags = {
    Name        = "${var.project_name}-${var.environment}-application-role"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "application_secret_access" {
  role       = aws_iam_role.application.name
  policy_arn = aws_iam_policy.application_secret_access.arn
}
