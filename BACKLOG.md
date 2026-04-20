# Backlog

## Pre-GA

- **MITM the egress proxy (ssl-bump): close two attack vectors.**
  Plain hostname-allowlist proxy still exposes two real exfil paths:
  1. `CLAUDE_CODE_OAUTH_TOKEN` lives in agent-container env. Anything in the
     container (incl. prompt-injected Bash via `/proc/self/environ`) reads
     it.
  2. **api.anthropic.com itself is an exfil channel.** A compromised agent
     can `curl https://api.anthropic.com/v1/messages` with attacker-supplied
     tools (`web_fetch` to attacker.com) — Anthropic dutifully fetches the
     attacker URL server-side, attacker.com logs the exfil. Hostname
     allowlist can't see this because it's all inside one allowed domain.
  Fix in two phases:
  - **Phase A (token-hiding via header-injection)**: squid ssl-bump
    terminates TLS to api.anthropic.com, injects
    `Authorization: Bearer $TOKEN` server-side, re-encrypts. Token lives
    only in the proxy. Agent containers trust a proxy-CA cert (baked into
    Containerfile.{llm,software}) and have no token in env.
  - **Phase B (request-body policy via ICAP)**: small ICAP service
    (~100 LOC Python) hooked into squid; inspects each `/v1/messages` body
    and validates that the requested `tools` match the calling mode's
    permitted set (e.g. software-mode rejected if it requests `web_fetch`).
    Closes attacker-controlled-API-request exfil.
  Pre-check before starting Phase A: verify claude CLI doesn't pin Anthropic
  certs (test: set NODE_EXTRA_CA_CERTS to our proxy CA, check if CLI accepts
  the MITM'd connection). If pinned, this whole item is moot.
  Cost: ~30 LOC squid ssl-bump + CA-gen + 3-line CA-trust in agent
  Containerfiles for Phase A; ~100 LOC ICAP service + squid icap_service
  config for Phase B.



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
