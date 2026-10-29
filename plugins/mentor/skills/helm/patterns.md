# Helm — Patterns & Requirements

Recurring template patterns and operational requirements for Helm charts. Companion to `SKILL.md` (foundations). For Kubernetes resource-level standards see the `kubernetes` skill's `resource-standards.md`.

---

## Image construction

The image reference must support three cases: tag only, digest only, and tag+digest. The tag+digest form (`repo:tag@sha256:...`) gives you human-readable tags in `kubectl get pods` while guaranteeing immutability via the digest.

### Values shape

```yaml
image:
  repository: ""
  tag: ""                # e.g., "v1.4.2" or commit SHA
  digest: ""             # e.g., "sha256:abc123..." — takes precedence when set
  pullPolicy: IfNotPresent
```

### Helper

Add an image helper to `_helpers.tpl`:

```gotmpl
{{- define "my-chart.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- if .Values.image.digest -}}
  {{- printf "%s:%s@%s" .Values.image.repository $tag .Values.image.digest -}}
{{- else -}}
  {{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}
{{- end -}}
```

### Usage in templates

```gotmpl
image: {{ include "my-chart.image" . }}
imagePullPolicy: {{ .Values.image.pullPolicy }}
```

Rendered output examples:
- Tag only: `ghcr.io/example/myapp:v1.4.2`
- Tag + digest: `ghcr.io/example/myapp:v1.4.2@sha256:abc123...`
- Digest only (tag empty): `ghcr.io/example/myapp:1.0.0@sha256:abc123...` (falls back to `appVersion`)

---

## ExternalSecret toggle pattern

Every credential block in `values.yaml` includes an `externalSecret` and a `vault` sub-key. Three modes in priority order: `<cred>.vault.enable` > `<cred>.externalSecret.enable` > chart-internal inline values. For the full template chain — values shape, `secrets.yaml` guard, `secretKeyRef` three-way branch, credential file mounts — see `postgres.md` (database) and `kafka.md` (SASL).

### Multi-secret naming convention

When a chart has multiple credential blocks (database, kafka, node RPC, etc.), each produces one Secret and one set of env vars. The naming convention:

| Values block | Secret suffix | Env var prefix |
|---|---|---|
| `database` | `{{ fullname }}-db` | `DB_*` or `POSTGRES_*` |
| `kafka` | `{{ fullname }}-kafka` | `KAFKA_*` |
| `node` | `{{ fullname }}-node` | `NODE_*` |
| `auth` | `{{ fullname }}-auth` | `AUTH_*` or service-specific |

The Secret suffix should match (or abbreviate) the values block name. Keep this mapping consistent across charts so ops can predict the Secret name from the values file.

### Secret replication via extraObjects

When a Secret exists in another namespace, use the mittwald replicator annotation injected through `extraObjects` in the env overlay:

```yaml
# dev/eth.yaml
extraObjects:
  - apiVersion: v1
    kind: Secret
    metadata:
      name: my-kafka-credentials
      annotations:
        replicator.v1.mittwald.de/replicate-from: kafka/my-kafka-credentials
    type: Opaque
```

### ExternalSecret creation via extraObjects

When the chart's env overlay needs to provision an `ExternalSecret` resource (e.g., pulling from AWS Secrets Manager), inject it through `extraObjects`:

```yaml
# dev/eth.yaml
extraObjects:
  - apiVersion: external-secrets.io/v1
    kind: ExternalSecret
    metadata:
      name: my-credentials
    spec:
      refreshInterval: 10m
      secretStoreRef:
        kind: ClusterSecretStore
        name: aws-secrets-manager
      target:
        name: my-credentials
        creationPolicy: Owner
        deletionPolicy: Retain
        template:
          type: Opaque
      data:
        - secretKey: url
          remoteRef:
            key: /foo/bar
            property: url
```

### Vault dynamic credentials — self-contained generator

When `<cred>.vault.enable: true`, the `VaultDynamicSecret` generator and the `ExternalSecret` that consumes it render together under a **single guard** in `secrets.yaml`. No separate `SecretStore` is needed — `VaultDynamicSecret` carries its own auth config inline. ESO authenticates with Vault using the chart's ServiceAccount (name + `{{ .Release.Namespace }}`) via the Kubernetes `TokenRequest` API — pod `automountServiceAccountToken` is unaffected.

The generator name uses a `<backend>-generator` suffix to distinguish it from the Secret it produces. The `ExternalSecret` target name is identical to the chart-internal Secret name, so Deployment wiring (volumeMount + secretKeyRef) is unchanged across all three credential modes.

The chart-level `vault.mountPath` and `vault.role` supply the Kubernetes auth config shared by all credential blocks. The Vault role must have `bound_service_account_names` and `bound_service_account_namespaces` configured to match this chart's SA name and namespace. For charts with multiple credential blocks, each gets its own generator + ExternalSecret pair under its own guard.

For the complete VaultDynamicSecret + ExternalSecret templates, see `postgres.md` and `kafka.md`.

---

## Credential file mounts

All credential Secrets — regardless of source mode (chart-internal, ExternalSecret, or Vault dynamic) — are **always** mounted as files at `/var/run/secrets/<type>/`. This gives applications a consistent file path across modes, pairs cleanly with `readOnlyRootFilesystem: true`, and lets secrets-file libraries (e.g. Spring Cloud Vault, Consul Template consumers) work without env var plumbing.

Add `mountPath` to each credential block in `values.yaml`:

```yaml
database:
  mountPath: /var/run/secrets/db    # produces /var/run/secrets/db/<key>
kafka:
  sasl:
    mountPath: /var/run/secrets/kafka
```

In the Deployment template, credential volumes are rendered **unconditionally** — hard-coded before the user-defined pass-through `volumes`/`volumeMounts`:

```gotmpl
          volumeMounts:
            - name: db-credentials
              mountPath: {{ .Values.database.mountPath | default "/var/run/secrets/db" }}
              readOnly: true
            {{- with .Values.volumeMounts }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
      volumes:
        - name: db-credentials
          secret:
            secretName: {{ include "my-chart.fullname" . }}-db
        {{- with .Values.volumes }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
```

