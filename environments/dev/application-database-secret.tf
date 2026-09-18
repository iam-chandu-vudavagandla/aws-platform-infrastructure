resource "aws_secretsmanager_secret" "application_database" {
  name = "${var.project_name}-${var.environment}-application-database"

  description = "Database credentials for the EKS application"

  recovery_window_in_days = 7

  tags = {
    Name        = "${var.project_name}-${var.environment}-application-database"
    Project     = var.project_name
    Environment = var.environment
  }
}
