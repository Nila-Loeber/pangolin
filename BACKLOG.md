# Backlog

## Pre-GA

- **Self-host the egress filter (drop StepSecurity Harden-Runner dependency).**
  `step-security/harden-runner@v2` with `egress-policy: block` is free on
  public repos but gated behind a paid StepSecurity plan on private repos.
  Replace with a self-contained iptables-based egress filter at job start:
  ~15 lines of bash that sets OUTPUT-policy DROP, allows the explicit
  endpoint list (same as the current `allowed-endpoints`), and restricts to
  443/53. No external dependency, no vendor pricing, works on private repos.
  Tradeoff: no pretty violation reporting — but for our threat model the
  block-or-not signal is what matters.



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
