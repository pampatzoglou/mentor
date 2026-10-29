---
name: housekeeping
description: Stateful, idempotent repo sweep of a Kubernetes service repo. Applies companion skills in pass order (devbox/taskfile → dockerfile/compose → helm → kubernetes → argo/skaffold → github-actions → tidy → prune → document) and iterates until the repo converges. Writes .housekeeping/state.yaml breadcrumbs so re-runs skip completed items. Does not cover Terraform — run the terraform skill directly for IaC repos.
requires: [devbox, taskfile, dockerfile, docker-compose, helm, argo-applicationset, skaffold, kubernetes, secrets, github-actions, tidy, prune, document]
---

# Repo Housekeeping

Multi-pass, stateful sweep of a service repo. Each pass applies one companion skill's standards in full. Passes repeat until a complete cycle produces no new changes — at which point the repo has converged.

**Take your time.** This is a marathon, not a sprint. Read each file before touching it. Write state after every item. When something is unclear, flag it and move on — don't guess.

---

## Scope vs sibling skills

| Skill | Responsibility |
|---|---|
| `housekeeping` | Orchestrator — runs companion skills in order, tracks state, iterates to convergence |
| `bootstrap` | Creates a repo from nothing. Housekeeping converges an *existing* one — never scaffold a whole repo from here |
| `platform-review` | Reviews a *diff* and reports. Housekeeping sweeps the whole tree and *fixes* |
| `tidy` | Mechanical style drift — called as Pass 6 |
| `prune` | Removal and dead code — called as Pass 7 |
| `document` | Documentation generation — called as Pass 8 |
| `terraform` | **Out of scope.** No pass covers `.tf` — invoke the `terraform` skill directly |

**This skill holds no standards of its own.** Every rule belongs to the skill named in its
pass. When a pass needs a criterion, load that skill and apply *its* checklist rather than
restating it here — a copy here is a copy that drifts. The tables below are item inventories
and auto-fix policy, not a second source of truth.

Do not inline `tidy`, `prune`, or `document` logic here. Invoke each as its own pass with its own state entries.

---

## State file

**Location**: `.housekeeping/state.yaml` in the root of the repo being swept.

**Persistence**: commit it to share progress across the team. The state file is the authoritative record of what has been done and why.

```yaml
version: "1"
lastRun: ""          # ISO timestamp — updated at the start of each run
repoRoot: ""         # absolute path — sanity-check on re-run
items:
  <item-id>:
    status: pending | completed | skipped | failed
    completedAt: ""  # set when status is resolved
    action: ""       # what was done, why skipped, or what manual action is needed
```

**Item ID format**: `<pass>.<area>.<target>.<check>`

Examples:
- `p1.devbox.tasks.cluster-up`
- `p1.taskfile.tasks.template`
- `p1.taskfile.ci-integration`
- `p2.helm.api.chart-yaml.name-matches-dir`
- `p2.helm.api.helpers.selector-no-version`
- `p3.k8s.api.security.run-as-non-root`
- `p3.k8s.api.resources.limits-set`
- `p3.k8s.api.probes.readiness-exists`
- `p4.argo.applicationset.go-template`
- `p5.ci.workflow.calls-tasks`
- `p6.tidy.helm.api.deployment`
- `p7.prune.helm.api.values`
- `p8.docs.readme`

**Write state after every single item.** Interrupted runs never reprocess completed work.

---

## Run protocol

1. **Load state** — read `.housekeeping/state.yaml`. Create it if absent.
2. **Set `lastRun`** — write current ISO timestamp and save immediately.
3. **Execute passes in order** — for each pass, enumerate items, skip `completed`/`skipped`, process the rest.
4. **Emit a breadcrumb per item** — one line of conversational output:
   ```
   [completed] p1.taskfile.tasks.template — added template:dev and template:prod tasks
   [skipped]   p1.taskfile.tasks.cluster-up — repo has no kind cluster setup
   [failed]    p2.helm.api.values.no-latest — image.tag: latest in dev/values.yaml — manual fix needed
   ```
