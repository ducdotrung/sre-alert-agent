# AKS Deployment

This directory packages the alert agent for a first AKS deployment without adding auth or database layers yet.

It is intentionally sanitized for public use:

- image names are placeholders
- URLs use example domains
- gateway and namespace names are generic

If you want to run this on EKS instead, treat this folder as a reference and replace the storage class, registry, and ingress pieces with AWS equivalents.

## Shape

- one Docker image reused by all workloads
- one review web `Deployment`
- one shared `PersistentVolumeClaim` mounted at `/app/output`
- CronJobs matching workstation behavior:
  - pipeline every minute
  - health check every 5 minutes
  - self-improve weekly
- config from image files plus environment variables from Kubernetes `ConfigMap` and `Secret`

## Why The PVC Mount Is `/app/output`

The current orchestrator still assumes relative `output/` paths in a few places. Mounting the claim at `/app/output` keeps those paths aligned without refactoring the pipeline first.

## Files

- `namespace.yaml`: dedicated namespace
- `configmap.yaml`: non-secret environment defaults
- `secret.example.yaml`: placeholder secrets to copy and fill
- `persistentvolumeclaim.yaml`: shared writable storage
- `review-web-deployment.yaml`: review UI pod
- `review-web-service.yaml`: ClusterIP service for the review UI
- `pipeline-cronjob.yaml`: main triage -> review -> recommendation -> sender pipeline
- `pipeline-health-cronjob.yaml`: stale-run and lock monitoring
- `self-improve-cronjob.yaml`: weekly self-improvement run
- `queue-health-cronjob.yaml`: optional extra queue monitor
- `istio-review-web.example.yaml`: dedicated host example
- `istio-review-web-shared-gateway.example.yaml`: shared-host path-prefix example
- `kustomization.yaml`: apply the default set as one package

## Build And Push

```bash
docker build -t ghcr.io/example/sre-alert-agent:latest .
docker push ghcr.io/example/sre-alert-agent:latest
```

The manifests in this directory currently point at:

```text
ghcr.io/example/sre-alert-agent:latest
```

Change the tag before each release, or patch it with Kustomize or `kubectl set image`.

## First Apply

```bash
cp deploy/aks/secret.example.yaml /tmp/sre-alert-agent-secret.yaml
# edit /tmp/sre-alert-agent-secret.yaml with real values

kubectl apply -f /tmp/sre-alert-agent-secret.yaml
kubectl apply -k deploy/aks
```

If your cluster requires a different storage class name, image pull secret, or ingress shape, edit:

- `persistentvolumeclaim.yaml`
- `review-web-deployment.yaml`
- the `CronJob` manifests
- the Istio examples

## Optional Istio Exposure

Apply one option only:

```bash
# Option A: dedicated host
kubectl apply -f deploy/aks/istio-review-web.example.yaml

# Option B: shared host + path prefix
kubectl apply -f deploy/aks/istio-review-web-shared-gateway.example.yaml
```

The review web supports both:

- requests under `/sre-alert-review` on a shared host
- requests under `/` on a dedicated host

Set `REVIEW_WEB_BASE_URL` to the canonical public URL you want to emit in Teams cards and review links.

## Verify

```bash
kubectl get pods -n sre-alert-agent
kubectl get cronjobs -n sre-alert-agent
kubectl get pvc -n sre-alert-agent
kubectl logs -n sre-alert-agent deploy/sre-alert-review-web
kubectl create job --from=cronjob/sre-alert-pipeline sre-alert-pipeline-manual -n sre-alert-agent
kubectl logs -n sre-alert-agent job/sre-alert-pipeline-manual
```

## Current Limits

- review web is not authenticated yet
- pipeline is still designed around a single shared writer
- file queues on a PVC are acceptable for this stage, but not the end-state for multi-tenant or high-concurrency use
