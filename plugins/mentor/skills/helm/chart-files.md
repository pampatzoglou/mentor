# NOTES.txt and .helmignore

## NOTES.txt

Optional but recommended. Rendered after `helm install` / `helm upgrade` to show useful post-install information:

```gotmpl
{{- $fullName := include "my-chart.fullname" . -}}
1. Application deployed: {{ $fullName }}
   Namespace: {{ .Release.Namespace }}

2. Check status:
   kubectl get pods -l app.kubernetes.io/instance={{ .Release.Name }} -n {{ .Release.Namespace }}
```

Include kubectl commands to verify the deployment, access logs, or port-forward to the service. Keep it short — this is what the operator sees immediately after deploy.

## .helmignore

Exclude non-chart files from the Helm package to keep it clean and avoid leaking development artifacts:

```
.DS_Store
.git/
.gitignore
.idea/
.vscode/
*.swp
*.bak
*.tmp
*.orig
*~
__pycache__/
*.pyc
chart/
docs/
README.md
```

Include `README.md` in `.helmignore` — it's for humans reading the repo, not for the Helm package. Include language-specific artifacts (`__pycache__/`, `node_modules/`, etc.) relevant to the project.
