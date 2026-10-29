# Troubleshooting Kubernetes Workloads

Symptom-first decision trees. Match the user's symptom to a section, then walk it.

## Pod is not Running

### `Pending`

```bash
kubectl describe pod <pod> -n <ns>          # the Events at the bottom are the answer
kubectl get events -n <ns> --sort-by=.lastTimestamp | tail -20
```

Common causes by event message:

| Event contains | Cause | Fix |
|---|---|---|
| `0/N nodes are available: insufficient cpu/memory` | Cluster doesn't have room | Lower requests, scale cluster, or check for stuck pods hogging capacity |
| `didn't match Pod's node affinity/selector` | nodeSelector/affinity points to non-existent nodes | Check labels on actual nodes vs the selector |
| `had untolerated taint` | Pod missing a toleration for the targeted node | Add toleration, or pick a different node pool |
| `pod has unbound immediate PersistentVolumeClaims` | PVC isn't binding | See PVC troubleshooting below |
| `volume node affinity conflict` | PV is in a zone the pod can't be scheduled to | Either move the pod to that zone or recreate PV correctly |
| `0/N nodes are available: N node(s) didn't match topology spread constraints` | `whenUnsatisfiable: DoNotSchedule` is too strict | Switch to `ScheduleAnyway` or add zone capacity |

### `ImagePullBackOff` / `ErrImagePull`

```bash
kubectl describe pod <pod> -n <ns> | grep -A2 'Failed\|Warning'
```

- **`manifest unknown` / `not found`**: typo in `image:`, wrong tag, or registry/repo mismatch
- **`unauthorized` / `denied`**: missing or wrong `imagePullSecrets`. Check the secret exists in the *same namespace* as the pod, and the SA references it
- **`x509: certificate signed by unknown authority`**: registry is using a private CA the node doesn't trust — usually a node-config issue, not a pod issue
- **Stuck for a long time on a public image**: rate limiting (Docker Hub). Switch to a mirror or use authenticated pulls

### `CrashLoopBackOff`

```bash
kubectl logs <pod> -n <ns> --previous       # the previous container's logs
kubectl logs <pod> -n <ns> -c <container>   # if multi-container
kubectl describe pod <pod> -n <ns>          # check 'Last State' for exit code
```

Exit code interpretation:
- **0**: app exited cleanly — probably running a command that finished. Maybe should be a `Job`?
- **1**: app error. Read the logs.
- **137**: SIGKILL — usually OOMKilled. Check `kubectl describe pod` for `OOMKilled: true`. Increase memory limit or fix the leak.
- **139**: segfault. Native code bug, missing shared library.
- **143**: SIGTERM — usually fine on shutdown; problem if happening on startup (something killing the pod)

If the logs show the app starting fine then dying:
- Check if the liveness probe is too aggressive — initial delay too short, or hitting an endpoint that's slow during startup
- A startup probe will solve this for slow-booting apps

If logs are empty:
- The container may be crashing before stdout is set up — try `kubectl debug` with an ephemeral container
- Or the previous container is gone — `--previous` only works for the most recent crash

### `Init:Error` / `Init:CrashLoopBackOff`

```bash
kubectl logs <pod> -c <init-container-name> -n <ns>
```
Init containers run sequentially. The one named in the status is the one failing — its logs are where the answer is.

## PVC stuck `Pending`

```bash
kubectl describe pvc <pvc> -n <ns>
kubectl get storageclass
```

- **`storageclass.storage.k8s.io "<name>" not found`**: typo or the class doesn't exist on this cluster
- **`waiting for first consumer to be created before binding`**: the StorageClass uses `WaitForFirstConsumer`. The PVC binds when a pod that uses it is scheduled. If no pod uses it, this is normal and stays Pending.
- **No events at all**: provisioner isn't running. Check the storage operator pods (e.g., `kubectl get pods -n <storage-ns>`)
- **`requested storage does not match`**: PVC size larger than what the class allows, or accessMode mismatch

## ArgoCD Application not syncing

