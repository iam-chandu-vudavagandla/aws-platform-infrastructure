resource "aws_codeconnections_connection" "github_actions_runner" {
  name          = "${var.project_name}-${var.environment}-github-runner"
  provider_type = "GitHub"

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-runner"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_security_group" "codebuild_github_runner" {
  name        = "${var.project_name}-${var.environment}-codebuild-github-runner-sg"
  description = "Security group for the CodeBuild-hosted GitHub Actions runner"
  vpc_id      = module.vpc.vpc_id

  tags = {
    Name        = "${var.project_name}-${var.environment}-codebuild-github-runner-sg"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_vpc_security_group_egress_rule" "codebuild_github_runner_all" {
  security_group_id = aws_security_group.codebuild_github_runner.id

  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "-1"

  description = "Allow the runner to reach GitHub, AWS APIs, ECR, and the VPC"
}

resource "aws_vpc_security_group_ingress_rule" "eks_api_from_codebuild_runner" {
  security_group_id = module.eks.cluster_security_group_id

  referenced_security_group_id = aws_security_group.codebuild_github_runner.id
  from_port                    = 443
  ip_protocol                  = "tcp"
  to_port                      = 443

  description = "Allow the CodeBuild GitHub runner to reach the private EKS API"
}

resource "aws_cloudwatch_log_group" "codebuild_github_runner" {
  name              = "/aws/codebuild/${var.project_name}-${var.environment}-github-runner"
  retention_in_days = 14

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-runner-logs"
    Project     = var.project_name
    Environment = var.environment
  }
}

data "aws_iam_policy_document" "codebuild_github_runner_assume_role" {
  statement {
    sid     = "AllowCodeBuild"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codebuild_github_runner" {
  name               = "${var.project_name}-${var.environment}-codebuild-github-runner-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_github_runner_assume_role.json

  tags = {
    Name        = "${var.project_name}-${var.environment}-codebuild-github-runner-role"
    Project     = var.project_name
    Environment = var.environment
  }
}

data "aws_iam_policy_document" "codebuild_github_runner" {
  statement {
    sid    = "WriteRunnerLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]

    resources = [
      "${aws_cloudwatch_log_group.codebuild_github_runner.arn}:*"
    ]
  }

  statement {
    sid    = "ManageBuildNetworkInterfaces"
    effect = "Allow"

    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:CreateNetworkInterfacePermission",
      "ec2:DeleteNetworkInterface",
      "ec2:DescribeDhcpOptions",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "UseGitHubConnection"
    effect = "Allow"

    actions = [
      "codeconnections:GetConnection",
      "codeconnections:GetConnectionToken"
    ]

    resources = [
      aws_codeconnections_connection.github_actions_runner.arn
    ]
  }
}

resource "aws_iam_policy" "codebuild_github_runner" {
  name        = "${var.project_name}-${var.environment}-codebuild-github-runner"
  description = "Allow the CodeBuild GitHub runner to use VPC networking, logs, and its GitHub connection"
  policy      = data.aws_iam_policy_document.codebuild_github_runner.json

  tags = {
    Name        = "${var.project_name}-${var.environment}-codebuild-github-runner"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "codebuild_github_runner" {
  role       = aws_iam_role.codebuild_github_runner.name
  policy_arn = aws_iam_policy.codebuild_github_runner.arn
}

resource "aws_codebuild_project" "github_actions_runner" {
  name          = "${var.project_name}-${var.environment}-github-runner"
  description   = "Ephemeral GitHub Actions runner with private access to the development EKS cluster"
  service_role  = aws_iam_role.codebuild_github_runner.arn
  build_timeout = 30

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true
  }

  source {
    type                = "GITHUB"
    location            = "https://github.com/${var.github_repository}.git"
    git_clone_depth     = 1
    report_build_status = false

    auth {
      type     = "CODECONNECTIONS"
      resource = aws_codeconnections_connection.github_actions_runner.arn
    }
  }

  vpc_config {
    vpc_id             = module.vpc.vpc_id
    subnets            = module.vpc.private_subnet_ids
    security_group_ids = [aws_security_group.codebuild_github_runner.id]
  }

  logs_config {
    cloudwatch_logs {
      status      = "ENABLED"
      group_name  = aws_cloudwatch_log_group.codebuild_github_runner.name
      stream_name = "runner"
    }

    s3_logs {
      status = "DISABLED"
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-runner"
    Project     = var.project_name
    Environment = var.environment
  }

  depends_on = [
    aws_iam_role_policy_attachment.codebuild_github_runner
  ]
}

resource "aws_codebuild_webhook" "github_actions_runner" {
  project_name = aws_codebuild_project.github_actions_runner.name
  build_type   = "BUILD"

  filter_group {
    filter {
      type    = "EVENT"
      pattern = "WORKFLOW_JOB_QUEUED"
    }
  }
}

