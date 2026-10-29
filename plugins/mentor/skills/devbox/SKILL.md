---
name: devbox
description: 'Reproducible developer environments via pinned Nix packages. Covers .envrc setup with direnv, devbox.json structure, pinning strategy, and an init_hook that performs SSO login (when available) and pulls required dev secrets from Vault on shell entry. devbox.json is also the declared source of truth for tool versions that CI must match — CI itself does not run devbox.'
---

# Devbox

Devbox pins CLI tool versions via Nix so every developer gets the exact same environment — not global installs, not brew. It is the **declared** source of truth for tool versions: `devbox.json` is where a version is decided, and CI's `setup-tools` action is obliged to match it (see *CI does not use devbox — but must match it*).

## .envrc — the project entry point

Every project using devbox gets this `.envrc` at the root:

```bash
eval "$(devbox generate direnv --print-envrc)"
```

Commit it. Each developer runs `direnv allow` once; from then on `cd`-ing into the project activates the environment automatically, `cd`-ing out deactivates it.

**Why this form** over `use devbox`: `devbox generate direnv --print-envrc` renders the activation script inline and works without a separate direnv devbox plugin. It is more portable and more explicit about what's happening.

## devbox.json structure

```json
{
  "$schema": "https://raw.githubusercontent.com/jetify-com/devbox/main/.schema/devbox.schema.json",
  "packages": [
    "go-task@3.40",
    "jq@1.7",
    "yq-go@4.45"
  ],
  "shell": {
    "init_hook": [],
    "scripts": {}
  }
}
```