5. **Convergence check** — after all passes complete, if zero items transitioned `pending → completed` in this run, declare convergence and stop.
6. **Non-convergence** — list remaining `pending` and `failed` items. Stop. The next run picks up automatically.

**Convergence = no new completions in a full cycle.** `failed` items block convergence until a human resolves them and re-runs.

---

## When to fix vs when to flag

**Fix automatically** — safe, mechanical, no domain knowledge required:
- Adding missing keys to `values.yaml` with their canonical defaults
- Adding missing helpers to `_helpers.tpl`
- Adding `ignoreMissingValueFiles: true`
- Adding `goTemplate: true` + `missingkey=default`
- Creating stub files (`NOTES.txt`, `.helmignore`, `defaults/values.yaml`)
- Adding standard task definitions (`template:dev`, `lint`, `audit`) from the `taskfile` skill
- Setting `serviceAccount.automount: false`
- Adding missing PSA labels to `managedNamespaceMetadata`

**Flag and set `failed`** — requires human judgment:
- Security issues — hardcoded credentials, tokens, API keys
- Ambiguous values — which Vault path, which cluster name, which namespace
- Structural conflicts — existing patterns that contradict the standards but may be intentional
- Anything where the correct value cannot be derived from the existing code

Never silently drop a finding. If you can't auto-fix it, `status: failed` with a clear `action` is the right outcome.

---

## Passes

### Pass 1 — Foundation

Goal: tooling and automation work before touching chart content.

#### 1a. devbox — load `devbox` skill

| Item | Check | Auto-fix |
|---|---|---|
| `p1.devbox.exists` | `devbox.json` present | Create from `devbox` skill template |
| `p1.devbox.envrc` | `.envrc` present with `eval "$(devbox generate direnv --print-envrc)"` | Create |
| `p1.devbox.packages.helm` | `helm` pinned | Add |
| `p1.devbox.packages.kubectl` | `kubectl` pinned | Add |
| `p1.devbox.packages.kind` | `kind` pinned (if cluster scripts exist) | Add |
| `p1.devbox.packages.skaffold` | `skaffold` pinned (if `skaffold.yaml` exists) | Add |
| `p1.devbox.packages.go-task` | `go-task` pinned | Add |
| `p1.devbox.packages.kubeconform` | `kubeconform` pinned | Add |
| `p1.devbox.packages.kubescape` | `kubescape` pinned | Add |

Apply the full `devbox` skill completion checklist. All packages must be version-pinned.

#### 1b. Taskfile — load `taskfile` skill

| Item | Check | Auto-fix |
|---|---|---|
| `p1.taskfile.exists` | `Taskfile.yaml` present | Create from `taskfile` skill's canonical Helm skeleton |
| `p1.taskfile.tasks.default` | `default` task lists available tasks | Add |
| `p1.taskfile.tasks.template` | `template`, `template:dev`, `template:prod` tasks defined | Add per `taskfile` skill |
| `p1.taskfile.tasks.lint` | `lint`, `lint:dev`, `lint:prod` tasks defined | Add |
| `p1.taskfile.tasks.audit` | `audit`, `audit:dev`, `audit:prod` tasks defined | Add |
| `p1.taskfile.tasks.scan` | `scan` task defined (kubescape) | Add |
| `p1.taskfile.tasks.clean` | `clean` task defined | Add |
| `p1.taskfile.tasks.cluster-up` | `cluster:up` present (if kind is in devbox) | Add from `devbox` skill |
| `p1.taskfile.tasks.cluster-down` | `cluster:down` present | Add |
| `p1.taskfile.tasks.cluster-reset` | `cluster:reset` present | Add |
| `p1.taskfile.output-dir` | `.argo/` output directory convention used | Update if using a different path |
| `p1.taskfile.values-layering` | `_template` task passes `values.yaml` → `defaults/values.yaml` → `<env>/values.yaml` in that order | Fix ordering |
| `p1.taskfile.ci-integration` | CI workflow calls `task audit`, not inline helm commands | Flag only — CI is read-only for this pass |
| `p1.taskfile.destructive-prompt` | Any destructive task (`destroy`, `db:drop`, `apply:prod`) has `prompt:` | Add `prompt:` where missing |

