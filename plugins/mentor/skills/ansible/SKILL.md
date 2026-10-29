---
name: ansible
description: 'Author, review and run Ansible roles and playbooks in the house style: one role = one inventory group = one play, install/configure/service/verify task split, `<role>_` variable prefix, `<role>:<phase>` tags, drop-in integration with Alloy / Prometheus rules / Falco / nftables / logrotate / Traefik / Grafana / Vault Agent tracked by `<role>_*_applied` facts and removed by a cleanup play, checksum-verified upstream binaries pinned for Renovate, and Molecule scenarios with systemd-in-Docker. Use whenever a task touches roles/, playbooks/, inventory/, group_vars/host_vars, molecule/, ansible.cfg, ansible-lint, or asks to add a role/server type, wire a role into monitoring, or run check/provision/verify.'
requires: [taskfile, devbox]
---

# Ansible (fleet provisioning)

Distilled from `provision-server` (pampatzoglou). The repo's own `docs/CONVENTIONS.md`,
`docs/ANSIBLE.md` and `docs/DEPENDENCIES.md` are authoritative when present; read them first and
change them in the same change when a rule moves. `patterns.md` (next to this file) holds the
copy-paste task blocks for every integration.

## Operational boundary

- ✅ Freely: `task lint`, `task syntax`, `task inventory`, `task test ROLE=<role>` (Docker),
  `task check -- --limit <host>` (dry run + diff), `task verify` (read-only health checks),
  `task ping`.
- ⚠️ Ask first: `task provision`, any `ansible-playbook` without `--check`, `task tf:apply`,
  `task packer:build`. These change real hosts (the NAS holds the only copy of some data).
- Prefer `task` targets over raw `ansible-playbook`; they pin the inventory directory and run
  `task deps` (collections into `.ansible/collections`). Extra args go after `--`.

## Layout and naming

```
ansible.cfg              inventory=./inventory, roles_path=./roles, collections in .ansible/
inventory/hosts.yml      hosts + provision_roles: [...]   (per-host role list)
inventory/roles.yml      constructed plugin: each provision_roles entry -> group of same name
inventory/group_vars/    all.yml
inventory/host_vars/     <host>.yml (real hosts git-ignored; example.yml tracked)
playbooks/default.yml    everything: base -> vm -> databases -> monitoring -> traefik ->
                         services -> backups -> cleanup (last)
playbooks/<entry>.yml    base, databases, monitoring, services, backups: import_playbook lists
playbooks/plays/<r>.yml  one play per role/group
roles/<r>/               one role per server type or agent
molecule/site/           integration scenario; roles/<r>/molecule/default/ per role
```

One server type = one role = one group = one play:

| Thing          | Value |
|----------------|-------|
| Role           | `roles/<r>/` (snake_case, e.g. `doco_cd`, `mikrotik_monitor`) |
| Group          | `<r>`, produced by listing `<r>` in the host's `provision_roles` |
| Play           | `playbooks/plays/<r>.yml`, imported from the entry playbook it belongs to |
| Vars           | every variable `<r>_` prefixed (ansible-lint `var-naming` enforces) |
| Registers/facts| also `<r>_` prefixed: `<r>_installed`, `<r>_tmp`, `<r>_verify_unit` |
| Tags           | `<r>`, `<r>:install`, `<r>:configure`, `<r>:service`, `<r>:verify` + `verify` |
| Handlers       | `Restart <r>`, `Reload <r>`, `Reload systemd`, `Reload alloy`, … |

Play template (base.yml is the only one with plain `hosts: all`-style targeting):

```yaml
---
- name: Provision <r> servers
  hosts: "{{ provision_target | default('all') }}:&<r>"
  become: true
  roles:
    - role: <r>
```

Baseline roles (every host, `playbooks/base.yml`, order matters): firewall → alloy → updates →
packages → chrony → falco → logging → sshd → tailscale → docker → compose. Firewall first and
Falco early because later roles' drop-ins are validated against them; Alloy before anyone drops a
`<role>.alloy`.

Ordering in `default.yml` is deliberate and commented: databases before monitoring (rules in place
when Prometheus starts), Traefik after base (Docker socket), cleanup **last**. Keep a one-line
"why" comment on every ordering constraint you add.

## Role anatomy