`shell.scripts` are shortcuts runnable via `devbox run <name>`. Prefer delegating to Taskfile tasks (`task <name>`) so logic lives in one place — see [Scripts: delegate to Taskfile tasks](#scripts-delegate-to-taskfile-tasks). Reserve inline bodies for environment bootstrap that can't be a task (e.g. cluster lifecycle management).

**Commit both `devbox.json` and `devbox.lock`.** The lockfile captures the exact resolved Nix store path; without it the same `devbox.json` can resolve to different package versions on different days.

## Pinning strategy

Use major-or-minor constraints, not exact patch versions:

- ✅ `helm@3.16` — flexible on patch, locked on minor
- ❌ `helm@3.16.4` — over-pinned; breaks when Nix removes that exact revision

`devbox.lock` provides the actual reproducibility — `devbox.json` is the constraint, the lockfile is the truth.

## Common packages by domain

| Domain | Packages |
|---|---|
| Always | `go-task`, `jq`, `yq-go` |
| Kubernetes | `helm`, `kubectl`, `kind`, `skaffold`, `kubeconform`, `kubescape` |
| Terraform | `terraform`, `tflint`, `tfsec`, `terraform-docs` |
| Go | `go` |
| Python | `python311`, `uv` |
| Node | `nodejs_22` |
| Rust | `rustup` |
| Containers | `hadolint`, `trivy` |
| Cloud CLIs | `awscli2`, `google-cloud-sdk` |
| Secrets / auth | `vault` (+ a cloud SSO CLI for the init_hook — see Shell init) |

Don't add packages the project doesn't use — each is a download and PATH entry. A bloated shell is slow to enter and obscures actual dependencies.

## Common usage

```bash
devbox shell                  # enter pinned-tools shell
devbox run task lint          # run one command without entering the shell
devbox update                 # update all to latest within pinned constraints
devbox add <package>          # add a package and update devbox.lock
devbox info                   # show installed packages and versions
devbox doctor                 # diagnose environment issues (missing Nix, broken PATH, direnv not hooked)
```

## Scripts: delegate to Taskfile tasks

Like CI, `devbox run` scripts should call Taskfile tasks, not embed their own logic — the Taskfile stays the single source of truth, so a script and its CI equivalent run the exact same thing (see the `taskfile` skill). Inside a devbox script the environment is already active, so call `task` directly (no `devbox run` prefix needed):

```json
"shell": {
  "scripts": {
    "fmt":     ["task fmt"],
    "lint":    ["task lint"],
    "test":    ["task test"],
    "build":   ["task build"],
    "audit":   ["task audit"],
    "secrets": ["task secrets"]
  }
}
```

`devbox run lint` now does exactly what `task lint` does locally and what the CI job runs — one definition, three call sites.

**The exceptions are things a task can't do**, because both `devbox run <script>` and `task` execute in a subprocess:
- **Bootstrap that must run before the task toolchain or cluster exists** — cluster lifecycle (below) is the canonical example.
- **Anything that must mutate your interactive shell** (export secrets, change directory state). A subprocess can't set env vars in the parent shell — that's why secret export lives in the `init_hook`, not a script.

Everything that operates on the project's code delegates to `task`.

## CI does not use devbox — but must match it

Devbox owns the **developer's** machine. CI installs the same tools a different way: pinned
setup actions in a `setup-tools` composite action (see the `github-actions` skill). Running Nix
on a runner buys a large closure to restore per job, a third-party action in every job's
critical path, and opaque failures.

What survives is the important half: **`devbox.json` is the declared source of truth for tool
versions**, and CI is obliged to match it. `devbox.json` pins the constraint (`helm@3.16`); CI
pins a patch inside it (`v3.16.4`), with a `# devbox.json: helm@3.16` comment next to it so the
pairing is checkable.

**When you bump a version here, bump it in `.github/actions/setup-tools/action.yml` in the same
commit.** The `github-actions` skill carries a `task ci:versions` check that fails on drift —
wire it into `task lint` rather than relying on discipline. Divergence here means a chart
renders one way locally and another way in CI, which surfaces as a confusing failed deploy
rather than as a version problem.

## Gotchas

- **`yq` vs `yq-go`**: `yq` in nixpkgs is a Python/xq wrapper; `yq-go` is Mike Farah's Go implementation that most platform tooling expects. Always pin `yq-go`.
- **Not a container.** Devbox uses the host kernel — OS-level differences (macOS vs Linux glibc) can still matter for system-call-heavy tools.
- **Language dependency versions** (npm packages, go modules, cargo crates) are the language's own lockfile's job. Devbox pins the toolchain, not project deps.

## Kubernetes tooling

When the project deploys to Kubernetes, pin these additional packages:

```json
{
  "packages": [
    "go-task@3.40",
    "helm@3.16",
    "kubectl@1.33",
    "kind@0.27",
    "skaffold@2.16",
    "kubeconform@0.7",
    "kubescape@3",
    "yq-go@4.45",
    "jq@1.7"
  ]
}
```

Versions are illustrative — pick the latest stable at repo creation, then update deliberately via `devbox update`.

### Cluster lifecycle scripts

Add kind cluster management to `devbox.json` `shell.scripts`:

```json
"shell": {
  "init_hook": [
    "echo \"devbox ready — helm $(helm version --short 2>/dev/null), kubectl $(kubectl version --client --short 2>/dev/null | head -1)\""
  ],
  "scripts": {
    "cluster:up":    "kind create cluster --name dev --config kind.yaml",
    "cluster:down":  "kind delete cluster --name dev",
    "cluster:reset": "devbox run cluster:down && devbox run cluster:up"
  }
}
```

Usage:
```bash
devbox run cluster:up     # create the kind cluster (once per machine)
devbox run cluster:reset  # tear down and recreate
```

## Shell init: pre-commit, SSO, secrets

The `init_hook` runs on every shell entry and every `direnv` reload, so set up hooks, authenticate, and export secrets right here. Two things keep it sane: **guard the logins so they don't re-prompt** when a session is still valid, and let secret fetches **fail-open** so an unreachable Vault doesn't break the shell.

```json
"shell": {
  "init_hook": [
    "pre-commit install",
    "export AWS_PROFILE=dev-sso-profile",
    "aws sts get-caller-identity --profile $AWS_PROFILE > /dev/null 2>&1 || aws sso login --profile $AWS_PROFILE",
    "vault token lookup > /dev/null 2>&1 || vault login -method=oidc role=developer > /dev/null",
    "creds=$(vault kv get -format=json secret/myapp/dev)",
    "export DB_USERNAME=$(printf '%s' \"$creds\" | jq -r '.data.data.username')",
    "export DB_PASSWORD=$(printf '%s' \"$creds\" | jq -r '.data.data.password')",
    "unset creds"
  ],
  "scripts": {
    "test": ["task test"]
  }
}
```

(Project scripts like `test` delegate to Taskfile tasks — see [Scripts: delegate to Taskfile tasks](#scripts-delegate-to-taskfile-tasks). Secret export is *not* one of them: it must run in the `init_hook` because a script runs in a subprocess and can't set env vars in your shell.)

- **The `|| login` guard is what makes it idempotent.** `aws sts get-caller-identity` exits 0 silently while the SSO session is valid, so the browser only opens when it has actually expired. `vault token lookup || vault login` does the same for Vault — and with `-method=oidc` that Vault login rides the SSO identity you just established.
- **Fetch each Vault path once, then `jq` out the keys.** `creds=$(vault kv get -format=json …)` followed by `jq -r '.data.data.<key>'` per variable is one round-trip for the whole secret, instead of a `vault` call per env var. init_hook entries share one shell, so `creds` set on one line is visible to the lines below it — `unset` it afterwards so the raw payload doesn't linger. (`.data.data` is the KV v2 envelope; KV v1 is just `.data`.)
- **Secrets stay in the shell env only** — nothing is written to disk. This export *must* live in the `init_hook`: a `devbox run` script or `task` runs in a subprocess and can't set vars in your interactive shell. The tradeoff is a Vault round-trip on every entry; to refresh after rotating a secret, run `direnv reload` (re-runs the hook), and keep the fetch list to only what local dev actually needs.
- **Don't let Vault outages block the shell.** Append `|| true` to the export lines (or guard the whole block) if you want shell entry to succeed even when Vault is down — the dependent task fails later with a clear error instead.
- **`pre-commit install`** wires the repo's git hooks on first entry; it's a no-op when already installed.

### Make the secret rules enforceable

The `secrets` skill's "Never" list is policy; a hook is what stops a paste from becoming a commit.
Since `pre-commit install` already runs on shell entry, the scanner costs one config block:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2                  # pin; renovate/dependabot bumps it
    hooks:
      - id: gitleaks
```

Add `gitleaks` to `packages` so the hook resolves from the devbox environment rather than the
developer's machine. Run it in CI too (`task lint:secrets`) — a hook is skippable with
`--no-verify`, a required check isn't. `gitleaks detect --log-opts="--all"` scans history when you
inherit a repo and want to know what's already in there.

Put the static config (`VAULT_ADDR`, region, default profile) in `shell.env` so the hook stays short:

```json
"shell": {
  "env": {
    "VAULT_ADDR": "https://vault.example.com",
    "AWS_REGION": "eu-west-1"
  }
}
```

### Packages

Add what the hook calls to `packages`: `vault`, `pre-commit`, `gitleaks`, and the cloud SSO CLI (`awscli2`, `google-cloud-sdk`, or `azure-cli`).

### Keep it secure

- Local dev secrets come from the **same Vault paths the workload reads in-cluster** via ExternalSecret, so dev and prod resolve the same keys. The `secrets` skill owns that path convention and the `/var/run/secrets/<block>/<key>` layout — follow it rather than inventing a local-only path.
- Prefer Vault **dynamic** secrets (DB creds, cloud STS) over static KV; a leaked shell env then expires on its own.
- Never `echo` a secret value, and never write one to a committed file. When you pull the whole secret as JSON, hold it in a shell var only as long as needed and `unset` it after extracting (as above); `jq -r` emits raw values so nothing gets quoted into the env.

## When devbox isn't right

| Need | Use instead |
|---|---|
| Strict OS/glibc isolation | Dev container or VM |
| Long-running services in dev (postgres, kafka) | Run in local cluster via skaffold/helm |
| Project dependency pinning | Language lockfiles (`go.sum`, `Cargo.lock`, `package-lock.json`) |

## Companion skills — offer after completing

When devbox setup is done, check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `taskfile` | No `Taskfile.yaml` / `Taskfile.yml` in the repo root |
| `github-actions` | No `.github/workflows/`, or no `setup-tools` composite action, or its versions have drifted from `devbox.json` |
| `document` | No `docs/ARCHITECTURE.md` or README doesn't mention devbox in the quick start |

Ask as a single grouped question — not mid-task, not separately for each.
