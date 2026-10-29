# Pass 3 — Kubernetes manifest check tables

## Security context — `p3.k8s.<chart>.security.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `run-as-non-root` | `runAsNonRoot: true` on pod spec | Set in `defaults/values.yaml` podSecurityContext |
| `run-as-user-nonzero` | `runAsUser` is non-zero | Set to `65532` in defaults |
| `no-privilege-escalation` | `allowPrivilegeEscalation: false` on every container | Set in securityContext |
| `capabilities-drop-all` | `capabilities.drop: [ALL]` | Set in securityContext |
| `no-privileged` | No `privileged: true` | Flag — never auto-remove |
| `no-host-network` | No `hostNetwork`, `hostPID`, `hostIPC` | Flag |
| `no-host-path` | No `hostPath` volumes | Flag |
| `sa-automount-false` | `automountServiceAccountToken: false` unless workload calls API server | Set |
| `readonly-rootfs` | `readOnlyRootFilesystem: true` | Set; add `/tmp` emptyDir if missing |
| `seccomp-runtimedefault` | `seccompProfile.type: RuntimeDefault` | Set in podSecurityContext |

## Resources — `p3.k8s.<chart>.resources.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `limits-set` | Every container (including init and sidecars) has `resources.limits` | Flag — values depend on workload; add commented example |
| `requests-set` | Every container has `resources.requests` | Flag — same reason |
| `no-empty-resources` | No `resources: {}` | Replace with commented example |

Resources require domain knowledge (CPU/memory sizing) — never auto-fill with numbers. Add the recommended commented-out shape from the `helm` skill and set `status: failed` prompting the operator to fill in values.

## Image hygiene — `p3.k8s.<chart>.image.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `no-latest` | No `:latest` tag in any values file | Flag |
| `tag-or-digest` | Every image reference has a tag or digest | Flag |

## Probes — `p3.k8s.<chart>.probes.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `readiness-exists` | HTTP services have `readinessProbe` | Add stub — endpoint requires human input |
| `liveness-exists` | Long-running services have `livenessProbe` | Add stub |
| `startup-for-slow-start` | Slow-starting apps have `startupProbe` | Flag — timing requires human input |
| `no-tcp-on-http` | HTTP services don't use TCP probes | Replace with httpGet stub |

Probe endpoints and thresholds cannot be derived from the chart alone. Create a stub pointing to the helm `patterns.md` probe templates and set `status: failed` for human completion.

## High availability — `p3.k8s.<chart>.ha.*`

Check only when `replicaCount >= 2` or `autoscaling.minReplicas >= 2`:

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `pdb-exists` | PDB template present and enabled | Create stub if absent |
| `anti-affinity` | `topologySpreadConstraints` or `affinity` set in defaults | Add standard spread from `kubernetes/resource-standards.md` |

## Labels and selectors — `p3.k8s.<chart>.labels.*`

The label set is **owned by the `helm` skill** (`_helpers.tpl` labels helper + `patterns.md`'s
component-label rule) and checked by `kubernetes/reviewing-manifests.md`. Don't restate a
partial list here — read those and apply theirs, so this pass can't drift from them.

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `recommended-labels` | The full set from `reviewing-manifests.md` is present: `name`, `instance`, `version`, `component`, `part-of`, `managed-by` | Add via the `_helpers.tpl` labels helper — never by hand-writing labels into a template |
| `component-label` | Every workload carries a unique `app.kubernetes.io/component` per `helm/patterns.md` | Add via `componentLabels`; for Deployments/StatefulSets it must also be in the selector |
| `selector-stable` | No version-y label in `spec.selector.matchLabels` | Remove version from selector |
| `selector-subset-of-labels` | `matchLabels` is a subset of `metadata.labels` | Fix |
| `no-competing-label-vocab` | No bare-key duplicate of an `app.kubernetes.io/*` key (`app:`, `service:` alongside them) — see the `tagging` skill's ownership boundary | Consolidate onto the standard keys |

Adding a component label to an **existing** Deployment/StatefulSet selector forces a
delete/recreate — selectors are immutable. If the workload is already live without one,
mark the item `failed` and explain, rather than auto-fixing it.

## GitOps — `p3.k8s.<chart>.gitops.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `no-kubectl-apply-in-readme` | README doesn't instruct `kubectl apply` to managed cluster | Flag |
| `sync-wave-correct` | Prerequisites at lower wave numbers than dependents | Flag — wave ordering requires repo knowledge |
