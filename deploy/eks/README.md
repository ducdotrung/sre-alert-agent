# EKS Deployment

This directory packages the alert agent for an AWS-based deployment on EKS.

It assumes:

- one Docker image stored in Amazon ECR
- one review web `Deployment`
- one shared `PersistentVolumeClaim` mounted at `/app/output`
- CronJobs for the pipeline, health checks, and self-improvement
- standard Kubernetes `Ingress` instead of Istio

## AWS Assumptions

- the cluster already exists in EKS
- the AWS Load Balancer Controller is installed for `Ingress`
- the Amazon EFS CSI driver is installed for shared RWX storage
- an EFS-backed `StorageClass` exists, or you will change `storageClassName`

The manifests are intentionally generic. Replace the placeholder account ID, region, domain, and ACM certificate ARN before applying.
The manifests are written to be rendered with environment variables, so you do not need to edit the files directly.

## Files

- `namespace.yaml`: dedicated namespace
- `configmap.yaml`: non-secret environment defaults
- `secret.example.yaml`: placeholder secrets to copy and fill
- `persistentvolumeclaim.yaml`: shared writable storage using an EFS-style storage class
- `review-web-deployment.yaml`: review UI pod
- `review-web-service.yaml`: ClusterIP service for the review UI
- `ingress.yaml`: ALB-backed ingress example
- `pipeline-cronjob.yaml`: main triage -> review -> recommendation -> sender pipeline
- `pipeline-health-cronjob.yaml`: stale-run and lock monitoring
- `self-improve-cronjob.yaml`: weekly self-improvement run
- `queue-health-cronjob.yaml`: optional extra queue monitor
- `kustomization.yaml`: apply the default set as one package

## Build And Push

```bash
export AWS_ACCOUNT_ID=123456789012
export AWS_REGION=us-east-1
export IMAGE_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/sre-alert-agent:latest

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -t $IMAGE_URI .
docker push $IMAGE_URI
```

The manifests in this directory currently point at:

```text
${IMAGE_URI}
```

Change the tag before each release by updating `IMAGE_URI` before rendering.

## Required Environment Variables

Set these before rendering:

```bash
export IMAGE_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/sre-alert-agent:latest
export REVIEW_WEB_BASE_URL=https://alerts.example.com
export EKS_REVIEW_WEB_HOST=alerts.example.com
export AWS_ACM_CERT_ARN=arn:aws:acm:us-east-1:123456789012:certificate/replace-me
export EKS_EFS_STORAGE_CLASS=efs-sc
```

If you want the review UI under a path prefix later, set `REVIEW_WEB_BASE_URL` accordingly and adjust the ingress path from `/` to your prefix.

## First Apply

```bash
cp deploy/eks/secret.example.yaml /tmp/sre-alert-agent-eks-secret.yaml
# edit /tmp/sre-alert-agent-eks-secret.yaml with real values

kubectl apply -f /tmp/sre-alert-agent-eks-secret.yaml

find deploy/eks -name '*.yaml' ! -name 'secret.example.yaml' -print0 \
  | xargs -0 -I{} sh -c 'envsubst < "$1"' _ {} \
  | kubectl apply -f -
```

If your cluster uses a different EFS storage class, ingress class, certificate model, or image repository, edit:

- the environment variables above
- `ingress.yaml` if you want a different ingress controller or routing shape

## Ingress

The included `ingress.yaml` is a normal Kubernetes `Ingress` using common AWS Load Balancer Controller annotations:

- internet-facing ALB
- HTTPS redirect
- ACM certificate ARN from `${AWS_ACM_CERT_ARN}`
- host-based routing for `${EKS_REVIEW_WEB_HOST}`

The review web also supports running under a subpath. If you later want `https://example.com/sre-alert-review`, change:

- `REVIEW_WEB_BASE_URL` in your shell environment
- the `paths` section in `ingress.yaml`

No Istio-specific routing is required.

## Verify

```bash
kubectl get pods -n sre-alert-agent
kubectl get cronjobs -n sre-alert-agent
kubectl get pvc -n sre-alert-agent
kubectl get ingress -n sre-alert-agent
kubectl logs -n sre-alert-agent deploy/sre-alert-review-web
kubectl create job --from=cronjob/sre-alert-pipeline sre-alert-pipeline-manual -n sre-alert-agent
kubectl logs -n sre-alert-agent job/sre-alert-pipeline-manual
```

## Current Limits

- review web is not authenticated yet
- pipeline is still designed around a single shared writer
- file queues on a RWX volume are acceptable for this stage, but not the end-state for high-concurrency or multi-tenant use
