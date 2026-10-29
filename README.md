# mentor

Opinionated platform engineering & DevSecOps skills for coding agents: Terraform, Helm, devex and
tagging conventions. Installable as a Claude Code plugin marketplace.

## Why

A platform team turns infrastructure into recipes: the decisions are made once, encoded in modules
and charts, and product teams consume the result without re-deriving it. mentor applies the same
idea to agentic workflows. Each skill is a recipe for one kind of work — a Helm chart, a Terraform
stack, a CI pipeline — that carries the house conventions with it, so an agent produces output
that has a high probability of passing the quality gates on the first try instead of after rounds
of review.

The guiding principles are the platform's:

- **Golden paths over options.** Skills prescribe one way to do a thing — directory layout, naming,
  values layering, task names — rather than surveying alternatives. Deviation is a deliberate
  choice, not an accident of what the model happened to generate.
- **One owner per contract.** A rule lives in exactly one skill and the others reference it:
  `secrets` owns the Vault path and `*_FILE` convention, `github-actions` owns SHA pinning,
  `tagging` owns the label taxonomy. Skills compose instead of drifting apart.
- **The gates are the same for agents and CI.** Every check runs through a Taskfile task
  (`task check`, `task lint`, ...) that CI also calls, so an agent verifies its work with exactly
  the gates the pull request will face.
- **Abstract the mechanics, not the judgement.** Skills scaffold, validate and review; they do not
  apply infrastructure or push to production. `terraform` stops at plan, deploys go through
  GitOps.

## Install

```sh
/plugin marketplace add pampatzoglou/mentor
/plugin install mentor@mentor     # skills
/plugin install personas@mentor   # persona slash commands (optional)
```

## Skills

| Area | Skills |
|---|---|
| Infrastructure | `terraform`, `ansible`, `tagging`, `secrets` |
| Workloads & delivery | `helm`, `kubernetes`, `argo-applicationset`, `dockerfile`, `docker-compose`, `skaffold` |
| CI & dev environment | `ci`, `github-actions`, `taskfile`, `devbox` |
| Repo lifecycle | `bootstrap`, `housekeeping`, `tidy`, `prune`, `document`, `git` |
| Design & review | `architecture`, `platform-review`, `debugging` |

Entry points: `bootstrap` scaffolds a new repo, `housekeeping` brings an existing one up to the
conventions, and `platform-review` reviews a change by dispatching to the skills it touches.

## Personas

Skills carry the method; personas carry the judgement — how much of the method a question needs
and whose call it is. Each persona owns a slice of the work and hands off the rest by name, so a
question about replica lag goes to `dba`, not `devops`.

`architect`, `cloud`, `data`, `dba`, `devops`, `dx`, `housekeeper`, `pm`, `qa`,
`security-architect`, `sre`, `staff`

Invoke as `/personas:<name> [task]`, e.g. `/personas:sre review the alerting for checkout`.

## Layout

```
.claude-plugin/
  marketplace.json          # marketplace catalog — lists every plugin below
plugins/
  mentor/                   # core skills plugin
    .claude-plugin/plugin.json
    skills/
      <skill-name>/
        SKILL.md            # required: frontmatter + instructions, under 500 lines
        <topic>.md          # optional: reference material loaded on demand
        assets/             # optional: template files under plain names (gitignore, Taskfile.yml)
    evals/                  # prompt → expected-skill routing cases (claude plugin eval)
    LICENSE, NOTICE         # copies of the root files; only the plugin directory ships
  personas/                 # persona slash commands
    .claude-plugin/plugin.json
    commands/
      <persona>.md
templates/
  skill/SKILL.md            # starting point for a new skill
scripts/lint-skills.py      # frontmatter, size, TOC, link and licensing lint
Taskfile.yml                # task check — the same gates CI runs
```

`metadata.requires` lists the skills a skill builds on, space-separated. Claude Code does not
enforce it; it documents the dependency graph, and `task lint` checks every name exists. Skills ship in one plugin so installing one always brings its dependencies.

## Adding a skill

1. `cp -r templates/skill plugins/mentor/skills/<skill-name>`
2. Set `name` to match the directory. Write the `description` as what the skill does plus when to
   use it (`Use when ...`, `Triggers on ...`) — it is all the model sees when choosing a skill.
   Add a case under `plugins/mentor/evals/` for the prompt that should route to it.
3. If the skill introduces a rule, make it the owner and have other skills reference it rather
   than restate it.
4. Bump `version` in `plugins/mentor/.claude-plugin/plugin.json`.
5. Run `task check:static` (validate + lint), then `task eval` for the routing evals.

## Checks

| Task | Runs |
|---|---|
| `task validate` | `claude plugin validate` on the marketplace and the mentor plugin |
| `task lint` | `name` matches the directory; `description` ≤ 1024 chars with a when-clause; `license` present; body < 500 lines; reference files > 100 lines have a `## Contents`; links resolve; no dotfiles in skills; plugin `LICENSE`/`NOTICE` match the root |
| `task eval` | prompt → expected-skill cases in `plugins/mentor/evals/`, 3 runs each, a case passes at ≥ 2/3 |
| `task check` | all of the above |

CI (`.github/workflows/check.yml`) runs `task check:static` on every PR and `task eval` when the
`ANTHROPIC_API_KEY` secret is available.

## License

Apache-2.0. Copyright 2026 Pantelis Ampatzoglou — see `LICENSE` and `NOTICE`.
