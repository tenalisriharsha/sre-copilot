# KubePodCrashLooping

A pod in the cluster is crash looping: its containers start, exit, and are
restarted repeatedly. Alertname: `KubePodCrashLooping` (container status
`CrashLoopBackOff`).

## Symptoms

- Pod restarts increasing rapidly (`kube_pod_container_status_restarts_total`).
- `kubectl get pods` shows `CrashLoopBackOff` for the affected pod.
- Application endpoints intermittently failing or unavailable.

## Diagnosis

1. Check container logs from the current and previous instance:
   `kubectl logs <pod> -n <namespace> --previous`.
2. Describe the pod to see exit codes and events:
   `kubectl describe pod <pod> -n <namespace>`.
   Exit code 1 usually means an application error; 137 means OOMKilled.
3. Look for missing config: ConfigMaps, Secrets, environment variables, or
   unreachable dependencies (database, upstream API) at startup.
4. If the exit code is 137 or the reason is OOMKilled, follow the OOMKilled
   runbook instead.

## Remediation

- Fix the underlying application error (bad config, missing secret, failed
  migration) and roll out a new deployment.
- If a bad image or config was just deployed, roll back:
  `kubectl rollout undo deployment/<name> -n <namespace>`.
- As a temporary measure for a known-bad replica, delete the pod to force a
  reschedule after the fix is deployed.

## Escalation

If restarts continue after a rollback, page the owning team with the pod
name, namespace, exit code, and the last 50 log lines.
