# Ansible integration patterns (copy-paste)

Replace `<r>` with the role name. Each block lives in `tasks/configure.yml` unless noted.

## Alloy config

```yaml
- name: Write <r> Alloy config
  ansible.builtin.template:
    src: <r>.alloy.j2
    dest: "{{ alloy_config_dir }}/<r>.alloy"
    owner: root
    group: "{{ alloy_group }}"
    mode: "0640"
    validate: "{{ alloy_binary_path }} fmt %s"
  notify: Reload alloy

# Read by the cleanup play: without it, <r>.alloy is removed.
- name: Mark <r> Alloy config as applied
  ansible.builtin.set_fact:
    <r>_alloy_config_applied: true
```

Template header: `// {{ ansible_managed }}` then a comment naming what it collects; forward
metrics to `prometheus.relabel.default.receiver` (from the alloy role's config.alloy), set `job`
via `discovery.relabel`. Journal logs are already shipped by the base pipeline.

## Prometheus rules

```yaml
# Alert rules go to the Prometheus on this host: one in the prometheus group, or already
# installed. Checked with promtool where Prometheus is installed.
- name: Check for a Prometheus rules directory
  ansible.builtin.stat:
    path: "{{ prometheus_config_dir | default('/etc/prometheus') }}/rules"
  register: <r>_prometheus_rules_dir

- name: Check for promtool
  ansible.builtin.stat:
    path: "{{ prometheus_binary_dir | default('/usr/local/bin') }}/promtool"
  register: <r>_promtool_bin

- name: Install <r> Prometheus rules
  when: >-
    inventory_hostname in groups['prometheus'] | default([])
    or <r>_prometheus_rules_dir.stat.exists
  block:
    # No owner or mode: the prometheus role sets them, and must not fight this task over them.
    - name: Ensure Prometheus rules directory exists  # noqa: risky-file-permissions
      ansible.builtin.file:
        path: "{{ prometheus_config_dir | default('/etc/prometheus') }}/rules"
        state: directory

    - name: Write <r> Prometheus rules
      ansible.builtin.copy:
        src: <r>.rules.yml
        # A directory: the file keeps its name, <role>.rules.yml.
        dest: "{{ prometheus_config_dir | default('/etc/prometheus') }}/rules/"
        owner: root
        group: root
        mode: "0644"
        validate: >-
          {{ <r>_promtool_bin.stat.path ~ ' check rules %s'
             if <r>_promtool_bin.stat.exists else omit }}
      notify: Reload prometheus rules

    # Read by the cleanup play: without it, the rules file is removed.
    - name: Mark <r> Prometheus rules as applied
      ansible.builtin.set_fact:
        <r>_prometheus_rules_applied: true
```

Handlers (`handlers/main.yml`), role-local so the role works without the prometheus role loaded:

```yaml
# Only acts while Prometheus runs: a role applied before the prometheus role leaves its rules for
# Prometheus to load when it starts. SIGHUP (ExecReload) re-reads the rule files.
- name: Check whether prometheus runs
  ansible.builtin.systemd_service:
    name: prometheus.service
  register: <r>_prometheus_unit
  failed_when: false
  listen: Reload prometheus rules

- name: Reload prometheus for new rules
  ansible.builtin.systemd_service:
    name: prometheus.service
    state: reloaded
  when: <r>_prometheus_unit.status.ActiveState | default('') == 'active'
  listen: Reload prometheus rules
```

Rules file:

```yaml
---
# Prometheus alert rules owned by the <r> role, installed by it into /etc/prometheus/rules/
# on hosts running Prometheus.
# `host` is the external label every series gets from Alloy's config.alloy.
groups:
  - name: <r>
    rules:
      - alert: <Thing>Down
        expr: up{job="<r>"} == 0
        for: 5m
        labels:
          severity: critical
          service: <r>
        annotations:
          summary: "{{ $labels.host }}: <r> is down"
          description: >-
            What breaks for whom, and the first command to run (`journalctl -u <r>`).
```

## Falco rules

```yaml
# Created here too: roles that run before Falco is installed still need it, and an empty
# directory is harmless on a host without Falco.
- name: Ensure Falco rules directory exists
  ansible.builtin.file:
    path: /etc/falco/rules.d
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Check for Falco
  ansible.builtin.stat:
    path: /usr/bin/falco
  register: <r>_falco_bin

# Falco hot-reloads rules.d. Validated by Falco itself where it is installed.
- name: Write <r> Falco rules
  ansible.builtin.template:
    src: <r>.falco.yaml.j2
    dest: /etc/falco/rules.d/<r>.yaml
    owner: root
    group: root
    mode: "0644"
    validate: "{{ '/usr/bin/falco -V %s' if <r>_falco_bin.stat.exists else omit }}"

# Read by the cleanup play at the end of default.yml: without it, the rules file is removed.
- name: Mark <r> Falco rules as applied
  ansible.builtin.set_fact:
    <r>_falco_rules_applied: true
```

Template: `# {{ ansible_managed }}`, `# provision: role=<r>`, self-contained macros prefixed
`<r>_` (so the file validates without the default ruleset), `tags: [provision, <r>, …]`.

## nftables (inbound ports)

```yaml
# Created here too: roles that run before the firewall role still need it, and an empty
# directory is harmless on a host without nftables.
- name: Ensure firewall rules directory exists
  ansible.builtin.file:
    path: /etc/nftables.d
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Check for nftables
  ansible.builtin.stat:
    path: /usr/sbin/nft
  register: <r>_nft_bin

# Checked on its own with `nft -c` where nftables is installed; the firewall role checks the
# whole ruleset when it writes it.
- name: Write <r> firewall rules
  ansible.builtin.template:
    src: <r>.nft.j2
    dest: /etc/nftables.d/<r>.nft
    owner: root
    group: root
    mode: "0644"
    validate: "{{ '/usr/sbin/nft -c -f %s' if <r>_nft_bin.stat.exists else omit }}"
  notify: Reload firewall rules

# Read by the cleanup play at the end of default.yml: without it, the rules file is removed.
- name: Mark <r> firewall rules as applied
  ansible.builtin.set_fact:
    <r>_firewall_applied: true
```

Allowed sources come from `<r>_firewall_allow: []` (CIDRs) in defaults, set per host.

## logrotate (only for file logs; journald is the default)

```yaml
- name: Write <r> logrotate policy
  when: <r>_logrotate_paths | length > 0
  block:
    - name: Install logrotate
      ansible.builtin.apt:
        name: [logrotate]
        state: present
        update_cache: true
        cache_valid_time: 3600

    - name: Write <r> logrotate policy for its file logs
      ansible.builtin.template:
        src: logrotate.j2
        dest: /etc/logrotate.d/<r>
        owner: root
        group: root
        mode: "0644"
        validate: /usr/sbin/logrotate --debug %s

    # Read by the cleanup play at the end of default.yml: without it, the policy is removed.
    - name: Mark <r> logrotate policy as applied
      ansible.builtin.set_fact:
        <r>_logrotate_applied: true

- name: Remove <r> logrotate policy
  ansible.builtin.file:
    path: /etc/logrotate.d/<r>
    state: absent
  when: not (<r>_logrotate_paths | length > 0)
```

Defaults: `<r>_logrotate_paths: []`, `<r>_logrotate_frequency: daily`, `<r>_logrotate_rotate: 7`.

## Traefik route

```yaml
# A route on Traefik (file provider) when <r>_traefik_host is set and this host runs
# Traefik: in the traefik group, or with its dynamic configuration directory already there.
- name: Check for Traefik's dynamic configuration directory
  ansible.builtin.stat:
    path: "{{ traefik_config_dir | default('/etc/traefik') }}/dynamic"
  register: <r>_traefik_dynamic_dir

- name: Write <r> Traefik route
  when:
    - <r>_traefik_host | length > 0
    - >-
      inventory_hostname in groups['traefik'] | default([])
      or <r>_traefik_dynamic_dir.stat.exists
  block:
    # No owner or mode: the traefik role sets them, and must not fight this task over them.
    - name: Ensure Traefik dynamic configuration directory exists  # noqa: risky-file-permissions
      ansible.builtin.file:
        path: "{{ traefik_config_dir | default('/etc/traefik') }}/dynamic"
        state: directory

    - name: Write <r> Traefik route
      ansible.builtin.template:
        src: <r>.traefik.yml.j2
        dest: "{{ traefik_config_dir | default('/etc/traefik') }}/dynamic/<r>.yml"
        owner: root
        group: root
        mode: "0644"

- name: Remove <r> Traefik route
  ansible.builtin.file:
    path: "{{ traefik_config_dir | default('/etc/traefik') }}/dynamic/<r>.yml"
    state: absent
  when: <r>_traefik_host | length == 0
```

## Grafana data source / dashboards

```yaml
- name: Check for Grafana's data source directory
  ansible.builtin.stat:
    path: /etc/grafana/provisioning/datasources
  register: <r>_grafana_datasources_dir

- name: Provide <r> as a Grafana data source
  when: >-
    inventory_hostname in groups['grafana'] | default([])
    or <r>_grafana_datasources_dir.stat.exists
  block:
    # No owner or mode: the grafana package sets them, and must not fight this task over them.
    - name: Ensure Grafana's data source directory exists  # noqa: risky-file-permissions
      ansible.builtin.file:
        path: /etc/grafana/provisioning/datasources
        state: directory

    # No owner or mode either: the grafana package makes everything in /etc/grafana
    # root:grafana 0640 on every install and upgrade, and the two would fight.
    - name: Write <r> Grafana data source  # noqa: risky-file-permissions
      ansible.builtin.template:
        src: <r>.grafana.yaml.j2
        dest: /etc/grafana/provisioning/datasources/<r>.yaml
      notify: Restart grafana for data sources

    # Read by the cleanup play: without it, the data source is deleted from Grafana.
    - name: Mark <r> Grafana data source as applied
      ansible.builtin.set_fact:
        <r>_grafana_datasource_applied: true

# Dashboards: a folder of the role's own.
- name: Provide <r> dashboards to Grafana
  ansible.builtin.include_role:
    name: grafana
    tasks_from: dashboards.yml
  vars:
    grafana_dashboards_role: <r>
    grafana_dashboards_list: "{{ <r>_grafana_dashboards }}"
  when: <r>_grafana_dashboards | length > 0
```

Data source template starts with `# provision: role=<r>` (cleanup turns it into
`deleteDatasources` once the role is gone).

## Upstream binary install (`tasks/install.yml`)

```yaml
- name: Check installed <r> version
  ansible.builtin.command: "{{ <r>_binary }} --version"
  register: <r>_installed
  changed_when: false
  failed_when: false
  check_mode: false

- name: Install <r> binary
  when: >-
    <r>_installed.rc != 0 or <r>_version not in <r>_installed.stdout
  block:
    - name: Create temporary download directory
      ansible.builtin.tempfile:
        state: directory
        suffix: -<r>
      register: <r>_tmp

    - name: Download <r> (checksum verified against SHA256SUMS)
      ansible.builtin.get_url:
        url: "{{ <r>_release_url }}/{{ <r>_asset }}"
        dest: "{{ <r>_tmp.path }}/{{ <r>_asset }}"
        checksum: "sha256:{{ <r>_release_url }}/SHA256SUMS"
        mode: "0644"

    - name: Unpack <r>
      ansible.builtin.unarchive:
        src: "{{ <r>_tmp.path }}/{{ <r>_asset }}"
        dest: "{{ <r>_tmp.path }}"
        remote_src: true

    - name: Install <r> binary
      ansible.builtin.copy:
        src: "{{ <r>_tmp.path }}/<r>"
        dest: "{{ <r>_binary }}"
        remote_src: true
        owner: root
        group: root
        mode: "0755"
      notify: Restart <r>

  always:
    - name: Remove temporary download directory
      ansible.builtin.file:
        path: "{{ <r>_tmp.path }}"
        state: absent
      when: <r>_tmp.path is defined
```

## Service (`tasks/service.yml`)

```yaml
---
- name: Ensure <r> is enabled and running
  ansible.builtin.systemd_service:
    name: <r>.service
    state: started
    enabled: true
    daemon_reload: true

# Apply a pending restart before the checks in verify.yml.
- name: Flush handlers
  ansible.builtin.meta: flush_handlers
```

Disabled optional component: `stat` the unit, then stop/disable only when it exists.

## Once-per-run guard (agent roles pulled in via meta deps)

```yaml
# Every role depends on <agent> (meta/main.yml), so each play would run it again; facts outlive
# plays, so once per run is enough. Its defaults and handlers stay loaded for the dependents.
- name: Skip <agent> when already applied in this run
  ansible.builtin.meta: end_role
  when: <agent>_applied | default(false)
  tags: [always]
# … imports …
- name: Mark <agent> as applied in this run
  ansible.builtin.set_fact:
    <agent>_applied: true
  tags: [always]
```

## Agent-owned cleanup (`roles/<agent>/tasks/cleanup.yml`)

```yaml
# Run by playbooks/plays/cleanup.yml after every other play. Roles mark their files with
# `# provision: role=<role>` and set <role>_<kind>_applied when they run; a marked file
# without that fact belongs to a role no longer applied.
- name: Find <kind> files written by roles
  ansible.builtin.find:
    paths: /etc/<dir>
    patterns: "*.<ext>"
    contains: "^# provision: role="
  register: <agent>_cleanup_files

- name: Remove <kind> files of roles no longer applied
  ansible.builtin.file:
    path: "{{ item.path }}"
    state: absent
  loop: "{{ <agent>_cleanup_files.files }}"
  loop_control:
    label: "{{ item.path | basename }}"
  vars:
    <agent>_cleanup_role: "{{ item.path | basename | regex_replace('\\.<ext>$', '') }}"
  when: >-
    not lookup('ansible.builtin.vars', <agent>_cleanup_role ~ '_<kind>_applied',
               default=false)
  notify: Reload <agent>
```

Then add an `include_role … tasks_from: cleanup.yml` to the guarded block in
`playbooks/plays/cleanup.yml`.
