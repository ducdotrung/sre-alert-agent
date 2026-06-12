# Handoff - 2026-06-12 EKS Packaging

## Session Summary

- Kept `deploy/aks/` in place as the Azure reference.
- Added a separate `deploy/eks/` package for the AWS hackathon target path.

## Added

- `deploy/eks/README.md`
- `deploy/eks/configmap.yaml`
- `deploy/eks/namespace.yaml`
- `deploy/eks/persistentvolumeclaim.yaml`
- `deploy/eks/review-web-deployment.yaml`
- `deploy/eks/review-web-service.yaml`
- `deploy/eks/ingress.yaml`
- `deploy/eks/pipeline-cronjob.yaml`
- `deploy/eks/pipeline-health-cronjob.yaml`
- `deploy/eks/queue-health-cronjob.yaml`
- `deploy/eks/self-improve-cronjob.yaml`
- `deploy/eks/secret.example.yaml`
- `deploy/eks/kustomization.yaml`

## Packaging Shape

- ECR image placeholders: `123456789012.dkr.ecr.us-east-1.amazonaws.com/sre-alert-agent:latest`
- RWX storage placeholder: `efs-sc`
- standard Kubernetes `Ingress` with common AWS Load Balancer Controller annotations
- no Istio resources

## Docs Updated

- `README.md` now links to both `deploy/eks/` and `deploy/aks/`
- `docs/DEPLOYMENT.md` now positions `deploy/eks/` as the AWS starting point

## Exact Next Step

Provide real deploy-time environment values for:

- `IMAGE_URI`
- `REVIEW_WEB_BASE_URL`
- `EKS_REVIEW_WEB_HOST`
- `AWS_ACM_CERT_ARN`
- `EKS_EFS_STORAGE_CLASS`
