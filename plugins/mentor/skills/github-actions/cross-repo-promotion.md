# GitHub Actions — Cross-repo promotion (service repo → GitOps repo)

Companion to `SKILL.md` (foundations: core pattern, security, matrix, caching). This file covers the **merge-time** deploy half of Kubernetes delivery: moving a freshly built image tag from a **service repo** into the separate **GitOps repo** ArgoCD watches. For the **PR-time** checks (lint/template/audit) see `kubernetes-ci.md`.

The service repo owns the chart definitions under `deploy/charts/`; the promotion job syncs them into the GitOps repo's deploy branch, bumps `image.tag` in the target environment's values layer, then opens and auto-merges a PR.

## Pick one topology — these two are mutually exclusive

There are two supported GitOps layouts, and a repo must use exactly one:

| Topology | Where ArgoCD looks | Use this file? |
|---|---|---|
| **Same-repo** — `main` holds source, a `deploy` branch holds CI-updated values | `deploy/argo/` + `deploy/charts/` in the service repo, `targetRevision: deploy` | No. Have CI commit the tag bump to the `deploy` branch of this repo; see the `argo-applicationset` skill's `targetRevision` section |
| **Separate GitOps repo** — this file | `deploy/charts/` in the GitOps repo; ApplicationSets still in the service repo's `deploy/argo/` | Yes |

Running both means two sources of truth for the same charts and a permanent sync fight. Confirm which one the repo uses before wiring anything — the `ci` skill asks this during analysis.

Flow: `build-push` → mint App token → checkout GitOps repo → sync `deploy/` + bump tags → commit on a throwaway branch → PR → squash-merge → ArgoCD syncs on its own.

## Credentials: one scoped App token, nothing else

The default `GITHUB_TOKEN` can't write to another repo. Mint a short-lived, repo-scoped token with `actions/create-github-app-token` and use it for **every** cross-repo operation — checkout, push, `gh pr create`, `gh pr merge`. Don't mix in a long-lived PAT.

| App token over PAT | Why |
|---|---|
| Short-lived | Expires in ~1h, auto-rotated — no static secret to leak |
| Scoped | Limited to the installation; `repositories:` narrows it to just the GitOps repo |
| Attributable | Commits/PRs show as the app, not someone's personal PAT |
| Triggers downstream CI | Pushes authenticated by an App token (or PAT) trigger the target repo's workflows; pushes by the default `GITHUB_TOKEN` do **not** |

**Gotcha — which credential actually pushes.** `actions/checkout` persists the token it was given (default `persist-credentials: true`), so a later `git push` in that checkout authenticates with the **App token automatically** — `git push` does *not* read `GH_TOKEN`. Only the `gh` CLI reads `GH_TOKEN`. Setting `GH_TOKEN: ${{ secrets.SOME_PAT }}` on the push step does nothing and masks which credential is really in use. Set `GH_TOKEN` to the App token **only on `gh` steps**, and let checkout handle the push.

**One-time App setup:** install the GitHub App on the GitOps repo with **Contents: write** and **Pull requests: write**, then store its Client ID and private key as `RELEASE_BOT_CLIENT_ID` and `RELEASE_BOT_PRIVATE_KEY` secrets in the service repo.

## Keep it DRY — iterate charts, don't enumerate services

Bumping each chart with its own copy-pasted `yq` line (and repeating the service list in the commit message and PR body) rots the instant a service is added or removed. Iterate the charts directory once and derive the service list from it — the job stays correct as services come and go.

## Canonical promotion job

