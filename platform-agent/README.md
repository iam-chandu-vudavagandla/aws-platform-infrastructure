# AWS Platform Reliability Agent

A policy-controlled, read-only investigation agent for the
`aws-platform-infrastructure` project.

The agent collects bounded Terraform and Kubernetes evidence, produces a
structured incident report, and optionally uses a local LLM to improve the
explanation without allowing the model to execute infrastructure changes.

## Workflows

### Inspect a Terraform module

```bash
platform-agent inspect-module modules/vpc
```

The agent:

1. Lists Terraform files inside the approved repository.
2. Checks for `main.tf`, `variables.tf`, and `outputs.tf`.
3. Rejects paths outside the approved project.
4. Returns structured JSON and a meaningful exit code.

### Investigate a Kubernetes Deployment

```bash
export AWS_PROFILE=aws-platform-new
export AWS_REGION=ap-south-1

platform-agent investigate-kubernetes \
  aws-platform-app \
  --namespace dev \
  --event-limit 20
```

The investigation collects read-only evidence from:

- Deployment status and container resources
- Pods selected by the Deployment
- Namespace events scoped to the incident
- Bounded recent pod logs
- Service and EndpointSlice state
- NetworkPolicies
- Node and scheduling conditions

### Run offline incident evaluations

```bash
platform-agent evaluate evals/fixtures
```


The command loads every JSON fixture, recreates a deterministic
incident report from its saved tool trace, and checks confidence,
approval requirements, required diagnosis terms, forbidden output,
evidence sources, expected errors and complete trace preservation.

Evaluations run locally without AWS, Kubernetes or Ollama.

Exit codes:

- `0`: every fixture passed
- `1`: one or more fixtures failed
- `2`: invalid command-line input

Current offline evaluation matrix:

| Scenario | Reliability boundary |
|---|---|
| OOMKilled container | Container memory and exit evidence |
| DNS resolution failure | Application dependency and resolver evidence |
| Default-deny egress | Pod-label and NetworkPolicy correlation |
| HPA metrics API failure | Autoscaling conditions and CPU-request evidence |

### Include HPA evidence

```bash
platform-agent investigate-kubernetes \
  aws-platform-app \
  --namespace dev \
  --event-limit 20 \
  --hpa-name aws-platform-app-hpa
```

The HPA investigation correlates:

- `ScalingActive` and `ScalingLimited` conditions
- Current and target CPU utilization
- Minimum, maximum, current, and desired replicas
- Deployment container CPU requests
- Metrics API failures
- Missing CPU requests
- `maxReplicas` capacity limits

## Diagnosis coverage

The Kubernetes investigation recognizes evidence for:

- Readiness and liveness probe failures
- Missing Secrets
- Failed scheduling
- `OOMKilled` containers
- Pod eviction
- Node `NotReady` conditions
- Node memory, disk, and PID pressure
- DNS resolution failures
- Services with zero ready endpoints
- Service and Deployment selector mismatches
- Default-deny NetworkPolicy egress
- HPA resource-metric failures
- Missing CPU requests
- HPA maximum replica limits

## Structured output

Every investigation returns JSON containing:

- Summary
- Probable cause
- Evidence
- Confidence
- Recommended action
- Human-approval requirement
- Complete tool-call trace
- Errors or missing evidence

## Deterministic and LLM-assisted diagnosis

Deterministic evidence analysis remains the safety baseline.

Optional local LLM enrichment can improve the wording of a diagnosis, but
the application validates it against collected evidence. If the LLM omits
or contradicts important facts, the deterministic report is returned.

The LLM cannot execute tools directly. All tool execution passes through
the explicit Python allowlist.

## Safety controls

- Read-only tools only
- Explicit tool allowlist
- No arbitrary shell execution
- Fixed Kubernetes context and AWS profile
- Validation of paths, namespaces, names, selectors, and bounds
- Bounded pod logs, events, policies, and endpoint evidence
- Incident-scoped evidence filtering
- Complete tool-call trace
- Deterministic fallback when LLM output is unsafe
- No automatic remediation
- Human approval required for recommended changes

## Continuous integration

The GitHub Actions `Python validation` job installs the application and
reliability-agent dependencies, then runs:

1. Application tests
2. All reliability-agent tests
3. `python -m pip check`
4. All committed offline incident evaluations

The evaluation gate runs without AWS credentials, Kubernetes access or
Ollama. A failed test, broken dependency or failed evaluation blocks the
workflow.

## Development

```bash
cd platform-agent

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install --editable '.[dev]'

python -m compileall -q src tests
pytest -q
python -m pip check
```

## Current validation

The project currently has 125 automated tests covering:

- Strict Pydantic contracts
- Terraform path boundaries
- Tool allowlisting
- Kubernetes input validation
- Command failures and timeouts
- Deployment, pod, event, and log evidence
- Incident-scoped filtering
- Service and EndpointSlice correlation
- NetworkPolicy selector correlation
- Node reliability conditions
- HPA and resource-metric failures
- Deterministic reports
- LLM evidence-preservation guardrails
- CLI behavior

The automated suite uses local fixtures and mocked Kubernetes responses,
so it does not require active AWS resources.
