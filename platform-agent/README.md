# AWS Platform Reliability Agent

A policy-controlled, read-only investigation agent for the
aws-platform-infrastructure project.

## Current workflows

### Inspect a Terraform module

```bash
platform-agent inspect-module modules/vpc
```

The agent lists the module files and checks for `main.tf`,
`variables.tf` and `outputs.tf`.

### Investigate a Kubernetes Deployment

```bash
export AWS_PROFILE=aws-platform-new
export AWS_REGION=ap-south-1

platform-agent investigate-kubernetes \
  aws-platform-app \
  --namespace dev \
  --event-limit 20
```

The workflow:

1. Reads the Deployment.
2. Extracts its label selector.
3. Reads only pods matching that selector.
4. Reads recent namespace events.
5. Ignores warning events unrelated to the Deployment and its pods.
6. Produces a structured JSON incident report.

## Safety controls

- Read-only tools only
- Explicit tool allowlist
- No arbitrary shell execution
- Fixed Kubernetes context and AWS profile
- Input validation for namespaces, names and selectors
- Bounded tool execution
- Complete tool-call trace
- No automatic remediation

## Development

```bash
cd platform-agent

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install --editable '.[dev]'

ruff check src tests
python -m pytest
```

## Current validation

The test suite covers:

- Strict Pydantic contracts
- Terraform path boundaries
- Tool allowlisting
- Kubernetes input validation
- Command failures and timeouts
- Deployment health summaries
- Pod readiness and restart evidence
- Event ordering and filtering
- Deployment-selector pod scoping
- Healthy and unhealthy incident reports
- CLI behavior

The live Kubernetes investigation has been validated against
`aws-platform-app` in the `dev` namespace on
`aws-platform-dev-eks`.
