# Reasoning breadcrumbs — examples

The `action` field is the human-readable record. Write it as if explaining to someone who wasn't in this session and has no context:

```yaml
# Good
p1.taskfile.tasks.template:
  status: completed
  completedAt: "2026-05-25T10:05:00Z"
  action: >
    Added template:dev, template:prod, and _template tasks following the
    taskfile skill's canonical Helm Taskfile. Values files are passed in
    order: values.yaml → defaults/values.yaml → <env>/values.yaml.
    Output goes to .argo/<env>/<chart>/.

# Good
p2.helm.api.helpers.selector-no-version:
  status: completed
  completedAt: "2026-05-25T10:06:00Z"
  action: >
    Removed app.kubernetes.io/version from selectorLabels. Selectors on
    Deployments are immutable — version in the selector breaks upgrades.

# Good
p4.skaffold.exists:
  status: skipped
  completedAt: "2026-05-25T10:07:00Z"
  action: "No local kind cluster setup in this repo — skaffold not applicable."

# Good
p2.helm.api.values.no-latest:
  status: failed
  completedAt: "2026-05-25T10:08:00Z"
  action: >
    dev/values.yaml:8 has image.tag: latest. Replace with a pinned tag
    or commit SHA. This is a security/reproducibility issue — not auto-fixed.
```
