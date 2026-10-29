# Kubernetes Resource Standards

The defaults below are the floor for any workload. Reviewing means checking against this list; authoring means starting from it.

## Security context

Every Pod spec needs both a `podSecurityContext` and a per-container `securityContext`. The pod-level one sets ownership and seccomp; the container-level one drops capabilities and blocks privilege escalation.

```yaml
spec:
  securityContext:                       # pod-level
    runAsNonRoot: true
    runAsUser: 65532                     # nobody-equivalent; pick a non-zero UID
    runAsGroup: 65532
    fsGroup: 65532                       # only if the pod mounts writable volumes
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      securityContext:                   # container-level
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true     # add emptyDir mounts for /tmp etc. as needed
        capabilities:
          drop: [ALL]
```

When `readOnlyRootFilesystem: true` breaks the app, mount `emptyDir` volumes at the specific writable paths (`/tmp`, the framework's cache dir) rather than disabling the flag.

When the workload genuinely needs a capability (e.g., `NET_BIND_SERVICE` to bind port 80), drop ALL and add back only what's needed:
```yaml
capabilities:
  drop: [ALL]
  add: [NET_BIND_SERVICE]
```

## Resource requests and limits

Required on every container, including init containers and sidecars.

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: "1"
    memory: 512Mi
```

Guidance:
- **Memory limit ≈ memory request** for predictable eviction behavior. Big gaps cause OOMKilled surprises.
- **CPU limit may exceed CPU request**, but consider whether you actually want CPU throttling — for latency-sensitive services many teams omit CPU limits intentionally and rely on requests for scheduling.
- For JVM apps, set `-XX:MaxRAMPercentage` rather than `-Xmx`, and leave headroom (~20%) between heap and the container limit.
- Init containers count toward scheduling — pick the highest request among initContainers, not the sum.

## Probes

| Probe | Purpose | Failure action |
|---|---|---|
| `startupProbe` | "Has the app finished booting?" | Delays liveness/readiness checks; only for slow starters |
| `readinessProbe` | "Should this pod receive traffic?" | Removes pod from Service endpoints |
| `livenessProbe` | "Is the app stuck?" | Restarts the container |

Patterns that go wrong:
- Liveness probe hitting the same endpoint as readiness, with the same thresholds — when a dependency blips, pods restart instead of just leaving the load balancer.
- Liveness probe with no `initialDelaySeconds` or `startupProbe` — slow-starting apps get killed mid-boot.
- TCP probe on an HTTP service — passes even when the app is returning 500s.

Reasonable defaults for an HTTP service:
```yaml
startupProbe:
  httpGet: { path: /health, port: http }
  failureThreshold: 30
  periodSeconds: 5         # gives 150s to start
readinessProbe:
  httpGet: { path: /ready, port: http }
  periodSeconds: 5
  timeoutSeconds: 2
livenessProbe:
  httpGet: { path: /health, port: http }
  periodSeconds: 15
  timeoutSeconds: 3
  failureThreshold: 3
```

## High availability

For anything with `replicas > 1`:

**PodDisruptionBudget** — protects against voluntary disruptions (node drains):
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: myapp
spec:
  maxUnavailable: 1        # or minAvailable: N-1
  selector:
    matchLabels:
      app.kubernetes.io/name: myapp
```
Pick `maxUnavailable: 1` for most workloads. For stateful systems with quorum (etcd, ZooKeeper, Kafka controllers), use `minAvailable` and set it so quorum is preserved.

**Topology spread** — prefer this over raw anti-affinity for spreading across zones/nodes:
```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway       # DoNotSchedule only if the cluster has enough zones
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: myapp
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: myapp
```

`whenUnsatisfiable: DoNotSchedule` is correct in theory but bites in practice when a zone is briefly unavailable. `ScheduleAnyway` is the safer default unless the workload genuinely cannot survive on one zone.

## Labels and selectors

Use the [recommended labels](https://kubernetes.io/docs/concepts/overview/working-with-objects/common-labels/):
```yaml
metadata:
  labels:
    app.kubernetes.io/name: myapp
    app.kubernetes.io/instance: myapp-prod
    app.kubernetes.io/version: "1.4.2"
    app.kubernetes.io/component: api
    app.kubernetes.io/part-of: payments
    app.kubernetes.io/managed-by: Helm
```
Selectors (`spec.selector.matchLabels`, Service selectors) are immutable on Deployments and StatefulSets — pick a stable subset (typically `name` + `instance`) and never include version-y labels in the selector.

## Storage

- Always specify a `storageClassName` explicitly. Don't rely on the cluster default; it can change.
- Set realistic sizes — a 1Gi PVC for a database is asking for trouble, a 1Ti PVC for a config volume wastes money.
- `accessModes: [ReadWriteOnce]` is the safe default. `ReadWriteMany` requires a CSI driver that supports it (NFS, CephFS, EFS).
- For StatefulSets, use `volumeClaimTemplates`, not a manually created PVC — the operator pattern needs the per-replica PVCs to be auto-generated.

## ConfigMaps and Secrets

- Mount as files when the config is hot-reloadable; use env vars for simple settings the app reads at boot.
- For Secrets, prefer `external-secrets` with `ExternalSecret` referencing Vault/AWS SM/etc. Never commit a Secret with literal `data:` values to git. The **`secrets` skill owns the full contract** — source modes, Vault paths, the `/var/run/secrets/<block>/<key>` mount path, and the `*_FILE` env convention; apply it rather than improvising per chart.
- Use the `reloader` annotation (or equivalent) to roll Deployments when their ConfigMap/Secret changes:
  ```yaml
  metadata:
    annotations:
      reloader.stakater.com/auto: "true"
  ```

## Networking

- **Services**: `ClusterIP` is the default and almost always correct. `LoadBalancer` only for external-facing endpoints; `NodePort` rarely.
- **Ingress / Gateway**: prefer Gateway API (`HTTPRoute`) on new clusters; `Ingress` is fine on older ones.
- **NetworkPolicy**: every namespace should have a default-deny egress and ingress, with explicit allows. If the team has a baseline policy, reference it; if not, mention adding one.
- **DNS**: use `external-dns` annotations rather than manually managing records:
  ```yaml
  metadata:
    annotations:
      external-dns.alpha.kubernetes.io/hostname: api.example.com
  ```

## TLS

- Use `cert-manager` `Certificate` resources, not raw `Secret`s with manually-generated certs.
- Internal services: use the cluster's internal CA `ClusterIssuer`.
- Public-facing: Let's Encrypt (`letsencrypt-prod`) — and remember to test against `letsencrypt-staging` first to avoid rate limits.

## Operator-managed resources

When a workload is managed by an operator, use the CRD — don't bypass the operator with raw Deployments/StatefulSets.

### CloudNativePG (Postgres)
Use `Cluster` (api: `postgresql.cnpg.io/v1`). Define `instances` (replica count), `storage`, `backup` (point to an `ObjectStore`), and `monitoring.enablePodMonitor: true`. Don't write your own Postgres StatefulSet alongside it.

### Strimzi (Kafka) / Redpanda
Topics and users are CRDs (`KafkaTopic`, `KafkaUser` for Strimzi; `Topic`, `User` for Redpanda) and belong in the same chart as the cluster. Pick partition count for the throughput you actually expect, not the maximum imaginable — repartitioning later is painful but possible; over-partitioning wastes broker resources permanently.

```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: orders
  labels:
    strimzi.io/cluster: main
spec:
  partitions: 6
  replicas: 3
  config:
    retention.ms: "604800000"     # 7d
    min.insync.replicas: "2"
```

### ClickHouse (Altinity operator)
Use `ClickHouseInstallation`. Plan sharding before deploying — changing shard count later means re-sharding data. Distributed tables need to be created on every node; the operator handles this if configured correctly.

## Common smells

These show up in reviews more than they should:

- A `Deployment` for something stateful (databases, message queues, anything with persistent disk per replica) — should be a `StatefulSet` or operator CRD.
- `imagePullPolicy: Always` with a fixed tag — wastes pulls; use `IfNotPresent` for tagged images.
- `resources` block missing entirely, or only `requests` and no `limits` (or vice versa).
- `replicas: 3` with no PDB and no anti-affinity — fake HA.
- `hostPath` volumes — almost always wrong; the workload is now node-bound.
- `automountServiceAccountToken: true` (the default) on workloads that don't talk to the API server. Set it to `false` explicitly.