Apply the full `taskfile` skill completion checklist. The `action:env` naming convention must be followed.

#### 1c. Container build — load `dockerfile` and `docker-compose` skills

Skip entirely if the repo builds no image (a chart-only platform repo). Otherwise apply each
skill's own success criteria; the items below are the ones that cross into later passes.

**Load `secrets` before touching any `secrets:` block or `*_FILE` env** — here and in Pass 2. It
owns the mount path and env convention that `p1.compose.secrets-from-files` below asserts, and
that the chart's credential blocks must agree with. Compose and Helm each own only their syntax
for it.

| Item | Check | Auto-fix |
|---|---|---|
| `p1.dockerfile.exists` | `Dockerfile` present when the repo has application source | Flag — generating one needs the `dockerfile` skill's full analysis, not a template |
| `p1.dockerfile.stages` | Four named stages: `base`, `build`, `develop`, `production` | Flag — restructuring is not mechanical |
| `p1.dockerfile.no-copy-all` | No `COPY . .` in any stage | Flag |
| `p1.dockerfile.volumes-declared` | Every runtime-writable path declared with `VOLUME` | Flag — the path list comes from reading the app |
| `p1.dockerfile.digest-pinned` | `production` base image pinned by digest | Flag — needs a registry lookup |
| `p1.compose.target-develop` | `docker-compose.yaml` builds `target: develop`, not the default (production) stage | Set |
| `p1.compose.hardening` | `read_only`, `tmpfs`, `cap_drop: [ALL]`, `no-new-privileges`, non-root `user:` on every service | Add |
| `p1.compose.secrets-from-files` | No literal secret in `environment:`; `*_FILE` env pointing at the same `/var/run/secrets/<block>/<key>` path the chart mounts (`secrets` skill) | Fix a flat target; flag literals — never auto-write a secret |
| `p1.uid.single-source` | The Dockerfile `USER` uid matches compose `user:` and the chart's `runAsUser`/`runAsGroup`/`fsGroup` | Align the *consumers* to the Dockerfile — it is the source of truth. Never change the Dockerfile to match a chart |

`p1.uid.single-source` is the seam Pass 3's security items depend on. Resolve it here, before
Pass 3 sets `runAsUser` in `defaults/values.yaml`, or the two passes will disagree.

---

### Pass 2 — Helm charts

Goal: every chart in `deploy/charts/` meets the standards in the `helm` skill, `helm/postgres.md`, and `helm/kafka.md`.

For each chart directory `<chart>` under `deploy/charts/`:

**Load `helm` skill and apply its completion checklist** — plus `secrets` for every credential block, since it owns the contract those blocks implement. Item IDs follow `p2.helm.<chart>.<section>.<check>`. The full checklist lives in `SKILL.md` (foundations) and `patterns.md` (patterns). Run every item in both.

Critical items to verify explicitly (these are commonly missed):

| Item | Check | Auto-fix |
|---|---|---|
| `p2.helm.<chart>.chart-yaml.name-matches-dir` | `name:` field matches directory name | Update |
| `p2.helm.<chart>.chart-yaml.appversion-not-scaffold` | `appVersion` is not `"1.16.0"` | Flag |
| `p2.helm.<chart>.values.standard-keys` | All 14 standard infrastructure keys present | Add missing with empty defaults |
| `p2.helm.<chart>.values.sa-automount` | `serviceAccount.automount: false` | Set |
| `p2.helm.<chart>.helpers.selector-no-version` | `selectorLabels` does not include `app.kubernetes.io/version` | Remove |
| `p2.helm.<chart>.templates.scheduling-fields` | All 5 scheduling fields in Deployment/StatefulSet/CronJob | Add missing |
| `p2.helm.<chart>.templates.downward-api` | Downward API block (NAMESPACE, POD_NAME, POD_IP, HOST_IP, NODE_NAME, CPU/MEM) in every container | Add |
| `p2.helm.<chart>.templates.checksum` | `checksum/config` annotation on pod template | Add |
| `p2.helm.<chart>.defaults.exists` | `defaults/values.yaml` present | Create stub |
| `p2.helm.<chart>.defaults.security-context` | Security context set from `kubernetes` skill standards | Add |
| `p2.helm.<chart>.defaults.reloader` | `reloader.stakater.com/auto: "true"` in `podAnnotations` | Add |