```
defaults/main.yml   public interface; header comment "Public interface of the <r> role…";
                    every knob commented with WHY / units / what false means
vars/main.yml       internal constants only ("not meant to be overridden"): arch maps, asset
                    names, derived paths
tasks/main.yml      import_tasks only (no logic), each tagged; optional leading assert
tasks/install.yml   packages, repos, users, dirs, upstream binary
tasks/configure.yml templates + every integration drop-in; notify on change
tasks/service.yml   systemd enable/start; ends with meta: flush_handlers
tasks/verify.yml    read-only checks, fail the play when broken; skipped in check mode
tasks/cleanup.yml   only on agent roles that own a drop-in directory (alloy, firewall, falco…)
handlers/main.yml
templates/          <r>.service.j2, <r>.alloy.j2, <r>.falco.yaml.j2, <r>.nft.j2,
                    <r>.traefik.yml.j2, <r>.grafana.yaml.j2, <r>.apparmor.j2, logrotate.j2
files/<r>.rules.yml Prometheus alert rules
meta/main.yml       galaxy_info (namespace provision, GPL-3.0-only, Ubuntu noble,
                    min_ansible_version "2.17") + dependencies: [alloy] for most roles
molecule/default/   molecule.yml, create.yml, destroy.yml, converge.yml, [prepare.yml], verify.yml
README.md           prose bullets: what it does, off switches, monitoring, ops runbook
```

`tasks/main.yml` shape:

```yaml
---
- name: Check the role's settings
  ansible.builtin.assert:
    that:
      - not <r>_enabled | bool or <r>_thing | length > 0
    fail_msg: >-
      Set <r>_thing (…) for this host.
    quiet: true
  tags: [always]

- name: Install
  ansible.builtin.import_tasks: install.yml
  tags: [<r>, <r>:install]

- name: Configure
  ansible.builtin.import_tasks: configure.yml
  tags: [<r>, <r>:configure]

- name: Service
  ansible.builtin.import_tasks: service.yml
  tags: [<r>, <r>:service]

- name: Verify
  ansible.builtin.import_tasks: verify.yml
  tags: [<r>, <r>:verify, verify]
```

Extra phases get their own file and tag (`disk.yml` → `<r>:disk`, `exporter.yml` →
`<r>:exporter`), gated with `when: <r>_x_enabled | bool` on the import.

**Role weight:** utility roles (packages, chrony-like) stay lean. Daemon and runtime roles get
Alloy / Prometheus rules / Falco / firewall / Grafana integrations only where a real signal
exists — don't add empty drop-ins for symmetry.

## Integration contract (drop-ins + applied facts + cleanup)

A role **never edits another role's config**. It drops its own file into the other component's
directory, then sets a fact so `playbooks/plays/cleanup.yml` knows it is still applied. Files of
roles that no longer ran are removed at the end of `default.yml`.

| Integration | Source in role | Destination | Validate | Fact |
|---|---|---|---|---|
| Alloy | `templates/<r>.alloy.j2` | `{{ alloy_config_dir }}/<r>.alloy` (root:`alloy_group` 0640) | `{{ alloy_binary_path }} fmt %s` | `<r>_alloy_config_applied` |
| Prometheus rules | `files/<r>.rules.yml` | `/etc/prometheus/rules/` (dir dest) | `promtool check rules %s` if present | `<r>_prometheus_rules_applied` |
| Falco | `templates/<r>.falco.yaml.j2` | `/etc/falco/rules.d/<r>.yaml` | `/usr/bin/falco -V %s` if present | `<r>_falco_rules_applied` |
| nftables | `templates/<r>.nft.j2` | `/etc/nftables.d/<r>.nft` | `nft -c -f %s` if present | `<r>_firewall_applied` |
| logrotate | `templates/logrotate.j2` | `/etc/logrotate.d/<r>` | `logrotate --debug %s` | `<r>_logrotate_applied` |
| Traefik | `templates/<r>.traefik.yml.j2` | `{{ traefik_config_dir }}/dynamic/<r>.yml` | — | (removed when `<r>_traefik_host` empty) |
| Grafana DS | `templates/<r>.grafana.yaml.j2` | `/etc/grafana/provisioning/datasources/<r>.yaml` | — | `<r>_grafana_datasource_applied` |
| Grafana dash | `include_role grafana tasks_from: dashboards.yml` | `/etc/grafana/dashboards/<r>/` | — | `<r>_grafana_dashboards_applied` |
| Vault Agent | `templates/<r>.vault-agent.hcl.j2` (`[[ ]]` delimiters) | `{{ vault_agent_config_dir }}/<r>.hcl` | — | `<r>_vault_agent_config_applied` |
| AppArmor | `templates/<r>.apparmor.j2` | prepared, **not deployed** (`<r>_apparmor_mode: complain`) | — | — |

Rules for every drop-in:

- Marker comment at the top: `# provision: role=<r>` (Falco, nft, logrotate, Grafana DS) plus
  `{{ ansible_managed }}`. The cleanup tasks `find … contains: "^# provision: role="`.
- **Target the component on this host**: `inventory_hostname in groups['<x>'] | default([])` OR
  its directory already exists (`stat`). A Prometheus on another host does not get the rules.
