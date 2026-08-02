# ImagePullBackOff

Kubernetes cannot pull the container image for a pod. Alertnames:
`ImagePullBackOff`, `KubeImagePullError`, `ErrImagePull`.

## Symptoms

- Pod stuck in `ImagePullBackOff` or `ErrImagePull`.
- New replicas never become ready after a deploy or scale-up.
- Events show `Failed to pull image ... rpc error` messages.

## Diagnosis

1. Read the pull error from pod events:
   `kubectl describe pod <pod> -n <namespace>`.
2. Common causes:
   - Tag does not exist (typo, or CI pushed a different tag).
   - Private registry authentication failure (missing/expired imagePullSecret).
   - Registry outage or network policy blocking egress to the registry.
   - Image pull rate limiting (Docker Hub anonymous pulls).
3. Verify the image reference in the deployment matches a tag that exists in
   the registry.

## Remediation

- Fix the image tag in the deployment and roll out again.
- For auth failures, rotate or recreate the imagePullSecret and reference it
  in the service account or pod spec.
- If the registry is down, wait for recovery or fail over to a mirrored
  registry; do not keep restarting pods.

## Escalation

If the registry itself is unavailable and it hosts production images,
escalate to the platform team — this blocks all deploys and scale-ups.
