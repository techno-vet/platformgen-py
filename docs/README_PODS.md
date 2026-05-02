# Pods Widget

The **Pods** widget is a Kubernetes pod status monitor. View pod health across clusters and namespaces, stream logs, exec into containers, and trigger restarts — all from inside Auger.

## Features

| Feature | Detail |
|---------|--------|
| **Pod list** | Real-time list of pods with status, restarts, age, and node |
| **Namespace filter** | Filter by namespace or show all |
| **Cluster selector** | Switch between kubeconfig contexts |
| **Color coding** | Running=green, Pending=yellow, CrashLoopBackOff=red, Terminating=grey |
| **Log stream** | Select a pod → click **Logs** to tail output in a scrollable pane |
| **Exec** | Open a shell inside a running container |
| **Restart** | Delete a pod to trigger a rolling restart |
| **Describe** | Full `kubectl describe pod` output |
| **Auto-refresh** | Refreshes every 10 seconds |

## Authentication

Uses `~/.kube/config` (volume-mounted from the host). The widget respects your active kubeconfig context and all configured clusters.

```bash
# Switch context from the Shell Terminal widget or Ask Auger:
kubectl config use-context my-cluster
```

## Rancher Integration

If `RANCHER_BEARER_TOKEN` and `RANCHER_URL` are set in `.env`, the widget can also list pods via the Rancher API — useful for clusters where direct kubectl access isn't available.

```bash
RANCHER_URL=https://rancher.helix.gsa.gov
RANCHER_BEARER_TOKEN=<your-rancher-token>
```

For rollout monitoring, prefer generating a Rancher-backed kubeconfig and using `kubectl` first for namespace-scoped checks like deployments, statefulsets, pods, and image tags. That kubeconfig authenticates as the same Rancher-backed user, so it helps with direct workload reads but does **not** bypass RBAC for restricted resources such as Flux `HelmRelease` objects in `tenant-flux-ns`.

## Common Workflows

**Find all crashing pods:**
> Filter status = `CrashLoopBackOff`

**View logs for a failing pod:**
> Select the pod → click **Logs** → logs stream in the right pane

**Ask Auger to investigate:**
> *"Why is pod data-utils-api-xyz crashing?"*
> Auger will pull logs, describe the pod, and suggest fixes.
