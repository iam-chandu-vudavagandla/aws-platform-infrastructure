# AWS Platform Reliability Agent Contract

## Purpose

Investigate Terraform structure and Kubernetes workload health in the
aws-platform-infrastructure project and produce evidence-based reports
without modifying infrastructure or application state.

## Supported environment

- Repository: aws-platform-infrastructure
- AWS profile: aws-platform-new
- AWS region: ap-south-1
- EKS cluster: aws-platform-dev-eks
- Kubernetes context: aws-platform-dev-new
- Default Kubernetes namespace: dev

## Implemented capabilities

The current agent can:

- List Terraform files inside the approved repository
- Check Terraform modules for expected standard files
- Read one Kubernetes Deployment
- Discover the Deployment label selector
- Read only the pods selected by that Deployment
- Read recent Kubernetes namespace events
- Ignore warning events unrelated to the investigated Deployment or pods
- Correlate Deployment, pod and event evidence
- Produce a strict Pydantic incident report
- Preserve the complete tool-call trace
- Stop after a tool failure
- Reject tools that are not explicitly allowlisted

The current workflows are deterministic. They do not depend on an LLM
to select tools, classify workload health or generate the final report.

## Allowed tools

The allowlisted tools are:

- `list_terraform_files`
- `check_module_files`
- `get_deployment`
- `get_pods`
- `get_events`

All Kubernetes operations are read-only and use predefined `kubectl`
argument structures without shell execution.

## Forbidden actions

The agent must not:

- Run `terraform apply`
- Run `terraform destroy`
- Run `kubectl apply`
- Run `kubectl delete`
- Restart, scale or roll back workloads
- Create, update or delete AWS resources
- Read Kubernetes Secret values
- Read AWS secret values
- Access files outside the approved repository
- Execute arbitrary shell commands
- Execute a tool that is not allowlisted

## Required output

Every completed investigation must return:

- Summary
- Probable cause
- Evidence
- Confidence level
- Recommended action
- Whether human approval is required
- Complete tool-call trace
- Errors or missing evidence

## Kubernetes evidence rules

A Kubernetes Deployment investigation must:

1. Read the Deployment before reading its pods.
2. Extract the Deployment `matchLabels` selector.
3. Pass the validated selector to the pod-inspection tool.
4. Evaluate only pods returned by that selector.
5. Consider warning events only when they refer to the Deployment or
   one of its selected pods.
6. Return low confidence if required evidence cannot be collected.

## Stop conditions

The agent must stop when:

- It has sufficient evidence to produce a report
- The maximum tool-call limit is reached
- A required tool fails
- Input validation fails
- The requested operation is not allowlisted
- The requested operation violates a safety rule

## Human approval

Any proposed operation that could modify infrastructure, application
state, permissions, networking, databases or deployments requires
explicit human approval.

Version 1 never executes modifying operations, including after approval.
It can only diagnose conditions and recommend a human-reviewed action.

## Planned capabilities

The following capabilities are not implemented yet:

- Kubernetes log inspection
- Kubernetes resource-metric inspection
- AWS EKS, ECR, ALB and RDS metadata inspection
- Terraform formatting and validation tools
- Terraform plan summarization
- Evaluation fixtures for repeatable failure scenarios
- Optional LLM-assisted explanation constrained by collected evidence
