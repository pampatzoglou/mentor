# Reviewing Kubernetes Manifests

Use when the user asks to review, audit, or sanity-check existing YAML — Helm chart, raw manifest, or the rendered output of `helm template`.

## Review the rendered output, not the base values

Run this checklist against **rendered manifests** (`task template:<env>`, or `helm template` with the full values layering), not against a chart's base `values.yaml`. The `helm` skill deliberately ships base defaults that are empty or off — `resources: {}`, `autoscaling.enabled: false`, `pdb.enabled: false`, commented-out production shapes — so the chart stays deployable on a bare kind cluster. Judging those as findings means reporting the chart's design as a defect, and it's the most common false positive here.

What that means per item: a value is a finding when it's still absent **after** `values.yaml → defaults/ → <env>/` have all been applied. If something is missing, name the layer it should be set in — usually `defaults/values.yaml` for operational baselines, `<env>/values.yaml` for anything that legitimately differs per environment.

## How to structure feedback

1. **Lead with blockers.** Things that are unsafe, will lose data, or will break under load. Group them together at the top.
2. **Then suggestions.** Style, label hygiene, "consider this".
3. **Be concrete.** Cite the file and the field. "Missing resource limits on `containers[0]` in `templates/deployment.yaml`" is actionable; "consider resource limits" isn't.
4. **Distinguish rules from preferences.** If something is a hard rule (no root containers in prod), say so. If it's a judgment call, say that too — and explain the trade-off rather than just asserting the preference.

## Checklist

Walk this for each workload resource. Pull in `resource-standards.md` for the actual standards behind each item.

### Security — blocker tier
- [ ] `runAsNonRoot: true` (or pod runs a known non-root image and the image enforces it)
- [ ] `runAsUser` is non-zero — and `runAsUser: 0` is never set explicitly
- [ ] `allowPrivilegeEscalation: false` on every container
- [ ] `capabilities.drop: [ALL]` — with explicit `add:` only when justified
- [ ] No `privileged: true`
- [ ] No `hostNetwork`, `hostPID`, `hostIPC`
- [ ] No `hostPath` volumes (or, if present, a comment explaining why)
- [ ] `automountServiceAccountToken: false` unless the workload calls the API server
- [ ] No literal credentials in `env`, `data`, or anywhere else — Secrets come from ExternalSecrets

### Resources — blocker tier
- [ ] Every container (including init and sidecars) has `requests`, and a memory `limit`
- [ ] Memory `limit` ≈ memory `request` (within ~25%)
- [ ] A missing **CPU** limit is only a finding if it looks accidental — omitting it to avoid throttling is legitimate for latency-sensitive services; ask rather than assert
- [ ] CPU request is realistic — not `1m` for a real workload, not `4` for a stub
- [ ] No `resources: {}` in the **rendered** manifest (in a base `values.yaml` it's the expected default — see above)

### Image hygiene — blocker tier
- [ ] No `:latest` tag in committed manifests
- [ ] No `image:` lines without a tag at all (defaults to `:latest`)

### Probes
- [ ] HTTP services have `readinessProbe` (otherwise Service load-balances to not-yet-ready pods)
- [ ] Long-running services have `livenessProbe`
- [ ] Liveness uses different/looser thresholds than readiness, or it's clearly intentional that they match
- [ ] Slow-starting apps have `startupProbe`, not just a long `initialDelaySeconds` on liveness
- [ ] Probes target an actual health endpoint, not a generic TCP check, when the protocol is HTTP

### High availability (only when `replicas >= 2`)
- [ ] `PodDisruptionBudget` exists for the workload
- [ ] Anti-affinity or `topologySpreadConstraints` for spreading replicas across nodes/zones
- [ ] Selector labels are stable (no version label in selector)

### Storage
- [ ] PVCs specify `storageClassName` explicitly
- [ ] StatefulSets use `volumeClaimTemplates`, not pre-created PVCs referenced by name
- [ ] PVC sizes look realistic for the workload
- [ ] `accessModes` matches what the storage class supports

### Networking
- [ ] Service `type` is the most restrictive that works (ClusterIP > NodePort > LoadBalancer)
- [ ] Service `selector` actually matches pod labels (a classic miss)
- [ ] If a `NetworkPolicy` exists, it covers both ingress and egress (most teams forget egress)
- [ ] DNS records are managed by `external-dns` annotations, not commit-and-forget A records

### Labels and selectors
- [ ] Recommended labels (`app.kubernetes.io/name`, `instance`, `version`, `component`, `part-of`, `managed-by`) are present — produced by the chart's labels helper, not hand-written per template (the `helm` skill owns the helper)
- [ ] Every workload has a unique `app.kubernetes.io/component`; dependent Services/PDBs/Monitors select on the same value
- [ ] `spec.selector.matchLabels` is a subset of `metadata.labels`
- [ ] No version-label in `selector` (selectors are immutable)
- [ ] No bare-key label duplicating an `app.kubernetes.io/*` key — one vocabulary (the `tagging` skill owns the boundary)

### GitOps integration
- [ ] No `kubectl apply` instructions in the README that should go through ArgoCD/Flux
- [ ] If ArgoCD: sync wave annotation is correct (CRDs and prerequisites lower than dependents)
- [ ] No imperative resources (`Job` with no idempotency, `kubectl create` instructions)

### Operator-managed workloads
- [ ] Database/queue/cache is using the operator CRD, not a hand-rolled StatefulSet
- [ ] CRD apiVersion matches the operator version installed in the cluster
- [ ] Backup configuration exists for stateful operators (CNPG `Backup`, etc.)

## Patterns that warrant deeper review

If you spot any of these, the workload likely has more issues than the checklist will catch — slow down and read the full manifest carefully.

- A `Deployment` for a database, message queue, or anything with `volumeMounts` that look stateful
- `replicas:` that's been bumped without adding a PDB
- Sidecar containers without their own resource limits
- A `securityContext` block that exists but only sets one or two fields (suggests it was copy-pasted incompletely)
- A service mesh sidecar (Istio, Linkerd) without corresponding probe rewrites — probes get blocked by mTLS otherwise
- Any HPA without resource requests on the target pods (HPA can't compute utilization)

## Output template

When delivering a review, this format works well:

```
## Blockers

1. [file:line] short description
   <one or two sentences on why it matters and how to fix>

2. ...

## Suggestions

- [file:line] description
- ...

## Looks good

- (optional) list things that are well-handled, especially when reviewing someone's work
```

If everything checks out, say so directly — don't pad with imaginary issues.
