# Development Deployment Runbook

## Purpose

This runbook describes how to provision and deploy the AWS Platform development environment safely.

The deployment uses:

- Terraform for AWS infrastructure
- GitHub Actions OIDC for short-lived AWS credentials
- Amazon ECR for application images
- Amazon EKS for Kubernetes workloads
- AWS Secrets Manager for database credentials
- A protected GitHub environment named `dev`

Do not store AWS access keys in GitHub.

## Prerequisites

Required local tools:

- AWS CLI
- Terraform
- kubectl
- Git
- curl

Required access:

- An AWS profile authorized to provision the project
- Administrator access to the GitHub repository
- Permission to configure GitHub environments and variables

## 1. Configure the AWS session

```bash
export AWS_PROFILE=YOUR_AWS_PROFILE
export AWS_REGION=ap-south-1

aws sts get-caller-identity
aws configure get region --profile "${AWS_PROFILE}"

```

> **Execution warning:** This document is a future live-deployment procedure. Do not execute provisioning, deployment, rollback, or destruction commands until an approved live deployment window.

## 2. Configure Local Terraform Inputs

Copy the example file only when preparing for a live deployment:

```bash
cp environments/dev/deployment.auto.tfvars.example \
  environments/dev/deployment.auto.tfvars
```

Find the current public IPv4 address:

```bash
curl -fsS https://checkip.amazonaws.com
```

Edit `environments/dev/deployment.auto.tfvars` and replace the example CIDR with the current public address followed by `/32`.

The file must also identify the trusted repository and protected environment:

```hcl
eks_public_access_cidrs = [
  "YOUR_CURRENT_PUBLIC_IP/32"
]

github_repository = "iam-chandu-vudavagandla/aws-platform-infrastructure"
github_environment = "dev"
```

The real `deployment.auto.tfvars` file is ignored by Git. Never permit `0.0.0.0/0` or `::/0`.

## 3. Bootstrap the Terraform Backend

Before initialization, replace the placeholder bucket name in `bootstrap/backend/terraform.tfvars` with a globally unique S3 bucket name.

During the approved live deployment window:

```bash
terraform -chdir=bootstrap/backend init -reconfigure
terraform -chdir=bootstrap/backend plan -out=tfplan
terraform -chdir=bootstrap/backend apply tfplan
```

Display the created backend information:

```bash
terraform -chdir=bootstrap/backend output
```

## 4. Initialize the Development Backend

Replace `YOUR_BACKEND_BUCKET` before executing:

```bash
terraform -chdir=environments/dev init \
  -reconfigure \
  -backend-config="bucket=YOUR_BACKEND_BUCKET" \
  -backend-config="key=dev/terraform.tfstate" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"
```

Never execute backend initialization with a literal placeholder bucket name.

## 5. Review and Apply Infrastructure

Format and validate:

```bash
terraform fmt -check -recursive .
terraform -chdir=environments/dev validate
```

Create a saved plan:

```bash
terraform -chdir=environments/dev plan -out=tfplan
```

Review the plan carefully, particularly the NAT Gateway, EKS, RDS, IAM, OIDC, security groups, and public endpoint CIDRs.

Apply only the reviewed saved plan:

```bash
terraform -chdir=environments/dev apply tfplan
```

AWS resources can generate charges. Confirm the budget and approved deployment window before applying.


## 6. Configure kubectl

After Terraform successfully creates EKS, configure an administrator context:

```bash
aws eks update-kubeconfig \
  --name "$(terraform -chdir=environments/dev output -raw eks_cluster_name)" \
  --region "$(terraform -chdir=environments/dev output -raw aws_region)" \
  --alias aws-platform-dev-admin
```

Verify the selected context and worker nodes:

```bash
kubectl config current-context
kubectl get nodes
```

Do not continue unless the context points to the intended AWS account and development cluster.

## 7. Bootstrap the Development Namespace

The GitHub deployment role has namespace-scoped EKS permissions and cannot create the Namespace resource.

Create the namespace once with the Terraform administrator identity:

```bash
kubectl apply \
  --filename kubernetes/overlays/dev/namespace.yaml

kubectl get namespace dev
```

## 8. Configure the GitHub Environment

In the GitHub repository, open:

```text
Settings → Environments → New environment → dev
```

