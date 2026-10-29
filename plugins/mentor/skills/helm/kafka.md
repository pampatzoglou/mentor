# Helm — Kafka Credentials

Kafka SASL credential patterns. Companion to `patterns.md` (base patterns) and `SKILL.md` (foundations).

## Credential values shape

```yaml
kafka:
  brokers: ""
  securityProtocol: "SASL_PLAINTEXT"
  sasl:
    mechanism: SCRAM-SHA-512
    username: ""
    password: ""
    mountPath: /var/run/secrets/kafka    # always mounted; files: .../kafka/<key>
    externalSecret:
      enable: false
      name: ""                           # name of a pre-existing Secret
      usernameKey: username
      passwordKey: password
    vault:
      enable: false
      method: GET
      provider:
        server: http://vault.vault:8200
        version: v2
      resultType: Data
      path: ""                           # e.g. "kafka/creds/my-role"
      usernameKey: username
      passwordKey: password
      refreshInterval: "1h"
```

Three credential modes — see `SKILL.md` for the mode table and `vault.mountPath`/`vault.role` chart-level auth config.

---

## secrets.yaml

All three credential resources live in `secrets.yaml`. Only one renders at a time, controlled by the enable flags.

```gotmpl
{{- if and (not .Values.kafka.sasl.externalSecret.enable) (not .Values.kafka.sasl.vault.enable) }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "my-chart.fullname" . }}-kafka
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
type: Opaque
stringData:
  username: {{ .Values.kafka.sasl.username | quote }}
  password: {{ .Values.kafka.sasl.password | quote }}
{{- end }}
{{- if and .Values.kafka.sasl.vault.enable .Values.kafka.sasl.vault.path }}
---
apiVersion: generators.external-secrets.io/v1alpha1
kind: VaultDynamicSecret
metadata:
  name: {{ include "my-chart.fullname" . }}-kafka-generator
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  provider:
    server: {{ required "kafka.sasl.vault.provider.server is required" .Values.kafka.sasl.vault.provider.server | quote }}
    version: {{ .Values.kafka.sasl.vault.provider.version | default "v2" | quote }}
    auth:
      kubernetes:
        mountPath: {{ .Values.vault.mountPath | default "kubernetes" | quote }}
        role: {{ required "vault.role is required" .Values.vault.role | quote }}
        serviceAccountRef:
          name: {{ include "my-chart.serviceAccountName" . }}
          namespace: {{ .Release.Namespace }}
  method: {{ .Values.kafka.sasl.vault.method | default "GET" | upper | quote }}
  path: {{ required "kafka.sasl.vault.path is required" .Values.kafka.sasl.vault.path | quote }}
  resultType: {{ .Values.kafka.sasl.vault.resultType | default "Data" }}
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: {{ include "my-chart.fullname" . }}-kafka
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  refreshInterval: {{ .Values.kafka.sasl.vault.refreshInterval | default "1h" | quote }}
  target:
    name: {{ include "my-chart.fullname" . }}-kafka
    creationPolicy: Owner
    deletionPolicy: Retain
  dataFrom:
    - sourceRef:
        generatorRef:
          apiVersion: generators.external-secrets.io/v1alpha1
          kind: VaultDynamicSecret
          name: {{ include "my-chart.fullname" . }}-kafka-generator
{{- end }}
```

The VaultDynamicSecret and ExternalSecret render under a single `{{- if }}` guard — they are always deployed as a pair. The ExternalSecret target name (`{{ fullname }}-kafka`) is the same as the chart-internal Secret name, so the Deployment template wiring is identical across all three modes.

---

## Deployment wiring

### env vars (secretKeyRef)

```gotmpl
- name: KAFKA_SASL_USERNAME
  valueFrom:
    secretKeyRef:
      {{- if .Values.kafka.sasl.vault.enable }}
      name: {{ include "my-chart.fullname" . }}-kafka
      key: {{ .Values.kafka.sasl.vault.usernameKey }}
      {{- else if .Values.kafka.sasl.externalSecret.enable }}
      name: {{ .Values.kafka.sasl.externalSecret.name }}
      key: {{ .Values.kafka.sasl.externalSecret.usernameKey }}
      {{- else }}
      name: {{ include "my-chart.fullname" . }}-kafka
      key: username
      {{- end }}
- name: KAFKA_SASL_PASSWORD
  valueFrom:
    secretKeyRef:
      {{- if .Values.kafka.sasl.vault.enable }}
      name: {{ include "my-chart.fullname" . }}-kafka
      key: {{ .Values.kafka.sasl.vault.passwordKey }}
      {{- else if .Values.kafka.sasl.externalSecret.enable }}
      name: {{ .Values.kafka.sasl.externalSecret.name }}
      key: {{ .Values.kafka.sasl.externalSecret.passwordKey }}
      {{- else }}
      name: {{ include "my-chart.fullname" . }}-kafka
      key: password
      {{- end }}
```

### file mount (always present)

```gotmpl
          volumeMounts:
            - name: kafka-credentials
              mountPath: {{ .Values.kafka.sasl.mountPath | default "/var/run/secrets/kafka" }}
              readOnly: true
            {{- with .Values.volumeMounts }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
      volumes:
        - name: kafka-credentials
          secret:
            secretName: {{ include "my-chart.fullname" . }}-kafka
        {{- with .Values.volumes }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
```

The Secret name (`{{ fullname }}-kafka`) is stable regardless of credential mode. Key names vary:

| Mode | Keys available as files |
|---|---|
| Chart-internal | `username`, `password` |
| ExternalSecret | whatever the upstream store provides |
| Vault dynamic | `kafka.sasl.vault.usernameKey`, `kafka.sasl.vault.passwordKey` |

---

## Checklist

- [ ] Chart-internal Secret rendered only when both `kafka.sasl.vault.enable` and `kafka.sasl.externalSecret.enable` are false
- [ ] `secretKeyRef` handles all three modes: `kafka.sasl.vault.enable` → `kafka.sasl.externalSecret.enable` → chart-internal
- [ ] When `kafka.sasl.vault.enable: true`: `{{ fullname }}-kafka-generator` (VaultDynamicSecret) and `{{ fullname }}-kafka` (ExternalSecret) rendered under a single guard in `secrets.yaml`
- [ ] VaultDynamicSecret and ExternalSecret are never rendered independently — always as a pair
- [ ] VaultDynamicSecret `serviceAccountRef` includes both `name` and `namespace: {{ .Release.Namespace }}`
- [ ] `vault.role` bound to this chart's SA in Vault (`bound_service_account_names` + `bound_service_account_namespaces`)
- [ ] `kafka.sasl.mountPath` set (default `/var/run/secrets/kafka`); credential volume and volumeMount unconditional, `readOnly: true`
- [ ] Credential volume declared **before** pass-through `volumes` in the Deployment
- [ ] No literal credentials in env overlays — ExternalSecret or Vault references only