```bash
kubectl get application <app> -n argocd -o yaml | yq '.status'
argocd app get <app>
argocd app diff <app>                       # see what's drifting
```

| Status | Likely cause |
|---|---|
| `OutOfSync` but not syncing | Manual sync mode, or auto-sync paused. Check `spec.syncPolicy.automated` |
| `SyncFailed` with CRD-related error | CRDs not installed first — sync wave issue (see team-conventions for wave ordering) |
| `SyncFailed` with `the server could not find the requested resource` | CRD missing entirely, or apiVersion wrong |
| `SyncFailed` with permission error | ArgoCD service account lacks RBAC for that resource type |
| `Healthy` but the app isn't actually working | ArgoCD reports health from the resources' status fields — the app may need a custom health check |
| Stuck on `Progressing` | Some resource (often a StatefulSet or operator CR) reports Progressing forever — check its status |

For sync wave issues specifically: ArgoCD applies all resources in a wave, waits for them to be healthy, then proceeds. A misconfigured health check on a wave-N resource will block wave N+1 forever.

## Service has no endpoints

```bash
kubectl get endpoints <svc> -n <ns>         # if empty, no pods match
kubectl get pods -n <ns> --show-labels
kubectl describe svc <svc> -n <ns>
```

- **No endpoints, but pods exist**: `Service.spec.selector` doesn't match any pod's labels. Check both — typos and case-sensitivity bite here.
- **Endpoints exist but `NotReadyAddresses`**: pods are running but failing readiness probe. Check the readiness probe and the pod logs.
- **Endpoints exist, traffic still fails**: NetworkPolicy blocking? `containerPort` vs `targetPort` mismatch?

## Pod is Running but unreachable

Walk the layers from outside in:

1. **DNS**: `kubectl run -it --rm dnstest --image=busybox -- nslookup <svc>.<ns>.svc.cluster.local`
2. **Service routing**: `kubectl get endpoints <svc> -n <ns>` — does the Service know about the pod?
3. **NetworkPolicy**: `kubectl get networkpolicy -n <ns>` — is something blocking?
4. **Pod port**: `kubectl exec <pod> -n <ns> -- ss -tlnp` (or `netstat`) — is the app actually listening on the port the Service points to?
5. **App-level**: `kubectl exec <pod> -n <ns> -- curl localhost:<port>/health`

If the Service is `LoadBalancer`/`Ingress`, also check the cloud provider's LB / the ingress controller logs.

## "It worked yesterday"

```bash
kubectl rollout history deployment/<name> -n <ns>
kubectl get events -n <ns> --sort-by=.lastTimestamp
```

Quick-win checks:
- `kubectl rollout undo deployment/<name>` if a recent change broke it
- Look for cluster-wide changes in events — node draining, version bumps
- Check ArgoCD sync history for the app — was something synced that shouldn't have been?

## Useful one-liners

```bash
# Top 10 most-restarted pods in cluster
kubectl get pods -A --no-headers | awk '{print $5, $1, $2}' | sort -rn | head

# Pods that aren't Running or Succeeded
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded

# Events from the last 5 minutes, cluster-wide
kubectl get events -A --sort-by=.lastTimestamp | tail -30

# All resources in a namespace (catches things `get all` misses, like CRDs)
kubectl api-resources --verbs=list --namespaced -o name \
  | xargs -n1 -I{} kubectl get {} -n <ns> --ignore-not-found

# Why is this pod really using N MB of memory
kubectl top pod <pod> -n <ns> --containers

# Get into a pod with no shell (distroless / scratch)
kubectl debug <pod> -n <ns> -it --image=busybox --target=<container>
```

## When to escalate vs keep digging

It's worth saying explicitly: not every K8s problem is solvable from the cluster side. If you've gotten to:
- "the cloud provider's LoadBalancer is not provisioning"
- "the storage operator's CSI driver is failing on the node"
- "the cluster's CNI is dropping packets between specific nodes"

…the answer is usually with the platform team, not in another `kubectl describe`. Capture what you've tried and hand off rather than spiraling.