Configure protection rules and required reviewers when the repository plan supports them.

Add these environment variables:


| GitHub variable | Terraform output |
|---|---|
| `AWS_REGION` | `aws_region` |
| `AWS_DEPLOY_ROLE_ARN` | `github_actions_deployer_role_arn` |
| `EKS_CLUSTER_NAME` | `eks_cluster_name` |
| `ECR_REPOSITORY` | `ecr_repository_name` |
| `APPLICATION_ROLE_ARN` | `application_iam_role_arn` |
| `DB_SECRET_ARN` | `application_database_secret_arn` |
| `DB_HOST` | `rds_address` |

Retrieve an individual value with:

```bash
terraform -chdir=environments/dev output -raw OUTPUT_NAME
```

Replace `OUTPUT_NAME` with the Terraform output listed in the table. Do not enter `OUTPUT_NAME` literally.

These values are infrastructure identifiers. Do not add long-lived AWS access keys or secret access keys to GitHub.

## 9. Execute the Deployment Workflow

Before running the workflow, confirm that:

- Terraform apply completed successfully.
- EKS worker nodes are Ready.
- The `dev` namespace exists.
- All seven GitHub environment variables are configured.
- The workflow is being executed from `main`.

In GitHub, open:

```text
Actions → Deploy development → Run workflow
```

Select `main` and set `confirm_deployment` to `true`.

The workflow will:

1. Authenticate to AWS using GitHub OIDC.
2. Build the application container.
3. Push an immutable image to ECR.
4. Render environment-specific Kubernetes manifests.
5. Remove the Namespace manifest from the deployment payload.
6. Apply namespace-scoped resources.
7. Wait for the Deployment rollout.
8. Verify the deployed image digest.

## 10. Verify the Deployment

Inspect the deployed resources:

```bash
kubectl get deployment,pods,service,hpa,pdb,ingress \
  --namespace dev

kubectl rollout status \
  deployment/aws-platform-app \
  --namespace dev \
  --timeout=300s
```

Display the deployed immutable image:

```bash
kubectl get deployment aws-platform-app \
  --namespace dev \
  --output jsonpath='{.spec.template.spec.containers[?(@.name=="aws-platform-app")].image}'

echo
```

Retrieve the ALB hostname:

```bash
kubectl get ingress nginx-ingress \
  --namespace dev \
  --output jsonpath='{.status.loadBalancer.ingress[0].hostname}'

echo
```

After the ALB becomes active, replace the placeholder and test:

```bash
curl -fsS "http://YOUR_ALB_HOSTNAME/health"
curl -fsS "http://YOUR_ALB_HOSTNAME/ready"
```

## 11. Roll Back an Application Deployment

Inspect the revision history:

```bash
kubectl rollout history \
  deployment/aws-platform-app \
  --namespace dev
```

Roll back only after confirming it is required:

```bash
kubectl rollout undo \
  deployment/aws-platform-app \
  --namespace dev

kubectl rollout status \
  deployment/aws-platform-app \
  --namespace dev \
  --timeout=300s
```

Document the rollback reason and resulting image digest. A later GitHub deployment may reapply the workflow-selected image.

## 12. Destroy the Development Environment

> **Destructive procedure:** Execute this section only during an approved teardown window after confirming that no required data must be retained.

Delete the Ingress while EKS and the AWS Load Balancer Controller are running:

```bash
kubectl delete ingress nginx-ingress \
  --namespace dev
```

Wait for the AWS Application Load Balancer to be deleted. Then create and review a destroy plan:

```bash
terraform -chdir=environments/dev plan \
  -destroy \
  -out=tfplan-destroy
```

Apply only the reviewed plan:

```bash
terraform -chdir=environments/dev apply \
  tfplan-destroy
```

Confirm that EKS, worker nodes, NAT Gateway, ALB, and RDS are gone. Do not destroy the backend until its state is no longer required.

## Security Rules

- Never commit AWS or database credentials.
- Never commit the real `deployment.auto.tfvars`.
- Never permit unrestricted EKS endpoint access.
- Never use literal placeholder values in live commands.
- Never apply an unreviewed Terraform plan.
- Never deploy from an unreviewed branch.
- Use GitHub OIDC instead of long-lived AWS keys.
- Confirm the AWS account, region, Kubernetes context, and expected cost before every live operation.
