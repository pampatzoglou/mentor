# Helm — Postgres Credentials

Postgres credential patterns and migration operations. Companion to `patterns.md` (base patterns) and `SKILL.md` (foundations).

## Credential values shape

```yaml
database:
  host: ""
  port: "5432"
  database: ""
  username: "postgres"
  password: "postgres"
  mountPath: /var/run/secrets/db    # always mounted; files: .../db/<key>
  externalSecret:
    enable: false
    name: ""                        # name of a pre-existing Secret
    usernameKey: username
    passwordKey: password
  vault:
    enable: false
    method: GET
    provider:
      server: http://vault.vault:8200
      version: v2
    resultType: Data
    path: ""                        # e.g. "database/creds/my-role"
    usernameKey: username
    passwordKey: password
    refreshInterval: "1h"
```

Three credential modes — see `SKILL.md` for the mode table and `vault.mountPath`/`vault.role` chart-level auth config.

---

## secrets.yaml

All three credential resources live in `secrets.yaml`. Only one renders at a time, controlled by the enable flags.

```gotmpl
{{- if and (not .Values.database.externalSecret.enable) (not .Values.database.vault.enable) }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "my-chart.fullname" . }}-db
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
type: Opaque
stringData:
  username: {{ .Values.database.username | quote }}
  password: {{ .Values.database.password | quote }}
{{- end }}
{{- if and .Values.database.vault.enable .Values.database.vault.path }}
---
apiVersion: generators.external-secrets.io/v1alpha1
kind: VaultDynamicSecret
metadata:
  name: {{ include "my-chart.fullname" . }}-postgres-generator
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  provider:
    server: {{ required "database.vault.provider.server is required" .Values.database.vault.provider.server | quote }}
    version: {{ .Values.database.vault.provider.version | default "v2" | quote }}
    auth:
      kubernetes:
        mountPath: {{ .Values.vault.mountPath | default "kubernetes" | quote }}
        role: {{ required "vault.role is required" .Values.vault.role | quote }}
        serviceAccountRef:
          name: {{ include "my-chart.serviceAccountName" . }}
          namespace: {{ .Release.Namespace }}
  method: {{ .Values.database.vault.method | default "GET" | upper | quote }}
  path: {{ required "database.vault.path is required" .Values.database.vault.path | quote }}
  resultType: {{ .Values.database.vault.resultType | default "Data" }}
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: {{ include "my-chart.fullname" . }}-db
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  refreshInterval: {{ .Values.database.vault.refreshInterval | default "1h" | quote }}
  target:
    name: {{ include "my-chart.fullname" . }}-db
    creationPolicy: Owner
    deletionPolicy: Retain
  dataFrom:
    - sourceRef:
        generatorRef:
          apiVersion: generators.external-secrets.io/v1alpha1
          kind: VaultDynamicSecret
          name: {{ include "my-chart.fullname" . }}-postgres-generator
{{- end }}
```

The VaultDynamicSecret and ExternalSecret render under a single `{{- if }}` guard — they are always deployed as a pair. The ExternalSecret target name (`{{ fullname }}-db`) is the same as the chart-internal Secret name, so the Deployment template wiring is identical across all three modes.

---

## Deployment wiring

### env vars (secretKeyRef)

Include this block **only when the application reads its credentials from the environment**; the
file mount below is unconditional either way. `secretKeyRef` is the sanctioned way to do env
injection — never a literal — and it must resolve to the same Secret key the file comes from. See
the `secrets` skill, *Files always; env only where the code actually reads env*.

```gotmpl
- name: DB_USERNAME
  valueFrom:
    secretKeyRef:
      {{- if .Values.database.vault.enable }}
      name: {{ include "my-chart.fullname" . }}-db
      key: {{ .Values.database.vault.usernameKey }}
      {{- else if .Values.database.externalSecret.enable }}
      name: {{ .Values.database.externalSecret.name }}
      key: {{ .Values.database.externalSecret.usernameKey }}
      {{- else }}
      name: {{ include "my-chart.fullname" . }}-db
      key: username
      {{- end }}
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      {{- if .Values.database.vault.enable }}
      name: {{ include "my-chart.fullname" . }}-db
      key: {{ .Values.database.vault.passwordKey }}
      {{- else if .Values.database.externalSecret.enable }}
      name: {{ .Values.database.externalSecret.name }}
      key: {{ .Values.database.externalSecret.passwordKey }}
      {{- else }}
      name: {{ include "my-chart.fullname" . }}-db
      key: password
      {{- end }}
```

### file mount (always present)

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

The Secret name (`{{ fullname }}-db`) is stable regardless of credential mode. Key names vary:

| Mode | Keys available as files |
|---|---|
| Chart-internal | `user`, `password` |
| ExternalSecret | whatever the upstream store provides |
| Vault dynamic | `database.vault.usernameKey`, `database.vault.passwordKey` |

---

## Migration Job with Helm hooks

For database migrations that must run before the application starts. Hook ordering guarantees the admin Secret exists before the Job runs.

```gotmpl
{{- if .Values.migrate.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "my-chart.fullname" . }}-migrate
  annotations:
    "helm.sh/hook": post-install,pre-upgrade
    "helm.sh/hook-weight": "0"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: {{ .Values.migrate.backoffLimit }}
  ttlSecondsAfterFinished: {{ .Values.migrate.ttlSecondsAfterFinished }}
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: {{ include "my-chart.image" . }}
          command: [...]
          env:
            # credentials via secretKeyRef — same three-way toggle as the app
{{- end }}
```

When the migration needs admin credentials separate from app credentials, create a hook-ordered admin Secret at weight `-10` so it exists before the Job at weight `0`:

```gotmpl
{{- if and .Values.migrate.enabled (not .Values.database.admin.externalSecret.enable) }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "my-chart.fullname" . }}-db-admin
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation
type: Opaque
stringData:
  username: {{ .Values.database.admin.username | quote }}
  password: {{ .Values.database.admin.password | quote }}
{{- end }}
```

Values shape:

```yaml
migrate:
  enabled: false
# migrate:
#   enabled: true
#   backoffLimit: 1
#   ttlSecondsAfterFinished: 600
```

---

## Checklist

- [ ] Chart-internal Secret rendered only when both `database.vault.enable` and `database.externalSecret.enable` are false
- [ ] `secretKeyRef` handles all three modes: `database.vault.enable` → `database.externalSecret.enable` → chart-internal
- [ ] When `database.vault.enable: true`: `{{ fullname }}-postgres-generator` (VaultDynamicSecret) and `{{ fullname }}-db` (ExternalSecret) rendered under a single guard in `secrets.yaml`
- [ ] VaultDynamicSecret and ExternalSecret are never rendered independently — always as a pair
- [ ] VaultDynamicSecret `serviceAccountRef` includes both `name` and `namespace: {{ .Release.Namespace }}`
- [ ] `vault.role` bound to this chart's SA in Vault (`bound_service_account_names` + `bound_service_account_namespaces`)
- [ ] `database.mountPath` set (default `/var/run/secrets/db`); credential volume and volumeMount unconditional, `readOnly: true`
- [ ] Credential volume declared **before** pass-through `volumes` in the Deployment
- [ ] Migration Job hook weight: admin Secret at `-10`, migrate Job at `0`
- [ ] No literal credentials in env overlays — ExternalSecret or Vault references only