The Secret name (`{{ fullname }}-db`) is stable across all three modes — the mount wiring is identical regardless of how the Secret was populated. Key names inside the mounted files vary by mode:

| Mode | Keys available as files |
|---|---|
| Chart-internal | `username`, `password` |
| ExternalSecret | whatever keys the upstream store provides — map them to `username`/`password` |
| Vault dynamic | `database.vault.usernameKey`, `database.vault.passwordKey` (both default to `username`/`password`) |

**The key names must be identical across all three modes**, or the mounted filename — and therefore
the app's `DB_USERNAME_FILE` — changes with the credential source, which defeats the whole point of
having three interchangeable modes. Vault's `database/creds/<role>` returns `username`, so that is
the spelling everything else adopts.

Env vars (`secretKeyRef`) co-exist with the file mount: the mount is unconditional, the env vars are
added when the application reads env rather than files (the `secrets` skill, *Files always; env only
where the code actually reads env*). Both resolve to the same key in the same Secret.

---

## extraObjects — arbitrary manifest escape hatch

In `_helpers.tpl` (the `render` helper):
```gotmpl
{{- define "my-chart.render" -}}
  {{- if typeIs "string" .value -}}
    {{- tpl .value .context }}
  {{- else -}}
    {{- tpl (.value | toYaml) .context }}
  {{- end -}}
{{- end -}}
```

In `templates/extra-manifests.yaml`:
```gotmpl
{{- range .Values.extraObjects }}
---
{{ include "my-chart.render" (dict "value" . "context" $) }}
{{- end }}
```

The `tpl` call allows users to embed Helm expressions (e.g., `{{ include "my-chart.fullname" . }}`) inside their extra objects. Common uses: ExternalSecrets, replicated Secrets, VaultDynamicSecrets, NetworkPolicies, any resource the base chart doesn't template.

---

## ConfigMap

Non-secret configuration the app reads from a file or env. Guard the whole resource with `config.enabled` so charts without external config render nothing (and the checksum line stays conditional):

```gotmpl
{{- if .Values.config.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
data:
  {{- toYaml .Values.config.data | nindent 2 }}
{{- end }}
```

Values shape:

```yaml
config:
  enabled: false
  data: {}
#   enabled: true
#   data:
#     APP_MODE: "production"
#     app.conf: |
#       key = value
```

Mount it as files (pairs with `readOnlyRootFilesystem`) or load via `envFrom.configMapRef`. Secret values never go here — those belong in `secrets.yaml` / ExternalSecret. A multi-component chart puts each component's ConfigMap under its folder (`frontend/configmap.yaml`) and checksums it in that component's pod template only.

---

## Config & Secret checksum annotations

Force a rolling restart when a mounted ConfigMap or Secret changes by checksumming each into a pod-template annotation. Use a distinct key per source — `checksum/config` for the ConfigMap, `checksum/secret` for the Secret:

```gotmpl
spec:
  template:
    metadata:
      annotations:
        {{- if .Values.config.enabled }}
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
        {{- end }}
        checksum/secret: {{ include (print $.Template.BasePath "/secrets.yaml") . | sha256sum }}
        {{- with .Values.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
```

- **Guard each `include` with the same condition that renders the file.** `include` on a template that doesn't exist errors at render time, so a conditional ConfigMap (`config.enabled`) needs an equally conditional checksum line. `secrets.yaml` is rendered by every chart here, so its checksum is unconditional.
- **Per workload, checksum only what that workload mounts.** In a multi-component chart the frontend Deployment checksums `frontend/configmap.yaml`; the backend checksums its own. Don't hash every config file into every pod — an unrelated change would needlessly churn pods that don't consume it.
- **Put the checksums above the `podAnnotations` merge** so a user-supplied annotation can't accidentally clobber them.
- Distinct keys make `kubectl describe pod` show *which* source changed.

This complements the reloader annotation:
- **Checksum** — restart when the chart's own rendered `configmap.yaml`/`secrets.yaml` changes (values change between deploys).
- **Reloader** (`reloader.stakater.com/auto: "true"`) — restart when an external Secret/ConfigMap is updated in-place (credential rotation, ExternalSecret refresh).

Use both. Checksums go in the template; reloader goes in `defaults/values.yaml` via `podAnnotations`.

---

## Downward API metadata injection

Standard env var block for every container. Provides runtime context for logging, metrics labels, and resource-aware tuning:

```gotmpl
- name: NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: POD_IP
  valueFrom:
    fieldRef:
      fieldPath: status.podIP
- name: HOST_IP
  valueFrom:
    fieldRef:
      fieldPath: status.hostIP
- name: NODE_NAME
  valueFrom:
    fieldRef:
      fieldPath: spec.nodeName
- name: CPU_REQUEST
  valueFrom:
    resourceFieldRef:
      divisor: 1m
      resource: requests.cpu
- name: CPU_LIMIT
  valueFrom:
    resourceFieldRef:
      divisor: 1m
      resource: limits.cpu
- name: MEM_REQUEST
  valueFrom:
    resourceFieldRef:
      divisor: 1Mi
      resource: requests.memory
- name: MEM_LIMIT
  valueFrom:
    resourceFieldRef:
      divisor: 1Mi
      resource: limits.memory
```

Include this block in every Deployment, CronJob, and Job template. The resource fields let applications self-tune (thread pools, buffer sizes, GC settings) based on their actual allocation.

---

## Environment variable ordering

Maintain a consistent ordering in the `env:` block across all templates:

1. **Downward API** — NAMESPACE, POD_NAME, POD_IP, HOST_IP, NODE_NAME, CPU/MEM request/limit
2. **Plain config values** — non-secret configuration set via `value:` (chain ID, batch sizes, topic names, feature flags)
3. **Secret references** — credentials via `secretKeyRef`, grouped by resource block (all DB_* together, all KAFKA_* together)

This ordering makes templates scannable — metadata at the top, config in the middle, secrets at the bottom.

---

## Scheduling fields

Every Deployment, StatefulSet, and CronJob template must include all five scheduling fields. Use `{{- with }}` + `toYaml` for list/map types and `{{- if }}` for scalars:

```gotmpl
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.topologySpreadConstraints }}
      topologySpreadConstraints:
        {{- tpl (toYaml .) $ | nindent 8 }}
      {{- end }}
      {{- if .Values.priorityClassName }}
      priorityClassName: {{ .Values.priorityClassName | quote }}
      {{- end }}
```

`topologySpreadConstraints` uses `tpl` so label selectors can reference chart helpers (e.g., `{{ include "my-chart.selectorLabels" . }}`). The other fields use plain `toYaml`.

All five fields must have corresponding empty defaults in `values.yaml`:

```yaml
nodeSelector: {}
affinity: {}
tolerations: []
topologySpreadConstraints: []
priorityClassName: ""
```

---

## Volumes and volumeMounts pass-through

Volumes and volumeMounts are defined in values and passed through with `toYaml`. The `defaults/values.yaml` layer typically adds the `/tmp` emptyDir; env overlays can add more:

```gotmpl
          {{- with .Values.volumeMounts }}
          volumeMounts:
            {{- toYaml . | nindent 12 }}
          {{- end }}
      # ... (at pod spec level)
      {{- with .Values.volumes }}
      volumes:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

The base `values.yaml` defines empty lists; `defaults/values.yaml` provides the operational baseline:

```yaml
# values.yaml
volumes: []
volumeMounts: []

# defaults/values.yaml
volumes:
  - emptyDir: {}
    name: tmp
volumeMounts:
  - name: tmp
    mountPath: /tmp
```

---

## Deployment strategy

### RollingUpdate (default — stateless HTTP services)

```yaml
strategy:
  rollingUpdate:
    maxSurge: 25%
    maxUnavailable: 25%
  type: RollingUpdate
```

Use for stateless workloads where multiple versions can coexist during deploy.

### Recreate (single-writer consumers)

```yaml
strategy:
  type: Recreate
```

Use when the workload cannot run two instances simultaneously — Kafka consumers with a single partition assignment, workers with exclusive locks, or processes that hold file locks. All old pods are terminated before new ones start.

Values shape (optional — only expose if the chart supports both):

```yaml
strategy:
  type: RollingUpdate
# strategy:
#   type: Recreate
```

---

## Liveness probe patterns

### HTTP services

Use named ports (`http`, `metrics`) in all `httpGet` probes. For standard values and anti-patterns (liveness ≠ readiness thresholds, slow-start `startupProbe`, TCP vs HTTP) see `kubernetes/resource-standards.md` — the canonical defaults apply here too.

### Non-HTTP workers (heartbeat file)

For background consumers, producers, and other non-HTTP workloads that have no endpoint to probe. The application writes a Unix timestamp to a heartbeat file periodically; the probe checks staleness:

```gotmpl
livenessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - test $(( $(date +%s) - $(cat /tmp/heartbeat) )) -lt {{ .Values.livenessProbe.maxAgeSeconds }}
  initialDelaySeconds: {{ .Values.livenessProbe.delays.initialDelaySeconds }}
  periodSeconds: {{ .Values.livenessProbe.delays.periodSeconds }}
  timeoutSeconds: {{ .Values.livenessProbe.delays.timeoutSeconds }}
  failureThreshold: {{ .Values.livenessProbe.delays.failureThreshold }}
```

Values shape:
```yaml
livenessProbe:
  maxAgeSeconds: 300
  delays:
    initialDelaySeconds: 10
    periodSeconds: 15
    timeoutSeconds: 10
    failureThreshold: 3
```

The heartbeat file (`/tmp/heartbeat`) requires a writable `/tmp` — pair with an `emptyDir` volume (see defaults layer).

---

## Defaults layer — operational baseline

`defaults/values.yaml` contains everything true for every cluster deployment. This is the canonical shape:

```yaml
imagePullSecrets:
  - name: registry-credentials

image:
  tag: ""    # set by CI — commit SHA or release tag
  digest: ""

podAnnotations:
  reloader.stakater.com/auto: "true"

podLabels:
  function: app
  env: dev
  region: ""
  provider: ""
  owner: ""

podSecurityContext:
  fsGroup: 65532                 # = the Dockerfile's USER — see the `dockerfile` skill
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault

securityContext:
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  runAsNonRoot: true
  runAsUser: 65532               # never decided here; mirrors the image
  runAsGroup: 65532