**If `database` block exists in values**, load `helm/postgres.md` and apply its checklist under `p2.helm.<chart>.postgres.*`.

**If `kafka` block exists in values**, load `helm/kafka.md` and apply its checklist under `p2.helm.<chart>.kafka.*`.

After applying checklist items, run `helm template` to validate the chart renders cleanly. If it fails, mark the relevant item `failed` with the exact error.

---

### Pass 3 — Kubernetes Manifest Standards

Goal: every rendered workload meets the security, resource, probe, and HA standards in the `kubernetes` skill.

**Load `kubernetes` skill** and apply `reviewing-manifests.md` against the rendered output of each chart. Item IDs: `p3.k8s.<chart>.<category>.<check>`.

Render each chart first:
```bash
helm template <chart> deploy/charts/<chart> \
  -f deploy/charts/<chart>/values.yaml \
  -f deploy/charts/<chart>/defaults/values.yaml \
  -f deploy/charts/<chart>/dev/values.yaml
```

Walk the `reviewing-manifests.md` checklist in blocker-tier-first order:

#### Security context — `p3.k8s.<chart>.security.*`

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

#### Resources — `p3.k8s.<chart>.resources.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `limits-set` | Every container (including init and sidecars) has `resources.limits` | Flag — values depend on workload; add commented example |
| `requests-set` | Every container has `resources.requests` | Flag — same reason |
| `no-empty-resources` | No `resources: {}` | Replace with commented example |

Resources require domain knowledge (CPU/memory sizing) — never auto-fill with numbers. Add the recommended commented-out shape from the `helm` skill and set `status: failed` prompting the operator to fill in values.

#### Image hygiene — `p3.k8s.<chart>.image.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `no-latest` | No `:latest` tag in any values file | Flag |
| `tag-or-digest` | Every image reference has a tag or digest | Flag |

#### Probes — `p3.k8s.<chart>.probes.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `readiness-exists` | HTTP services have `readinessProbe` | Add stub — endpoint requires human input |
| `liveness-exists` | Long-running services have `livenessProbe` | Add stub |
| `startup-for-slow-start` | Slow-starting apps have `startupProbe` | Flag — timing requires human input |
| `no-tcp-on-http` | HTTP services don't use TCP probes | Replace with httpGet stub |

Probe endpoints and thresholds cannot be derived from the chart alone. Create a stub pointing to the helm `patterns.md` probe templates and set `status: failed` for human completion.

#### High availability — `p3.k8s.<chart>.ha.*`

Check only when `replicaCount >= 2` or `autoscaling.minReplicas >= 2`:

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `pdb-exists` | PDB template present and enabled | Create stub if absent |
| `anti-affinity` | `topologySpreadConstraints` or `affinity` set in defaults | Add standard spread from `kubernetes/resource-standards.md` |

#### Labels and selectors — `p3.k8s.<chart>.labels.*`

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

#### GitOps — `p3.k8s.<chart>.gitops.*`

| Check suffix | Condition | Auto-fix |
|---|---|---|
| `no-kubectl-apply-in-readme` | README doesn't instruct `kubectl apply` to managed cluster | Flag |
| `sync-wave-correct` | Prerequisites at lower wave numbers than dependents | Flag — wave ordering requires repo knowledge |

After all checklist items, run kubescape:
```bash
task audit:dev
# or directly:
kubescape scan framework nsa deploy/charts/<chart> --severity-threshold high
```

For each finding from kubescape:
- Auto-fix mechanical issues (missing securityContext fields already covered above)
- For ambiguous findings, add an entry to `.kubescape/exceptions.json` with a `reason` field and set `status: failed`

