# AWS Platform Reliability Agent Contract

## Purpose

Investigate failures in the aws-platform-infrastructure project and
produce an evidence-based diagnosis without changing infrastructure.

## Supported environment

- Repository: aws-platform-infrastructure
- AWS profile: new-free-account
- AWS region: ap-south-1
- EKS cluster: aws-platform-dev-eks
- Kubernetes namespace: dev

## Version 1 capabilities

The agent may:

- Inspect Terraform files
- Run Terraform formatting and validation checks
- Summarize Terraform plans
- Read Kubernetes resource status
- Read Kubernetes events
- Read application and controller logs
- Read Kubernetes metrics
- Inspect EKS, ECR, ALB and RDS metadata
- Produce an incident report

## Forbidden actions

The agent must not:

- Run terraform apply
- Run terraform destroy
- Run kubectl apply
- Run kubectl delete
- Restart or scale workloads
- Roll back deployments
- Create, update or delete AWS resources
- Read secret values
- Access files outside the approved repository
- Execute arbitrary shell commands

## Required output

Every investigation must return:

- Summary
- Probable cause
- Evidence
- Confidence level
- Recommended action
- Whether human approval is required
- Complete tool-call trace
- Errors or missing evidence

## Stop conditions

The agent must stop when:

- It has sufficient evidence to produce a diagnosis
- The maximum tool-call limit is reached
- A required tool repeatedly fails
- The requested operation violates a safety rule
- Human approval is required

## Human approval

Any operation that could modify infrastructure, application state,
permissions, networking, databases or deployments requires explicit
human approval.

Version 1 does not execute modifying operations even after approval.
It may only recommend a change or generate a proposed patch.
