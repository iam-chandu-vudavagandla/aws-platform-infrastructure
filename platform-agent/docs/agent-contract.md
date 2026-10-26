# AWS Platform Reliability Agent Contract

## Purpose

Investigate Terraform structure and Kubernetes workload reliability in
the `aws-platform-infrastructure` project and produce evidence-based
incident reports without modifying infrastructure or application state.

## Operating principles

The agent must:

- Collect evidence before forming a diagnosis
- Use only explicitly allowlisted read-only tools
- Keep tool arguments bounded and validated
- Preserve a complete tool-call trace
- Separate observations from recommendations
- Require human approval for recommended changes
- Fall back to deterministic output when LLM output is unavailable,
  incomplete, or contradictory

## Supported environment

- Repository: `aws-platform-infrastructure`
- AWS profile: `aws-platform-new`
- AWS region: `ap-south-1`
- EKS cluster: `aws-platform-dev-eks`
- Kubernetes context: `aws-platform-dev-new`
- Default Kubernetes namespace: `dev`

The automated test suite does not require access to this environment.

## Supported workflows

### Terraform module inspection

The agent can:

- List Terraform files inside the approved repository
- Check for standard module files
- Reject paths outside the approved project
- Stop at a bounded tool-call limit
- Return structured success and failure reports

### Kubernetes Deployment investigation

The agent can collect and correlate:

- Deployment status and conditions
- Deployment selector and container resources
- Selected pod state, labels, restarts, and container history
- Incident-scoped namespace warning events
- Bounded recent pod logs
- Service configuration and EndpointSlices
- NetworkPolicies selecting affected pods
- HPA configuration, metrics, replicas, and conditions

## Reliability diagnoses

The deterministic investigation supports:

- Readiness probe failures
- Liveness probe failures
- Missing Kubernetes Secrets
- Failed scheduling
- `OOMKilled` containers
- Pod eviction
- Node `NotReady`
- Node memory, disk, and PID pressure
- DNS resolution failures
- Services with zero ready endpoints
- Service and Deployment selector mismatches
- Default-deny NetworkPolicy egress
- HPA `FailedGetResourceMetric`
- Missing container CPU requests
- HPA `ScalingLimited` and maximum replica limits

## Allowed tools

Only the following tools may execute:

- `list_terraform_files`
- `check_module_files`
- `get_deployment`
- `get_pods`
- `get_events`
- `get_pod_logs`
- `get_service_endpoints`
- `get_network_policies`
- `get_hpa`

All Kubernetes operations use predefined `kubectl` argument lists.
Commands are executed without a shell.

## Kubernetes evidence rules

A Deployment investigation must:

1. Read the Deployment before reading pods.
2. Extract the Deployment equality-based label selector.
3. Pass that validated selector to the pod tool.
4. Evaluate only pods selected by the Deployment.
5. Consider warning events only when they refer to the Deployment or
   one of its selected pods.
6. Collect logs only for an unhealthy, loggable pod associated with
   relevant warning evidence.
7. Bound log lines, time range, output size, event count, pod count,
   endpoint addresses, labels, and NetworkPolicy count.
8. Query Service and EndpointSlice evidence only after relevant
   connectivity evidence is found.
9. Query NetworkPolicies only when connectivity remains unexplained by
   missing Service endpoints.
10. Query HPA evidence only when an HPA name is explicitly supplied.
11. Return low confidence when required evidence cannot be collected.

## HPA evidence rules

An HPA investigation must correlate:

- HPA target reference
- Minimum and maximum replicas
- Current and desired replicas
- Current and target CPU utilization
- `ScalingActive` conditions
- `ScalingLimited` conditions
- Deployment container CPU requests

The agent must distinguish:

- Metrics unavailable while CPU requests exist
- CPU utilization unavailable because CPU requests are missing
- Healthy metrics with scaling constrained by `maxReplicas`

## Deterministic and LLM-assisted diagnosis

Tool selection and execution remain controlled by deterministic
application code.

An optional local LLM may improve the final explanation only after
evidence collection. The LLM cannot execute commands or bypass the tool
registry.

Before accepting LLM output, evidence guardrails verify preservation of
relevant facts, including:

- Probe failures
- Scheduling failures
- OOM termination
- Eviction
- Node readiness and pressure
- DNS resolution
- Service endpoints and selectors
- NetworkPolicy egress restrictions
- HPA metric failures
- Missing CPU requests
- HPA replica limits

If the LLM omits or contradicts required evidence, the deterministic
report must be returned.

## Forbidden actions

The agent must not:

- Run `terraform apply`
- Run `terraform destroy`
- Run `kubectl apply`
- Run `kubectl delete`
- Restart, scale, patch, or roll back workloads
- Create, update, or delete AWS resources
- Read Kubernetes Secret values
- Read AWS secret values
- Access files outside the approved repository
- Execute arbitrary shell commands
- Execute a tool that is not allowlisted
- Perform automatic remediation

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

Reports are validated through strict Pydantic contracts.

## Failure and stop conditions

The agent must stop or return a bounded failure report when:

- Sufficient evidence has been collected
- A required tool fails
- Input validation fails
- A Terraform tool-call limit is reached
- The requested operation is not allowlisted
- The requested operation violates a safety rule
- Required evidence is incomplete

## Human approval

Any recommendation that could modify infrastructure, application state,
permissions, networking, databases, scaling, or deployments requires
explicit human approval.

The agent never executes modifying operations, including after approval.
It diagnoses conditions and recommends a human-reviewed action.

## Out of scope

The current version does not:

- Modify or remediate infrastructure
- Manage Kubernetes Secrets
- Inspect unrestricted AWS account data
- Apply Terraform plans
- Change HPA limits
- Change NetworkPolicies
- Restart workloads
- Guarantee a diagnosis when required evidence is unavailable