---

### Pass 4 — ArgoCD and Skaffold

Goal: ApplicationSets and local dev config meet the standards in `argo-applicationset` and `skaffold` skills.

**Load `argo-applicationset` skill** and apply its completion checklist for each file in `deploy/argo/`. Item IDs: `p4.argo.<filename>.<check>`.

| Item | Check | Auto-fix |
|---|---|---|
| `p4.argo.<f>.go-template` | `goTemplate: true` | Add |
| `p4.argo.<f>.missing-key-default` | `goTemplateOptions: [missingkey=default]` | Add |
| `p4.argo.<f>.namespace-metadata` | `managedNamespaceMetadata` with full PSA label set | Add standard block |
| `p4.argo.<f>.ignore-missing-values` | `ignoreMissingValueFiles: true` | Add |
| `p4.argo.<f>.values-layering` | `values.yaml → defaults/values.yaml → <env>/values.yaml` | Reorder |
| `p4.argo.<f>.sync-options` | ServerSideApply, ApplyOutOfSyncOnly, Wait | Add missing |
| `p4.argo.<f>.prune-explicit` | `prune:` explicitly set | Add `prune: false` |

**Load `skaffold` skill** and apply its checklist. Item IDs: `p4.skaffold.<check>`.

| Item | Check | Auto-fix |
|---|---|---|
| `p4.skaffold.exists` | `skaffold.yaml` present | Create from `skaffold` skill template |
| `p4.skaffold.push-false` | `local.push: false` | Set |
| `p4.skaffold.kube-context` | `kubeContext: kind-dev` | Set |
| `p4.skaffold.values-layering` | `valuesFiles` order matches `taskfile` and `helm` layer order | Fix |
| `p4.skaffold.dev-overrides` | `dev/values.yaml` has `pullPolicy: IfNotPresent`, empty `imagePullSecrets` | Add |

---

### Pass 5 — CI/CD

Goal: every required file and folder for CI and GitOps delivery is present and follows the `github-actions` skill.

**Load `github-actions` skill.** Item IDs: `p5.ci.<check>`.

#### Required directory structure

| Item | Check | Auto-fix |
|---|---|---|
| `p5.ci.dirs.github-workflows` | `.github/workflows/` directory exists | Create |
| `p5.ci.dirs.deploy-argo` | `deploy/argo/` directory exists | Create |
| `p5.ci.dirs.deploy-charts` | `deploy/charts/` directory exists | Create |
| `p5.ci.dirs.argo-output` | `.argo/` render target is gitignored, not committed | Add `.argo/` to `.gitignore`; no `.gitkeep` (the Taskfile creates it) |
| `p5.ci.dirs.kubescape` | `.kubescape/` directory exists | Create |

#### CI workflow files

| Item | Check | Auto-fix |
|---|---|---|
| `p5.ci.workflow.ci-exists` | `.github/workflows/ci.yaml` (or `ci.yml`) present | Create from `github-actions` skill template |
| `p5.ci.workflow.release-exists` | `.github/workflows/release.yaml` present | Create stub with image build trigger on tag push |
| `p5.ci.workflow.calls-tasks` | Every `run:` step delegates to `task X`, no inline helm/kubectl | Flag inline commands for extraction to Taskfile |
| `p5.ci.setup-tools-action` | `.github/actions/setup-tools/action.yml` exists and each job installs only the tools it needs | Create from the `github-actions` skill template |
| `p5.ci.no-devbox-in-ci` | No `devbox-install-action` and no `devbox run` in any workflow — CI installs tools via pinned setup actions | Replace with a `setup-tools` step |
| `p5.ci.version-parity` | Every version in `setup-tools` carries a `# devbox.json: <pkg>@<constraint>` comment and satisfies that constraint | Flag a mismatch — picking which side is correct needs a human |
| `p5.ci.workflow.concurrency` | `concurrency` block with `cancel-in-progress: true` | Add |
| `p5.ci.workflow.minimal-permissions` | `permissions: contents: read` at workflow level | Add |
| `p5.ci.workflow.sha-pinned-actions` | **Every** `uses:` is pinned to a full 40-char commit SHA with the version in a trailing comment — the `github-actions` skill owns this rule; a mutable `@v4`/`@main` tag is a finding, not an acceptable state | Resolve with `gh api repos/<o>/<r>/commits/<tag> --jq .sha`, or `pinact run` for the whole tree. Flag if the SHA can't be resolved offline |
| `p5.ci.workflow.persist-credentials-false` | `actions/checkout` has `persist-credentials: false` when downstream steps don't push | Add |
| `p5.ci.workflow.audit-step` | CI runs `task audit` (or `audit:dev`) | Add step |
| `p5.ci.workflow.matrix-envs` | For multi-env repos, `strategy.matrix.env` produces per-env audit runs | Add matrix |

