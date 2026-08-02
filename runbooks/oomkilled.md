# OOMKilled

A container was killed by the kernel OOM killer because it exceeded its
memory limit. Alertnames: `OOMKilled`, `KubeContainerOOMKilled`. Exit code
137.

## Symptoms

- Pod restarts with reason `OOMKilled` in `kubectl get pods`.
- Memory usage climbing steadily until it hits the container limit.
- Requests latency spikes or gaps in metrics before the kill.

## Diagnosis

1. Confirm the kill reason:
   `kubectl describe pod <pod> -n <namespace>` → `Last State: OOMKilled`.
2. Compare actual usage against the limit:
   `kubectl top pod <pod> -n <namespace>` and check
   `container_memory_working_set_bytes` vs `resources.limits.memory`.
3. Identify the growth pattern: a steady climb suggests a memory leak; a
   sudden spike suggests a large request/batch job or cache fill.
4. Check for a recent deploy or traffic change that correlates with the
   first kill.

## Remediation

- Short term: raise the memory limit (and request) to match observed usage
  plus headroom, then redeploy.
- If usage grows without bound, treat it as a leak: capture a heap/profile
  dump before the next kill and hand it to the owning team.
- Consider Vertical Pod Autoscaler recommendations for right-sizing.

## Escalation

If the workload is memory-critical (databases, queues) and kills repeat
after a limit increase, escalate to the owning team immediately — data loss
or corruption is possible.