- Create the destination directory yourself (roles that run earlier still need it); when the
  owning role sets owner/mode, leave them out and add `# noqa: risky-file-permissions` with a
  comment saying why ("must not fight this task over them").
- Validate with the owning tool when it is installed, else `omit`:
  `validate: "{{ '/usr/sbin/nft -c -f %s' if <r>_nft_bin.stat.exists else omit }}"`.
- Notify via shared listen names: `Reload alloy`, `Reload firewall rules`,
  `Reload prometheus rules` (role-local handler pair that checks the unit is active first, then
  reloads — see `patterns.md`), `Restart grafana for data sources`.
- Cleanup only runs on untagged full runs (`ansible_run_tags == ['all']` and no skip tags).
  `default.yml --limit <host>` is the one-host run that still cleans up.
- Alloy is a meta dependency of most roles but guards itself with `alloy_applied` +
  `meta: end_role`, so it executes once per run while its defaults and handlers stay loaded.

## Task style

- FQCN always (`ansible.builtin.*`, `community.general.*`, `ansible.posix.*`). ansible-lint
  `production` profile.
- Task names are sentences in the imperative / "Ensure …" / "Check …" / "Assert …" form.
- `command` uses `argv:` lists, never shell strings; every `command`/`shell` has `changed_when`,
  `creates`, or a guard. Probing commands: `changed_when: false`, `failed_when: false`,
  `check_mode: false`.
- Handlers for restarts, never `register` + `when: x.changed`. `meta: flush_handlers` at the end
  of `service.yml` so verify sees the new state.
- `systemd_service` (not `systemd`/`service`), with `daemon_reload: true` where units changed.
- Generated secrets: `copy` with `lookup('ansible.builtin.password', '/dev/null', …)`,
  `force: false`, `no_log: true`, root 0600 under `/etc/credstore/<r>/`, handed to units with
  `LoadCredential`. Never commit secrets; never regenerate an existing one.
- Destructive steps refuse rather than guess (e.g. assert a repo dir is empty before `init`;
  never format disks — mount by UUID with `nofail`, disks referenced by `/dev/disk/by-id/`).
- File modes quoted strings (`"0644"`); yamllint forbids implicit/explicit octal.
- Loops: `loop_control: label:` with something short.
- YAML: block maps/lists for anything nested — `labels:\n  severity: warning`, not
  `labels: { severity: warning }`. Short flow lists are fine (`[jq]`, `tags: [r, r:install]`).
- 100-char lines; long lines that can't break get `# yamllint disable-line rule:line-length`.
- Comments explain **why** (constraint, upstream quirk, ordering), never restate the task name.
  Prose is plain and complete: "Read by the cleanup play: without it, <file> is removed."

## verify.yml

Read-only, runs on every play (and alone via `--tags verify` / `task verify`):

```yaml
- name: Check <r>
  when: not ansible_check_mode
  block:
    - name: Read the <r> unit status
      ansible.builtin.systemd_service:
        name: <r>.service
      register: <r>_verify_unit

    - name: Assert <r> is running
      ansible.builtin.assert:
        that: <r>_verify_unit.status.ActiveState == 'active'
        fail_msg: >-
          <r> is {{ <r>_verify_unit.status.ActiveState }}; check `journalctl -u <r>`.
        quiet: true

    - name: Wait for <r> to answer
      ansible.builtin.uri:
        url: "http://{{ <r>_listen_address }}/-/ready"
      register: <r>_verify_http
      until: <r>_verify_http.status | default(0) == 200
      retries: 30
      delay: 2
```

Check setup, not outcomes: "whether backups succeed is the alerts' job". Failure messages tell
the operator what to run next.

## Upstream binaries (GitHub releases)

1. `command: <bin> --version` → `<r>_installed` (changed_when/failed_when false, check_mode
   false); skip the install block when the version string matches.
2. `ansible.builtin.tempfile: state: directory` → download there; remove in `always:`.
3. `get_url` with `checksum: "sha256:{{ url }}/SHA256SUMS"` (or a pinned `sha256:` literal when
   upstream publishes none — say so in a comment).
4. Install to `/usr/local/bin` (`unarchive`/`community.general.decompress`), notify restart.
5. Pin in `defaults/main.yml`, bare version (no `v`), Renovate comment directly above:

```yaml
# renovate: datasource=github-releases depName=restic/restic
restic_version: "0.19.1"
```

Arch via `vars/main.yml`: `<r>_arch_map: {x86_64: amd64, aarch64: arm64}` indexed with
`ansible_facts['architecture']`. apt repos use `datasource=deb … registryUrl=…`.
Collections are pinned in `requirements.yml` (Renovate too).

## Prometheus alert rules (`files/<r>.rules.yml`)