#### Release workflow — image build

| Item | Check | Auto-fix |
|---|---|---|
| `p5.ci.release.tag-trigger` | `release.yaml` triggers on `tags: ['v*']` | Set |
| `p5.ci.release.oidc-auth` | Uses OIDC (`id-token: write`) rather than static registry credentials | Flag — registry-specific, cannot auto-fill |
| `p5.ci.release.image-tag-update` | Release workflow updates image tag in values files and pushes to deploy branch | Flag — repo-specific wiring |

#### ArgoCD folder setup

These items complement Pass 4 and ensure the folder structure ArgoCD expects actually exists:

| Item | Check | Auto-fix |
|---|---|---|
| `p5.ci.argo.applicationset-file` | `deploy/argo/applicationset.yaml` present | Create stub from `argo-applicationset` skill template |
| `p5.ci.argo.singletons-file` | `deploy/argo/singletons.yaml` present (if any singleton services) | Create stub if applicable |
| `p5.ci.argo.gitignore-argo-output` | `.argo/` **is** in `.gitignore` — it's a build artifact; ArgoCD renders `deploy/charts/<app>` itself via the ApplicationSet | Add to `.gitignore` if absent |

---

### Pass 6 — Tidy

Goal: mechanical style consistency, per the `tidy` skill.

**Load `tidy` skill.** For each file type in scope, run the full `tidy` checklist. Item IDs: `p6.tidy.<filetype>.<target>.<check>`.

Key areas:
- Helm template separators, empty variables, indentation
- YAML quoting consistency
- No `<no value>` strings in rendered output (run `helm template` to check)
- Trailing whitespace

Auto-fix style issues. If a finding is ambiguous (e.g., inconsistent quoting where both forms appear intentional), flag it.

---

### Pass 7 — Prune

Goal: remove dead code and AI context bloat, per the `prune` skill.

**Load `prune` skill.** Run the full `prune` checklist. Item IDs: `p7.prune.<category>.<target>`.

**Do not auto-delete anything.** Set `status: failed` for every finding, with the file path, line number, and rationale. Deletion requires explicit confirmation from the user.

### Out of scope for this pass — do not flag

Earlier passes deliberately create things `prune`'s generic heuristics would call bloat. Flagging them makes this pass fight Pass 2 and **the sweep can never converge**, because `failed` items block convergence. Skip:

- **The standard infrastructure keys** in `values.yaml` (`nodeSelector: {}`, `tolerations: []`, `extraObjects: []`, …). The `helm` skill mandates all of them, even empty, so overlays can set them without the chart "supporting" them. They are interface, not dead config.
- **Commented-out recommended shapes** in `values.yaml` (the `resources:` / `autoscaling:` / `metrics:` blocks). The `helm` skill requires these as inline documentation of every knob.
- **Placeholder-looking values in the base `values.yaml`** (`example.com`, empty strings). The base layer is scaffold defaults by design; real values live in `defaults/` and `<env>/`. Only flag a placeholder that appears in `defaults/` or an env overlay, where it *is* a bug.
- **`docker-compose.yaml`, `skaffold.yaml`, `.envrc`** being unreferenced by CI. They're local inner-loop tooling; nothing in CI is supposed to call them.
- **Commented-out code blocks** — `tidy` already owns these at Pass 6. Two passes reporting one finding with different verdicts is a boundary bug, not thoroughness.