```yaml
  deploy-dev:
    name: Deploy to dev
    runs-on: ubuntu-latest
    needs: [build-push]
    timeout-minutes: 5
    # Promote only from the default branch, after a successful build.
    if: github.ref == format('refs/heads/{0}', github.event.repository.default_branch)
    permissions:
      id-token: write     # OIDC, only if a prior step needs cloud auth
      contents: read      # cross-repo writes use the App token, NOT GITHUB_TOKEN
    env:
      ENVIRONMENT: dev
      GITOPS_REPO: my-org/gitops    # the repo ArgoCD watches
      GITOPS_BRANCH: deploy
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1 — service repo, owns deploy/ chart definitions

      # 1. Mint a short-lived, repo-scoped token — the ONLY credential for cross-repo writes.
      - name: Mint app token
        id: app-token
        uses: actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510 # v3.3.0
        with:
          client-id: ${{ secrets.RELEASE_BOT_CLIENT_ID }}
          private-key: ${{ secrets.RELEASE_BOT_PRIVATE_KEY }}
          owner: ${{ github.repository_owner }}
          repositories: gitops        # least privilege within the installation

      # 2. Check out the GitOps repo/branch beside the service repo (token persisted for the push).
      - name: Checkout GitOps repo
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          repository: ${{ env.GITOPS_REPO }}
          ref: ${{ env.GITOPS_BRANCH }}
          path: .gitops
          token: ${{ steps.app-token.outputs.token }}

      # 3. Compute the image tag once and expose it (matches build-push: short SHA).
      - name: Compute image tag
        id: tag
        run: echo "value=${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"

      # 4. Sync chart definitions in from the service repo, then bump every chart's image tag.
      - name: Update chart values
        working-directory: .gitops
        env:
          IMAGE_TAG: ${{ steps.tag.outputs.value }}
        run: |
          set -euo pipefail
          git config user.name  "${{ github.actor }}"
          git config user.email "${{ github.actor }}@users.noreply.github.com"
          git switch -c "deploy-${ENVIRONMENT}-${{ github.run_id }}"

          # Sync chart definitions only. deploy/argo/ stays in the service repo —
          # the platform app-of-apps reads ApplicationSets from there (see the
          # `argo-applicationset` skill). Copying them here would create a second
          # live copy of the same ApplicationSet resources.
          mkdir -p deploy/charts
          rsync -a --delete ../deploy/charts/ deploy/charts/

          # Bump image.tag in the PER-ENVIRONMENT layer, never defaults/.
          # defaults/ is "true for every cluster deployment" (see the `helm` skill), so
          # writing the tag there means promoting dev also retags prod — every
          # environment would ship whatever was built last.
          for chart in deploy/charts/*/; do
            [ -f "${chart}Chart.yaml" ] || continue
            f="${chart}${ENVIRONMENT}/values.yaml"
            mkdir -p "${chart}${ENVIRONMENT}"
            [ -f "$f" ] || echo '{}' > "$f"
            yq eval ".image.tag = \"$IMAGE_TAG\"" -i "$f"
            echo "  bumped ${chart} (${ENVIRONMENT}) -> $IMAGE_TAG"
          done

          git add -A
          git diff --cached --stat

      # 5. Commit, push, PR, and auto-merge — all on the App token.
      - name: Open and merge promotion PR
        working-directory: .gitops
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}   # gh reads this; git push uses persisted creds
          IMAGE_TAG: ${{ steps.tag.outputs.value }}
        run: |
          set -euo pipefail
          branch="deploy-${ENVIRONMENT}-${{ github.run_id }}"

          # Derive the service list once; reuse for commit message + PR body.
          services="$(ls -d deploy/charts/*/ | xargs -n1 basename | sed 's/^/- /')"
          {
            echo "## Automated ${ENVIRONMENT} promotion"
            echo
            echo "**Image tag:** \`$IMAGE_TAG\`"
            echo
            echo "### Services"
            echo "$services"
            echo
            echo "- Triggered by: @${{ github.actor }}"
            echo "- Source: ${{ github.repository }}@${{ github.sha }}"
            echo "- Run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
          } > /tmp/pr-body.md

          git commit -m "Promote ${ENVIRONMENT}: images -> $IMAGE_TAG" -F /tmp/pr-body.md
          git push -u origin "$branch"

          gh pr create --repo "$GITOPS_REPO" \
            --base "$GITOPS_BRANCH" --head "$branch" \
            --title "Promote ${ENVIRONMENT}: images -> $IMAGE_TAG" \
            --body-file /tmp/pr-body.md

          # --auto waits for the GitOps repo's branch-protection checks; drop it to merge immediately.
          gh pr merge "$branch" --repo "$GITOPS_REPO" --squash --delete-branch --auto
```

## Notes

- **Naming consistency:** drive branch, commit, and PR text off the single `ENVIRONMENT` var so a "dev" job never emits "staging" artifacts.
- **`--auto` vs immediate:** `--auto` enables auto-merge and waits for the target repo's required checks; without it, the merge happens now (the PR must be mergeable, or the token must have admin/bypass).
- **One job per environment** sharing this shape via `ENVIRONMENT`, or a matrix if the steps are byte-identical. Gate higher environments behind a GitHub Environment with required reviewers.
- **ArgoCD owns the last mile:** the job ends at merge. ArgoCD picks up the merged commit via its own poll/webhook — the workflow never calls ArgoCD directly.

## Common failures

| Symptom | Cause |
|---|---|
| Push to the GitOps repo `403` | App not installed on the target repo, missing Contents: write, or token not scoped to it |
| `gh pr merge --auto` errors | Auto-merge not enabled on the target repo, or no required checks — drop `--auto` to merge immediately |
| Push appears to work but uses the wrong identity | `git push` uses checkout's persisted token, not `GH_TOKEN` — set the App token on the checkout step |