```
---

## Deployment template skeleton

The canonical Deployment template wiring everything together. Adapt for your workload — this is the reference structure, not a copy-paste target:

```gotmpl
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "my-chart.selectorLabels" . | nindent 6 }}
  {{- with .Values.strategy }}
  strategy:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  template:
    metadata:
      annotations:
        {{- if .Values.config.enabled }}
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
        {{- end }}
        checksum/secret: {{ include (print $.Template.BasePath "/secrets.yaml") . | sha256sum }}
        {{- with .Values.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      labels:
        {{- include "my-chart.labels" . | nindent 8 }}
        {{- with .Values.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      serviceAccountName: {{ include "my-chart.serviceAccountName" . }}
      {{- with .Values.podSecurityContext }}
      securityContext:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .Chart.Name }}
          image: {{ include "my-chart.image" . }}
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          command: [...]
          {{- with .Values.securityContext }}
          securityContext:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          env:
            # 1. Downward API metadata
            - name: NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            # ... (full downward API block — see section above)

            # 2. Plain config values
            - name: ENV
              value: {{ .Values.config.env | quote }}

            # 3. Secret references — see postgres.md and kafka.md for the three-way secretKeyRef pattern
          {{- with .Values.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          # Probes — HTTP depending on workload type
          livenessProbe:
            httpGet:
              path: /health
              port: http
          readinessProbe:
            httpGet:
              path: /ready
              port: http
          volumeMounts:
            - name: db-credentials
              mountPath: {{ .Values.database.mountPath | default "/var/run/secrets/db" }}
              readOnly: true
            {{- with .Values.volumeMounts }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
      volumes:
        - name: db-credentials
          secret:
            secretName: {{ include "my-chart.fullname" . }}-db
        {{- with .Values.volumes }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.topologySpreadConstraints }}
      topologySpreadConstraints:
        {{- tpl (toYaml .) $ | nindent 8 }}
      {{- end }}
      {{- if .Values.priorityClassName }}
      priorityClassName: {{ .Values.priorityClassName | quote }}
      {{- end }}
```

Key points:
- `replicas` guarded by `autoscaling.enabled` — when HPA is active, it controls replica count
- Config checksum annotation **before** `podAnnotations` merge so user annotations can override
- Labels include both chart labels and user `podLabels`
- Env vars follow the ordering convention: downward API → config → secrets
- Image uses the `my-chart.image` helper for tag+digest support
- Set a unique `app.kubernetes.io/component` (see *Component label — required on every workload*). This skeleton uses plain `labels`/`selectorLabels` for brevity; switch to `componentLabels`/`componentSelectorLabels` whenever the chart renders more than one workload

---

## Service template

```gotmpl
apiVersion: v1
kind: Service
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "my-chart.selectorLabels" . | nindent 4 }}
```

Values shape:
```yaml
service:
  type: ClusterIP
  port: 8080
```

Use named ports (`http`, `metrics`, `grpc`) — they're referenced by probes, ServiceMonitors, and HTTPRoutes. Only create a Service for workloads that receive traffic (HTTP APIs, gRPC services). Background consumers/producers don't need one.

---

## Component label — required on every workload

Every workload a chart renders — `Deployment`, `StatefulSet`, `CronJob`, and `Job` (including Helm-hook migration Jobs) — must carry a **unique** `app.kubernetes.io/component`. Label even a single-workload chart (e.g. `server`); it becomes mandatory the moment a chart has more than one workload.

Two reasons:
1. **Selector isolation.** `selectorLabels` (name + instance) is identical for every workload in a chart. Without a distinguishing label, two Deployments — or a Deployment alongside a Job — have overlapping selectors: a controller can adopt another workload's pods, and Services/PDBs/Monitors match the wrong pods. A per-workload component label *in the selector* makes each workload select only its own pods.
2. **Operability.** `kubectl get pods -l app.kubernetes.io/component=migrate`, per-component dashboards, NetworkPolicy peers, and cost allocation all key off it.

Use the `componentLabels` / `componentSelectorLabels` helpers (defined under *Multi-deployment charts* below) in every workload, passing a name unique within the chart:

```gotmpl
# deployment.yaml — component: "server"
metadata:
  labels:
    {{- include "my-chart.componentLabels" (dict "root" . "component" "server") | nindent 4 }}
spec:
  selector:
    matchLabels:
      {{- include "my-chart.componentSelectorLabels" (dict "root" . "component" "server") | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "my-chart.componentLabels" (dict "root" . "component" "server") | nindent 8 }}
```

Assign a distinct value per object — e.g. `server`, `worker`, `migrate`, `report-cron`.

Rules:
- **Unique per workload** within the chart — never reuse a value across two objects.
- **Deployments / StatefulSets:** put the component label in the selector (`componentSelectorLabels`). Selectors are immutable — set it from day one; adding it to an existing workload forces a delete/recreate.
- **Jobs / CronJobs:** set it in `metadata.labels` and the pod-template labels, but **not** in a manual selector — Jobs generate their own controller-owned selector and overriding it is unsupported.
- **Dependent objects must match:** a Service, PDB, ServiceMonitor, or NetworkPolicy targeting one workload must include the same component label in its selector, or it silently matches the wrong (or zero) pods.

---

## Multi-deployment charts

When a single chart deploys multiple components (frontend + backend + worker, or per-tenant deployments), organize templates by component and use annotations to distinguish them.

### When to use multi-deployment vs separate charts

| Pattern | Use when |
|---------|----------|
| **Multi-deployment single chart** | Components share lifecycle, values, and version. Deploy/rollback as one unit. Examples: frontend + backend + worker in a monorepo. |
| **Separate charts** | Components have independent lifecycles, separate teams, or different release cadences. Compose via ArgoCD ApplicationSet. |

### Folder structure

```
my-chart/
├── templates/
│   ├── _helpers.tpl
│   ├── frontend/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── hpa.yaml
│   │   └── httproute.yaml
│   ├── backend/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── hpa.yaml
│   │   └── httproute.yaml
│   ├── worker/
│   │   └── deployment.yaml
│   ├── shared/
│   │   ├── secrets.yaml
│   │   ├── serviceaccount.yaml
│   │   └── pdb.yaml
│   └── NOTES.txt
```

Group by component when each has multiple resources. Use `shared/` for resources used by all components (ServiceAccount, shared Secrets, NetworkPolicy).

### Component-scoped helpers

Extend `_helpers.tpl` with component-aware helpers:

```gotmpl
{{- define "my-chart.componentName" -}}
{{- $component := .component -}}
{{- if $component -}}
{{- printf "%s-%s" (include "my-chart.fullname" .root) $component | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- include "my-chart.fullname" .root -}}
{{- end -}}
{{- end -}}

{{- define "my-chart.componentLabels" -}}
{{ include "my-chart.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "my-chart.componentSelectorLabels" -}}
{{ include "my-chart.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}
```

Usage in templates:

```gotmpl
# frontend/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "my-chart.componentName" (dict "root" . "component" "frontend") }}
  labels:
    {{- include "my-chart.componentLabels" (dict "root" . "component" "frontend") | nindent 4 }}
    {{- with .Values.frontend.podLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  selector:
    matchLabels:
      {{- include "my-chart.componentSelectorLabels" (dict "root" . "component" "frontend") | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "my-chart.componentLabels" (dict "root" . "component" "frontend") | nindent 8 }}
        {{- with .Values.frontend.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      annotations:
        {{- with .Values.frontend.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
```

### Component label conventions

Standard labels for multi-component charts:

```yaml
labels:
  role: web | worker | cron | infra | data
  component-type: frontend | backend | api | consumer | producer | sidecar
  tier: presentation | application | data | cache
```

These labels help with:
- Filtering in dashboards and log aggregation (`kubectl get pods -l role=web`)
- Network policy rules (`role: web` can receive ingress, `role: worker` cannot)
- Cost allocation and chargeback
- Automated security scanning (different rules for `tier: presentation` vs `tier: data`)
- Label selectors in monitoring, backup policies, and other controllers

Place them in both `metadata.labels` (Deployment level) and `spec.template.metadata.labels` (Pod level) so they're available for selection at both the workload and pod level.

### Values structure for multiple components

```yaml
# Global settings shared by all components
image:
  repository: ghcr.io/example/myapp
  pullPolicy: IfNotPresent

imagePullSecrets:
  - name: registry-credentials

# Component-specific overrides
frontend:
  enabled: true
  replicaCount: 2
  image:
    tag: "v1.4.2"
  service:
    type: ClusterIP
    port: 3000
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
  podLabels:
    role: web
    component-type: frontend
    tier: presentation

backend:
  enabled: true
  replicaCount: 3
  image:
    tag: "v1.4.2"
  service:
    type: ClusterIP
    port: 8080
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 20
  podLabels:
    role: web
    component-type: backend
    tier: application

worker:
  enabled: true
  replicaCount: 5
  image:
    tag: "v1.4.2"
  service:
    enabled: false  # workers don't serve traffic
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
  podLabels:
    role: worker
    component-type: consumer
    tier: application

# Shared configuration
database:
  host: postgres.default.svc.cluster.local
  port: "5432"
  externalSecret:
    enable: true
    name: my-app-db-credentials
```

### Component image helper

When components use different images or tags, extend the image helper:

```gotmpl
{{- define "my-chart.componentImage" -}}
{{- $component := .component -}}
{{- $componentConfig := index .root.Values $component -}}
{{- $globalImage := .root.Values.image -}}
{{- $repository := $componentConfig.image.repository | default $globalImage.repository -}}
{{- $tag := $componentConfig.image.tag | default $globalImage.tag | default .root.Chart.AppVersion -}}
{{- $digest := $componentConfig.image.digest | default $globalImage.digest -}}
{{- if $digest -}}
  {{- printf "%s:%s@%s" $repository $tag $digest -}}
{{- else -}}
  {{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end -}}
```

Usage:

```gotmpl
image: {{ include "my-chart.componentImage" (dict "root" . "component" "frontend") }}
```

### Disabling components

Guard each component's templates with an `enabled` flag:

```gotmpl
# frontend/deployment.yaml
{{- if .Values.frontend.enabled }}
apiVersion: apps/v1
kind: Deployment
...
{{- end }}
```

This allows per-environment component control:

```yaml
# dev/values.yaml
frontend:
  enabled: true
  replicaCount: 1

backend:
  enabled: true
  replicaCount: 1

worker:
  enabled: false  # disabled in dev
```

### Iteration pattern for homogeneous components

When deploying N identical components with different config (per-tenant, per-chain), use iteration instead of folders:

```gotmpl
# templates/tenant-deployments.yaml
{{- range $tenant, $config := .Values.tenants }}
{{- if $config.enabled }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "my-chart.fullname" $ }}-{{ $tenant }}
  labels:
    {{- include "my-chart.labels" $ | nindent 4 }}
    app.kubernetes.io/component: tenant
    tenant: {{ $tenant }}
    role: worker
    component-type: consumer
spec:
  replicas: {{ $config.replicaCount }}
  selector:
    matchLabels:
      {{- include "my-chart.selectorLabels" $ | nindent 6 }}
      tenant: {{ $tenant }}
  template:
    metadata:
      labels:
        {{- include "my-chart.labels" $ | nindent 8 }}
        tenant: {{ $tenant }}
        role: worker
        component-type: consumer
    spec:
      containers:
        - name: processor
          image: {{ include "my-chart.image" $ }}
          env:
            - name: TENANT_ID
              value: {{ $tenant | quote }}
            - name: TENANT_CONFIG
              value: {{ $config.endpoint | quote }}
          resources:
            {{- toYaml $config.resources | nindent 12 }}
{{- end }}
{{- end }}
```

Values:

```yaml
tenants:
  acme:
    enabled: true
    replicaCount: 2
    endpoint: "https://acme.example.com"
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
  globex:
    enabled: true
    replicaCount: 3
    endpoint: "https://globex.example.com"
    resources:
      requests:
        cpu: 200m
        memory: 256Mi
  initech:
    enabled: false  # disabled tenant
```

**Important:** Use `$` to reference the root context inside `range`. `.` inside the loop is the current iteration value.

### NOTES.txt for multi-component charts

Show status for each enabled component:

```gotmpl
{{- $fullName := include "my-chart.fullname" . -}}
Multi-component deployment: {{ $fullName }}

Enabled components:
{{- if .Values.frontend.enabled }}
- Frontend: {{ $fullName }}-frontend
  Port: {{ .Values.frontend.service.port }}
{{- end }}
{{- if .Values.backend.enabled }}
- Backend: {{ $fullName }}-backend
  Port: {{ .Values.backend.service.port }}
{{- end }}
{{- if .Values.worker.enabled }}
- Worker: {{ $fullName }}-worker (no service)
{{- end }}

Check status:
  kubectl get pods -l app.kubernetes.io/instance={{ .Release.Name }} -n {{ .Release.Namespace }}

View frontend logs:
  kubectl logs -l app.kubernetes.io/instance={{ .Release.Name }},app.kubernetes.io/component=frontend -n {{ .Release.Namespace }}
```

---

## Workload variants

### Deployment (default)

The standard workload type. Values include `replicaCount`, `service`, `ingress`/`httpRoute`, `autoscaling`, `pdb`, `metrics`. See the deployment template skeleton above.

### CronJob

For periodic batch workloads (reconcilers, cleanup jobs, reports). Different values shape — no `replicaCount`, `service`, `ingress`, `autoscaling`, `pdb`, or `metrics`:

```yaml
cron:
  schedule: "0 0,12 * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 2
  activeDeadlineSeconds: 1800
```

Template skeleton:
```gotmpl
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  schedule: {{ .Values.cron.schedule | quote }}
  concurrencyPolicy: {{ .Values.cron.concurrencyPolicy }}
  successfulJobsHistoryLimit: {{ .Values.cron.successfulJobsHistoryLimit }}
  failedJobsHistoryLimit: {{ .Values.cron.failedJobsHistoryLimit }}
  jobTemplate:
    spec:
      {{- if .Values.cron.activeDeadlineSeconds }}
      activeDeadlineSeconds: {{ .Values.cron.activeDeadlineSeconds }}
      {{- end }}
      backoffLimit: 1
      template:
        metadata:
          labels:
            {{- include "my-chart.labels" . | nindent 12 }}
            {{- with .Values.podLabels }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
          annotations:
            {{- if .Values.config.enabled }}
            checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
            {{- end }}
            checksum/secret: {{ include (print $.Template.BasePath "/secrets.yaml") . | sha256sum }}
            {{- with .Values.podAnnotations }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
        spec:
          restartPolicy: OnFailure
          {{- with .Values.imagePullSecrets }}
          imagePullSecrets:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          serviceAccountName: {{ include "my-chart.serviceAccountName" . }}
          {{- with .Values.podSecurityContext }}
          securityContext:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          containers:
            - name: {{ .Chart.Name }}
              image: {{ include "my-chart.image" . }}
              imagePullPolicy: {{ .Values.image.pullPolicy }}
              command: [...]
              {{- with .Values.securityContext }}
              securityContext:
                {{- toYaml . | nindent 16 }}
              {{- end }}
              {{- with .Values.resources }}
              resources:
                {{- toYaml . | nindent 16 }}
              {{- end }}
              env:
                # ... downward API + config env vars + secretKeyRef blocks
              {{- with .Values.volumeMounts }}
              volumeMounts:
                {{- toYaml . | nindent 16 }}
              {{- end }}
          {{- with .Values.volumes }}
          volumes:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.nodeSelector }}
          nodeSelector:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.affinity }}
          affinity:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.tolerations }}
          tolerations:
            {{- toYaml . | nindent 12 }}
          {{- end }}
```

Set a unique `app.kubernetes.io/component` (e.g. `report-cron`) on the CronJob `metadata.labels` and the `jobTemplate` pod labels — not in a selector (Jobs own their selector). See *Component label — required on every workload*.

For migration Jobs that must run before the application starts, see `postgres.md` — it covers the Helm hook template, admin Secret ordering (weight `-10` before Job at `0`), and the migrate values shape.

---

## Validation patterns for CRD templates

When a chart templates operator CRDs with user-provided lists (topics, users, ACLs), use `required` and `fail` to catch misconfigurations at render time:

### required — mandatory fields

```gotmpl
{{- $cluster := required "Values.clusterName is required" .Values.clusterName -}}

{{- range $t := .Values.topics.list }}
---
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: {{ required "topic.name is required" $t.name | quote }}
  labels:
    strimzi.io/cluster: {{ $cluster | quote }}
spec:
  partitions: {{ default 1 $t.partitions }}
  replicas: {{ default 3 $t.replicas }}
{{- end }}
```

### fail — conditional validation

```gotmpl
{{- range .authorization.acls }}
  {{- if and (ne .resource.type "cluster") (not (hasKey .resource "name")) }}
    {{- fail "acl.resource.name is required for non-cluster resource types" }}
  {{- end }}
{{- end }}
```

Use `required` for single mandatory fields. Use `fail` for cross-field validation where the condition is more complex than a nil check.

---

## Observability — monitoring templates

### PodMonitor

```gotmpl
{{- if and .Values.metrics.enabled .Values.metrics.podMonitor.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
    {{- with .Values.metrics.podMonitor.additionalLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- with .Values.metrics.podMonitor.jobLabel }}
  jobLabel: {{ . }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "my-chart.selectorLabels" . | nindent 6 }}
  podMetricsEndpoints:
    - port: metrics
      interval: {{ .Values.metrics.podMonitor.interval }}
      {{- with .Values.metrics.podMonitor.scrapeTimeout }}
      scrapeTimeout: {{ . }}
      {{- end }}
      honorLabels: {{ .Values.metrics.podMonitor.honorLabels }}
{{- end }}
```

### ServiceMonitor

```gotmpl
{{- if and .Values.metrics.enabled .Values.metrics.serviceMonitor.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
    {{- with .Values.metrics.serviceMonitor.additionalLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  selector:
    matchLabels:
      {{- include "my-chart.selectorLabels" . | nindent 6 }}
  endpoints:
    - port: metrics
      interval: {{ .Values.metrics.serviceMonitor.interval }}
      honorLabels: {{ .Values.metrics.serviceMonitor.honorLabels }}
      {{- with .Values.metrics.serviceMonitor.relabelings }}
      relabelings:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.metrics.serviceMonitor.metricRelabelings }}
      metricRelabelings:
        {{- toYaml . | nindent 8 }}
      {{- end }}
{{- end }}
```

### PrometheusRule

```gotmpl
{{- if and .Values.metrics.enabled .Values.metrics.prometheusRule.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
    {{- with .Values.metrics.prometheusRule.additionalLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  groups:
    - name: {{ include "my-chart.fullname" . }}
      rules:
        {{- toYaml .Values.metrics.prometheusRule.rules | nindent 8 }}
{{- end }}
```

### Values shape for all three

```yaml
metrics:
  enabled: false
  podMonitor:
    enabled: false
    interval: 30s
    scrapeTimeout: ""
    honorLabels: false
    jobLabel: ""
    additionalLabels: {}
  serviceMonitor:
    enabled: false
    interval: 30s
    honorLabels: false
    relabelings: []
    metricRelabelings: []
    additionalLabels: {}
  prometheusRule:
    enabled: false
    additionalLabels: {}
    rules: []
# metrics:
#   enabled: true
#   podMonitor:
#     enabled: true
#     interval: 30s
#     additionalLabels:
#       release: prometheus
#   prometheusRule:
#     enabled: true
#     additionalLabels:
#       release: prometheus
#     rules:
#       - alert: HighErrorRate
#         expr: rate(http_errors_total{job="my-chart"}[5m]) > 0.05
#         for: 10m
#         labels:
#           severity: warning
```

Use `podMonitor` for workloads without a Service (background consumers/producers). Use `serviceMonitor` for workloads with a Service (HTTP APIs). Both are behind `metrics.enabled` as a top-level gate.

---

## HPA template

```gotmpl
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
    {{- with .Values.autoscaling.labels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  {{- with .Values.autoscaling.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "my-chart.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    {{- if .Values.autoscaling.targetCPUUtilizationPercentage }}
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}
    {{- end }}
    {{- if .Values.autoscaling.targetMemoryUtilizationPercentage }}
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: {{ .Values.autoscaling.targetMemoryUtilizationPercentage }}
    {{- end }}
    {{- with .Values.autoscaling.metrics }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  {{- with .Values.autoscaling.behavior }}
  behavior:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
```

The template supports both shorthand (`targetCPUUtilizationPercentage`) and full custom `metrics` and `behavior` blocks. When both are present, they merge — the shorthand CPU/memory metrics come first, followed by any custom metrics.

---

## PDB template

```gotmpl
{{- if .Values.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
    {{- with .Values.pdb.labels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  {{- with .Values.pdb.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- if .Values.pdb.maxUnavailable }}
  maxUnavailable: {{ .Values.pdb.maxUnavailable }}
  {{- else }}
  minAvailable: {{ .Values.pdb.minAvailable | default 1 }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "my-chart.selectorLabels" . | nindent 6 }}
{{- end }}
```

The PDB selector must use the same `selectorLabels` as the Deployment. Don't add extra labels (like `app.kubernetes.io/component`) to the PDB selector unless they're also set on the pod template — a mismatch means the PDB silently protects nothing.

---

## Gateway API — HTTPRoute

For clusters running a Gateway API implementation (Envoy Gateway, Istio, etc.). Alongside or instead of traditional Ingress:

```gotmpl
{{- range $name, $route := .Values.route }}
  {{- if $route.enabled }}
---
apiVersion: {{ $route.apiVersion | default "gateway.networking.k8s.io/v1" }}
kind: {{ $route.kind | default "HTTPRoute" }}
metadata:
  name: {{ include "my-chart.fullname" $ }}{{ if ne $name "main" }}-{{ $name }}{{ end }}
  labels:
    {{- include "my-chart.labels" $ | nindent 4 }}
  {{- with $route.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- with $route.parentRefs }}
  parentRefs:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with $route.hostnames }}
  hostnames:
    {{- tpl (toYaml .) $ | nindent 4 }}
  {{- end }}
  rules:
    {{- range $rule := $route.rules }}
    - backendRefs:
        - group: ""
          kind: Service
          name: {{ $rule.backendRef.name | default (include "my-chart.fullname" $) }}
          port: {{ $rule.backendRef.port | default $.Values.service.port }}
          weight: 1
      {{- with $rule.matches }}
      matches:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with $rule.filters }}
      filters:
        {{- toYaml . | nindent 8 }}
      {{- end }}
    {{- end }}
{{- end }}
{{- end }}
```

Values shape:
```yaml
route:
  main:
    enabled: false
#   enabled: true
#   parentRefs:
#     - name: gateway
#       namespace: envoy-gateway-system
#   hostnames:
#     - "api.example.com"
#   rules:
#     - matches:
#         - path:
#             type: PathPrefix
#             value: /
```

The `range` over `$name, $route` supports multiple named routes per chart (e.g., `main`, `internal`, `admin`). The route named `main` omits the suffix from the resource name.

---

## Operational labels

Define organizational labels in `defaults/values.yaml` via `podLabels`. These are used for cost allocation, filtering in dashboards, and policy enforcement:

```yaml
podLabels:
  function: app          # app, worker, cron, infra
  env: dev               # dev, staging, prod
  region: ""             # cloud region or datacenter
  provider: ""           # cloud provider or hosting
  owner: ""              # team or individual
```

These are distinct from the Kubernetes recommended labels in `_helpers.tpl` (`app.kubernetes.io/*`), which identify the application. Operational labels identify the deployment context.

---

## ServiceAccount template

```gotmpl
{{- if .Values.serviceAccount.create -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "my-chart.serviceAccountName" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
  {{- with .Values.serviceAccount.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
automountServiceAccountToken: {{ .Values.serviceAccount.automount }}
{{- end }}
```

---

## RBAC

Only create RBAC when the workload actually calls the Kubernetes API (leader election, watching ConfigMaps, reconciling CRs). A workload that never talks to the API server needs neither RBAC nor a mounted token — keep `serviceAccount.automount: false`. Don't ship empty Roles "just in case."

`templates/rbac.yaml` — namespaced `Role` by default, `ClusterRole` when `rbac.clusterScope: true`, always bound to the chart's ServiceAccount:

```gotmpl
{{- if .Values.rbac.create }}
{{- $kind := ternary "ClusterRole" "Role" .Values.rbac.clusterScope }}
apiVersion: rbac.authorization.k8s.io/v1
kind: {{ $kind }}
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
rules:
  {{- toYaml .Values.rbac.rules | nindent 2 }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: {{ $kind }}Binding
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: {{ $kind }}
  name: {{ include "my-chart.fullname" . }}
subjects:
  - kind: ServiceAccount
    name: {{ include "my-chart.serviceAccountName" . }}
    namespace: {{ .Release.Namespace }}
{{- end }}
```

Values shape:

```yaml
serviceAccount:
  create: true
  automount: false        # flip to true when rbac.create is true — the pod needs its token

rbac:
  create: false
  clusterScope: false     # true → ClusterRole/ClusterRoleBinding (cluster-wide; use sparingly)
  rules: []
#   create: true
#   rules:
#     - apiGroups: [""]
#       resources: ["configmaps"]
#       verbs: ["get", "list", "watch"]
#     - apiGroups: ["coordination.k8s.io"]
#       resources: ["leases"]
#       verbs: ["get", "create", "update"]
```

Rules of thumb:
- Prefer a namespaced `Role`. Only go cluster-scoped for genuinely cluster-wide resources (nodes, namespaces, CRDs, PVs).
- Least privilege: enumerate explicit `verbs`, never `["*"]`; scope to `resourceNames` where the API allows it.
- When `rbac.create: true`, set `serviceAccount.automount: true` — without the token the granted permissions are unusable. This is the one case where automount is expected (the ServiceAccount default in `SKILL.md` is `false`).

---

## NetworkPolicy

Segment pod traffic with an explicit policy instead of relying on a cluster-wide default-deny you don't control. The pod selector reuses `selectorLabels`; `policyTypes` is derived from which rule sets are present, so you never declare a direction with no rules by accident.

`templates/networkpolicy.yaml`:

```gotmpl
{{- if .Values.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      {{- include "my-chart.selectorLabels" . | nindent 6 }}
  policyTypes:
    {{- if .Values.networkPolicy.ingress }}
    - Ingress
    {{- end }}
    {{- if .Values.networkPolicy.egress }}
    - Egress
    {{- end }}
  {{- with .Values.networkPolicy.ingress }}
  ingress:
    {{- tpl (toYaml .) $ | nindent 4 }}
  {{- end }}
  {{- with .Values.networkPolicy.egress }}
  egress:
    {{- tpl (toYaml .) $ | nindent 4 }}
  {{- end }}
{{- end }}
```

`tpl` wraps the rules so peer selectors can reference chart helpers (e.g. another component's `selectorLabels`).

Values shape:

```yaml
networkPolicy:
  enabled: false
  ingress: []
  egress: []
#   enabled: true
#   ingress:
#     - from:
#         - podSelector:
#             matchLabels:
#               app.kubernetes.io/name: ingress-nginx
#       ports:
#         - port: http            # named container port resolves to targetPort
#   egress:
#     # Always allow DNS first, or every other egress rule silently fails resolution
#     - to:
#         - namespaceSelector: {}
#       ports:
#         - port: 53
#           protocol: UDP
#         - port: 53
#           protocol: TCP
```

Notes:
- **Never block the local loop.** Keep `networkPolicy.enabled: false` in the **base `values.yaml`**, with the real `ingress`/`egress` rules commented as the starting shape. The chart must deploy on a bare `kind` cluster (often with no policy-enforcing CNI) and on `docker-compose` with full connectivity. Turn the policy *on* in `defaults/values.yaml` or the per-env overlay for real clusters — never in the base file. Same goes for any other restrictive or cluster-coupled feature (strict egress, `rbac.clusterScope`, ExternalSecret-only credentials): off in base, on in overlays.
- `enabled: true` with empty `ingress`/`egress` is a **no-op** (no `policyTypes`) — you opt into each direction by adding rules. For a strict "deny all ingress," add a single empty-rule list element or an explicit `policyTypes`.
- **Always include a DNS egress rule** once you restrict egress; otherwise the pod can't resolve any name and every other allow-rule looks broken.
- Prefer `namespaceSelector`/`podSelector` peers over raw `ipBlock` CIDRs — labels survive IP churn.

## Patterns checklist

In addition to the foundations checklist in `SKILL.md`:

- [ ] Image helper supports tag, digest, and tag+digest (`repo:tag@sha256:...`)
- [ ] Credential volumes and volumeMounts rendered unconditionally — hard-coded before pass-through `volumes`/`volumeMounts`, `readOnly: true`
- [ ] Secret suffixes match values block names (`-db`, `-kafka`, `-node`)
- [ ] See `postgres.md` checklist for database credential items
- [ ] See `kafka.md` checklist for Kafka SASL credential items
- [ ] `checksum/config` (ConfigMap) and `checksum/secret` (Secret) annotations on every workload that mounts them — each `include` guarded by the same condition that renders the file, placed above the `podAnnotations` merge
- [ ] Reloader annotation in `defaults/values.yaml` via `podAnnotations`
- [ ] Downward API metadata env vars present (NAMESPACE, POD_NAME, POD_IP, HOST_IP, NODE_NAME, CPU/MEM request/limit)
- [ ] Env var ordering: downward API → config values → secret references
- [ ] All five scheduling fields in every workload template (nodeSelector, affinity, tolerations, topologySpreadConstraints, priorityClassName)
- [ ] Volumes and volumeMounts pass-through with `toYaml`
- [ ] Deployment strategy appropriate for workload type (RollingUpdate vs Recreate)
- [ ] Liveness probe appropriate for workload type (HTTP or heartbeat file)
- [ ] `defaults/values.yaml` sets security context, pull secrets, reloader annotation, `/tmp` emptyDir
- [ ] PDB selector uses `selectorLabels` — matches Deployment selector exactly
- [ ] HPA wires both shorthand and custom `metrics`/`behavior`
- [ ] Monitoring templates (PodMonitor/ServiceMonitor/PrometheusRule) behind `metrics.enabled` gate
- [ ] CRD templates use `required` and `fail` for input validation
- [ ] Service uses named ports (`http`, `metrics`, `grpc`)
- [ ] Every workload (Deployment/StatefulSet/CronJob/Job) carries a unique `app.kubernetes.io/component`; Deployments/StatefulSets include it in the selector, Jobs/CronJobs only in labels
- [ ] No duplicate template blocks (e.g., tolerations rendered twice)
- [ ] Image tag pinned (no `:latest` in committed manifests)
- [ ] No literal credentials in env overlays — ExternalSecret references only
- [ ] `automountServiceAccountToken: false` unless the workload calls the API server
- [ ] RBAC created only when the workload calls the API server; namespaced `Role` preferred, explicit `verbs` (never `["*"]`); `automount: true` paired with `rbac.create: true`
- [ ] NetworkPolicy `podSelector` uses `selectorLabels`; `policyTypes` derived from present rule sets; DNS egress allowed whenever egress is restricted
- [ ] NetworkPolicy (and other restrictive features) default to `enabled: false` in base `values.yaml` with rules commented — enabled only in `defaults/`/overlays, so local kind/compose isn't blocked

**Multi-deployment charts:**

- [ ] Templates organized in component folders (`frontend/`, `backend/`, `worker/`, `shared/`)
- [ ] Component-scoped helpers defined: `componentName`, `componentLabels`, `componentSelectorLabels`
- [ ] A unique `app.kubernetes.io/component` on every workload and its dependent resources (Service/PDB/Monitor/NetworkPolicy selectors match it)
- [ ] Component labels defined: `role`, `component-type`, `tier` (both Deployment and Pod level)
- [ ] Each component has `enabled: false` toggle for per-environment control
- [ ] Component values nested under component name (`.Values.frontend.*`, `.Values.backend.*`)
- [ ] `componentImage` helper supports per-component image/tag overrides with global fallback
- [ ] NOTES.txt shows status for each enabled component
- [ ] For iteration pattern: use `$` for root context inside `range` loops
- [ ] Component selectors include component identifier (label or tenant name) for proper isolation
