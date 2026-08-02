# High CPU Usage

A pod or node is experiencing sustained high CPU usage or CPU throttling.
Alertnames: `HighCPUUsage`, `CPUThrottlingHigh`,
`KubeCPUOvercommit`.

## Symptoms

- CPU usage above the alerting threshold (typically 80–90%) for several
  minutes.
- Elevated `container_cpu_cfs_throttled_seconds_total` when throttled.
- Increased request latency; possible timeouts on CPU-bound endpoints.

## Diagnosis

1. Identify the hot pods:
   `kubectl top pods -n <namespace> --sort-by=cpu`.
2. Distinguish saturation (usage near node capacity) from throttling (usage
   at the container CPU limit while the node is idle):
   compare `container_cpu_usage_seconds_total` against the CPU limit.
3. Correlate with traffic: check request rate metrics for a spike, a cron
   job, or a retry storm.
4. Check for a recent deploy that could have introduced a hot loop or an
   N+1 query.

## Remediation

- Throttled: raise the CPU limit (or remove it and keep only requests) and
  redeploy.
- Saturated by load: scale out —
  `kubectl scale deployment/<name> -n <namespace> --replicas=<n>` — or verify
  the HPA is working and not capped by `maxReplicas`.
- If caused by a bad deploy, roll back while investigating.

## Escalation

If the whole node is saturated and the workload cannot scale out, escalate
to the platform team to add capacity or rebalance the node pool.
