# KubeNodeNotReady

A Kubernetes node has stopped reporting Ready status to the control plane.
Alertname: `KubeNodeNotReady`.

## Symptoms

- `kubectl get nodes` shows the node as `NotReady`.
- Pods on the node are stuck `Terminating`, `Unknown`, or being evicted.
- Workloads on the affected node stop serving traffic.

## Diagnosis

1. Describe the node to see the failing condition:
   `kubectl describe node <node>` — look at `Conditions` (Ready=False with
   reason like `KubeletNotReady`) and recent events.
2. Check the kubelet on the node:
   `systemctl status kubelet` and `journalctl -u kubelet -n 100`.
3. Common causes: node out of disk (DiskPressure), out of memory
   (MemoryPressure), network partition, kernel panic, or cloud provider
   instance termination.
4. Check cloud provider status for the underlying VM/instance.

## Remediation

- Cordon the node to stop new scheduling:
  `kubectl cordon <node>`.
- If the node is unhealthy beyond a quick kubelet restart, drain it:
  `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data`.
- Restart the kubelet for transient failures; replace the node (or let the
  autoscaler/machine controller replace it) for hardware or instance
  failures.
- Verify displaced pods reschedule and become ready on healthy nodes.

## Escalation

If multiple nodes go NotReady at once, suspect control-plane or network
infrastructure — escalate to the platform team immediately.