Everything else in the `prune` checklist applies normally: genuinely unreferenced values, unused `_helpers.tpl` partials, dead template files, orphaned scripts, stale dependencies.

Exception: stub files created in Pass 2 that are now empty (e.g., a `NOTES.txt` that is still the placeholder) should be filled in, not deleted.

---

### Pass 8 — Documentation

Goal: README, architecture docs, and chart-level documentation are present and accurate, per the `document` skill.

**Load `document` skill.** Follow its Analyze → Confirm → Generate process. Item IDs: `p8.docs.<check>`.

| Item | Check | Auto-fix |
|---|---|---|
| `p8.docs.readme` | `README.md` present with local dev section | Create or update |
| `p8.docs.architecture` | `docs/ARCHITECTURE.md` present with Mermaid component diagram | Create stub |
| `p8.docs.taskfile-listed` | README documents `task --list` as the entry point | Add |
| `p8.docs.local-dev-loop` | README explains `devbox run cluster:up` + `skaffold dev` flow | Add |
| `p8.docs.chart-descriptions` | Each `Chart.yaml` has a non-empty `description:` | Flag — needs human input |

**Hard rules from `document` skill** (that skill is authoritative — these are a reminder, not a restatement):
- Mermaid first; SVG only when a diagram genuinely can't be expressed in Mermaid. Never PNG/JPG/drawio.
- Document current code, not aspirations
- No placeholder "TBD" sections — omit rather than stub
- Update, don't overwrite — preserve accurate existing sections

---

## Convergence

**Converged** = a full cycle (Passes 1–8) produces zero `pending → completed` transitions.

Before declaring convergence:
1. No items are in `pending` state
2. All `failed` items have been reviewed (either manually fixed and re-run, or explicitly overridden to `skipped` by the user)
3. Pass 8 (docs) completed — documentation reflects the final state of all the work done in Passes 1–7

Report format:
```
Converged.
  Pass 1 (Foundation):       12 completed,  2 skipped
  Pass 2 (Helm):             31 completed,  4 skipped,  1 failed
  Pass 3 (K8s standards):    14 completed,  2 skipped,  3 failed
  Pass 4 (Argo/Skaffold):    11 completed,  1 skipped
  Pass 5 (CI):                9 completed,  2 skipped,  1 failed
  Pass 6 (Tidy):              8 completed
  Pass 7 (Prune):             0 completed,  5 flagged (awaiting confirmation)
  Pass 8 (Docs):              4 completed

  Failed (manual review):
    p2.helm.api.values.no-latest   — image.tag: latest in dev/values.yaml
    p3.k8s.api.resources.limits-set — resources block empty on app container
    p5.ci.release.oidc-auth        — OIDC role ARN not known; add to repo secrets
```

---

## Reasoning breadcrumbs

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

---

## Re-run behaviour

1. Load state, verify `repoRoot` matches.
2. Skip all `completed` and `skipped` items.
3. Re-check `pending` and `failed` — if a human fixed a `failed` item, it will now pass.
4. New files discovered since last run (new chart, new ApplicationSet) produce new item IDs processed as `pending`.
5. Items never go backward in state. To force re-checking a completed item, delete its entry from the state file.

---

## Checklist

- [ ] State file created before any item is processed; `repoRoot` set
- [ ] `lastRun` updated at the **start** of the run, not the end
- [ ] State written after **each item** individually — no batching
- [ ] Every `skipped` item has a human-readable reason
- [ ] Every `failed` item specifies the exact manual action needed
- [ ] Passes run in order 1 → 8; a pass is complete only when all its items are resolved
- [ ] `tidy`, `prune`, and `document` are invoked as passes, not inlined
- [ ] `helm template` is run to validate after Pass 2 items that modify templates
- [ ] Convergence declared only when a full cycle produces zero new completions
- [ ] `failed` items block convergence — they are always reported in the summary
