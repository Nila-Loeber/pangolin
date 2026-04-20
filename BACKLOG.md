# Backlog

## Pre-GA

- **Self-host the egress filter (drop StepSecurity Harden-Runner dependency).**
  `step-security/harden-runner@v2` with `egress-policy: block` is free on
  public repos but gated behind a paid StepSecurity plan on private repos.
  Replacement: `pangolin-egress-proxy` (squid forward proxy, built) with two
  ports — tight (Anthropic/GitHub/PyPI/etc. allowlist) and loose (any HTTPS,
  used only by research-search WebFetch). All agent containers and the host
  orchestrator route outbound through the proxy via `HTTPS_PROXY` env. Then
  iptables on the host blocks direct outbound except to the proxy, as
  defense-in-depth. Hostname-aware via `dstdomain` — robust to IP rotation.
  No vendor dependency, works on private repos, no cost.

  **Open sub-tasks:**
  - Wire proxy sidecar into orchestrate.py (start before cycle, stop after)
  - Per-mode `egress: tight|loose` field in modes.yml; orchestrator selects port
  - Add iptables bootstrap step to workflow templates
  - Drop `step-security/harden-runner` from the two workflows
  - Publish `pangolin-egress-proxy` from build-agent-images workflow

- **Move OAuth token out of agent containers via proxy header-injection
  (ssl-bump).** Today `orchestrate.spawn_agent_container_*` passes
  `CLAUDE_CODE_OAUTH_TOKEN` into each agent container as env. Anything in the
  container (incl. prompt-injected Bash via `/proc/self/environ`) can read it.
  Fix: squid ssl-bump on the egress proxy terminates TLS to api.anthropic.com,
  injects `Authorization: Bearer $TOKEN` server-side, re-encrypts. Token lives
  only in the proxy. Agent containers trust a proxy-CA cert (baked into
  Containerfile.{llm,software}) and have no token in env.
  Gain: prompt-injection can't exfiltrate credentials even if egress is
  somehow bypassed — there's nothing to exfiltrate.
  Cost: ~30 LOC squid.conf additions; CA generation script; 3-line CA-trust
  block in agent Containerfiles; cert-lifecycle doc.
  Do this right after plain-proxy integration is verified end-to-end.



- **Image reproducibility.** Current setup pins apk versions in Containerfiles,
  but Alpine's apk repos are mutable — they keep only the *current* version per
  release branch, so pins rot whenever upstream rebuilds for a CVE. We already
  hit this once (ca-certificates, now unpinned). Two durable fixes:
  1. Add renovate/dependabot on `Containerfile*` so pin-rot produces a PR
     within days instead of a broken build at dispatch time.
  2. Move runtime workflows from `:latest` to immutable image digests
     (`ghcr.io/.../pangolin-agent-bash@sha256:...`). The build workflow already
     pushes SHA-tagged images; runtime would pin and bump on a cadence. This
     decouples runtime reproducibility from apk's mutability entirely.
  Longer-term option: switch to apko/Wolfi (lockfile-based image builds, no
  runtime package manager). Bigger change, right answer for GA.



- **Generalize nlkw's wiki conventions.** The `--with-wiki` init flag currently
  ships nlkw-flavored templates (German-default voice, specific directory
  typology: `ref/`, `project/`, `draft/`, `fragment/`). Before GA:
  - Extract convention choices (language, directory layout, page-type table,
    split threshold, footer sections) into a declarative `wiki.yml` or a block
    in `modes.yml`.
  - Provide at least one neutral English template set alongside the nlkw one.
  - Let `pangolin init --with-wiki=<preset>` pick a preset.
  - Audit `default_config/wiki_schema.md` for the same personalization bleed.