- Group name `<r>`; header comment "Prometheus alert rules owned by the <r> role…".
- `labels:` block style: `severity` (`warning`/`critical`), `service: <r>`, and domain labels
  where they help (e.g. `backup_job`). The same alertname is reused across tools that do the
  same job (restic and rustic both raise `BackupTooOld`), distinguished by `service`.
- `summary: "{{ $labels.host }}: …"` (`host` is Alloy's external label); `description` says
  the impact and the command to run.
- Log/profile label naming: `service` (not Loki `service_name`), `level` (`warn`).

## Molecule

- Per role `roles/<r>/molecule/default/`, self-contained: `molecule.yml` with the `default`
  driver (`managed: true`) and its own `create.yml`/`destroy.yml` that drive the docker CLI
  (`--privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw`, systemd as PID 1, wait on
  `systemctl is-system-running --wait` in running/degraded) and write the inventory with
  `community.docker.docker` connection. Copy them from an existing role, don't reinvent.
- Image `geerlingguy/docker-ubuntu2404-ansible`, platform `ubuntu-noble`.
- `ANSIBLE_ROLES_PATH: ${MOLECULE_PROJECT_DIRECTORY}/..`, galaxy deps from the root
  `requirements.yml`. Container-specific overrides go in the provisioner's
  `inventory.group_vars.all` with a comment (e.g. `chrony_daemon_opts: "-x"`).
- `prepare.yml` mocks only what the role expects other roles to provide (dirs, files).
- Test sequence includes `idempotence`; `verify.yml` asserts the role's real effect.
- `molecule/site/` runs `default.yml` on one host per group and checks cross-role behaviour
  (combined Alloy config, Falco loads every rules file, cleanup of removed roles).
- `scripts/molecule.sh` builds the CI matrix; heavy/multi-node scenarios go in its `DISABLED`.
- POC scope: keep breadth; don't chase environment-specific Molecule failures (nested
  virtualization, kernel modules) — note the limitation in the scenario and move on.

## Adding a role / server type

1. Copy the closest existing role (lean utility → `chrony`; daemon with integrations →
   `alertmanager`/`restic`), rename prefix, tags, handlers, templates, `meta.role_name`.
2. `defaults/main.yml`: all knobs, safe defaults, `<r>_enabled`-style off switches, version pin
   with `# renovate:`.
3. `playbooks/plays/<r>.yml` (template above); import it from the right entry playbook with a
   comment on ordering. It must run before cleanup.
4. Add `<r>` to `provision_roles` of the host(s) in `inventory/hosts.yml`; host-specific values
   in `host_vars/<host>.yml`.
5. Integrations from the table, only those with real signal; for each, the applied fact. If you
   add a new *kind* of drop-in, extend `playbooks/plays/cleanup.yml` (or the owning role's
   `tasks/cleanup.yml`).
6. Molecule scenario; `README.md`; update the role tables in `README.md` / `docs/ANSIBLE.md`.
7. `task lint syntax && task test ROLE=<r>`; then `task check -- --limit <host>`.

## Review checklist

- [ ] Every var/register/fact `<r>_`-prefixed; tags on every import; `verify` tag on verify.
- [ ] No logic in `tasks/main.yml` beyond imports and the settings assert.
- [ ] Idempotent: second run reports no changes (commands guarded, `force: false` for one-shot
      generated files).
- [ ] Every drop-in: marker comment, host targeting, validate-or-omit, notify, applied fact.
- [ ] No edits to another role's files; meta deps only where truly required (alloy).
- [ ] Upstream downloads checksum-verified, tempdir + `always` cleanup, Renovate pin.
- [ ] verify.yml read-only, skipped in check mode, actionable `fail_msg`.
- [ ] No secrets in tracked files (`host_vars/<real host>.yml` is git-ignored; still prefer
      vault/`-K` over plaintext `ansible_become_password`).
- [ ] Docs updated in the same change (role README, docs/ tables, CONVENTIONS if a rule moved).

## Repo-specific notes (provision-server)

- Active playbooks: `default.yml` and `services.yml` (plus the entries it imports). Ignore
  `sandbox.yml` and anything marked old.
- Docs may lag the code: `README.md`/`CONVENTIONS.md` still mention
  `inventories/<env>/terraform.py` and `group_vars/<type>.yml`; the live setup is `inventory/`
  with `provision_roles` + the constructed `roles.yml` (see `ansible.cfg`, `Taskfile.yml`). Trust
  `ansible.cfg` and `Taskfile.yml`; fix the docs when you touch them.
- Terraform (`terraform/modules/<platform>`) creates VMs, waits on cloud-init, runs
  `default.yml` once via the ansible provider, and registers `ansible_host`s. Packer bakes the
  base play into the Proxmox template.
