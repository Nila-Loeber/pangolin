# Backlog

## Pre-GA

- **MITM Phase B — ICAP request-body policy (tool-allowlist).**
  Phase A (merged) closes the token-exfil vector by keeping
  `CLAUDE_CODE_OAUTH_TOKEN` in the proxy only. Phase B closes the
  `api.anthropic.com`-as-exfil vector:

  A compromised agent can still POST to `/v1/messages` (inside the bumped
  TLS tunnel) with an attacker-supplied `tools` array, e.g. `web_fetch` to
  `attacker.com`. Anthropic server-side fulfills the fetch → data
  exfiltrates through an allowlisted host.

  Fix: small ICAP service (~100 LOC Python) hooked into squid's
  `icap_service` for bumped traffic. Inspects the JSON body of each
  `/v1/messages` request and validates that `tools` is a subset of the
  per-mode permitted set (passed via a request header that the proxy
  trusts, e.g. `X-Pangolin-Mode: software`). Rejects e.g. `web_fetch` from
  software mode outright.

  Cost: ~100 LOC Python ICAP server + `icap_service` block in squid.conf +
  orchestrator sets `X-Pangolin-Mode` via `request_header_add` per mode.



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
