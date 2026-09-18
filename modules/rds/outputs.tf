output "db_instance_id" {
  description = "RDS DB instance ID"
  value       = aws_db_instance.this.id
}

output "db_instance_arn" {
  description = "RDS DB instance ARN"
  value       = aws_db_instance.this.arn
}

output "db_instance_identifier" {
  description = "RDS DB instance identifier"
  value       = aws_db_instance.this.identifier
}

output "database_name" {
  description = "Initial PostgreSQL database name"
  value       = aws_db_instance.this.db_name
}

output "endpoint" {
  description = "PostgreSQL endpoint including port"
  value       = aws_db_instance.this.endpoint
}

output "address" {
  description = "PostgreSQL DNS address"
  value       = aws_db_instance.this.address
}

output "port" {
  description = "PostgreSQL listener port"
  value       = aws_db_instance.this.port
}

output "db_subnet_group_name" {
  description = "RDS DB subnet group name"
  value       = aws_db_subnet_group.this.name
}

output "master_user_secret_arn" {
  description = "ARN of the RDS-managed master-user secret"
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}
