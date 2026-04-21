# Backlog

## Pre-GA

- **Image reproducibility + SBOM.** Current setup pins apk versions in
  Containerfiles, but Alpine's apk repos are mutable — they keep only the
  *current* version per release branch, so pins rot whenever upstream rebuilds
  for a CVE. We already hit this once (ca-certificates, now unpinned). Three
  durable fixes:
  1. Add renovate/dependabot on `Containerfile*` so pin-rot produces a PR
     within days instead of a broken build at dispatch time.
  2. Move runtime workflows from `:latest` to immutable image digests
     (`ghcr.io/.../pangolin-agent-bash@sha256:...`). The build workflow already
     pushes SHA-tagged images; runtime would pin and bump on a cadence. This
     decouples runtime reproducibility from apk's mutability entirely.
  3. Generate and publish a CycloneDX SBOM alongside each image
     (`build-agent-images.yml` step; Trivy or `syft` for image scan in the
     same job, fail the build on high-severity CVEs). SBOMs also close the
     CC-style AVA_VAN gap called out in the TÜViT review (2026-04-21).
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

- **Crypto inventory (`docs/CRYPTO.md`).** One-page artefact that lists:
  TLS versions accepted by the egress proxy, runtime-CA generation and
  rotation cadence (currently per-cycle), OAuth token lifetime + rotation
  posture (Owner-driven), `AGENT_PLACEHOLDER_TOKEN` provenance, and the
  `NODE_EXTRA_CA_CERTS` trust path into the agent images. Closes F4 from
  the TÜViT gap review (2026-04-21). Cheap; unblocks any future review.

- **Egress SNI/host accounting + volume alerts.** Tight-tier hosts other
  than `api.anthropic.com` are TLS-spliced — the proxy can observe the
  SNI and byte-count but not the content. Today we log pass/block on
  bumped hosts only. Add:
  1. Structured log line per spliced connection (SNI, start time, bytes
     in/out, duration).
  2. Per-cycle summary (table: host → request count, total bytes).
  3. Soft alert threshold (e.g. > N MB to a single non-anthropic host in
     one cycle) surfaced in the cycle summary comment.
  Covers the "exfil via pypi/ghcr/npm CDN" class that the Fefe-style
  review (2026-04-21) flagged: the Anthropic-only MITM means every
  other allowlisted host is a blind tunnel. Not content inspection, but
  enough to notice a 200 MB outbound burst.

- **Per-container iptables-REJECT (not host-wide).** `harden_egress`
  used to install a host-wide iptables REJECT as DiD against
  proxy-ignoring code; it was removed because GH-Actions log-blob
  upload lives on the same host. Restore the DiD by applying REJECT
  only inside the agent container's network namespace (docker network
  `pangolin-net` rules, or `--cap-add NET_ADMIN` + per-container
  iptables at startup). The host-level logging path is untouched;
  agents still can't reach anything but the proxy. Fefe-review
  (2026-04-21) called out `HTTPS_PROXY`-only as porous against any
  library that doesn't honor the env var (curl subprocess, explicit
  `proxies={}` in requests, …).

- **Move `ANTHROPIC_TOKEN` out of proxy-container env.** Today the real
  OAuth token lives in the proxy container as `ANTHROPIC_TOKEN` env.
  Environment is visible to anything in the same process tree and shows
  up in container-introspection APIs (`docker inspect`, any sidecar
  with the proxy PID namespace). Strictly better: bind-mount a tmpfs
  file (0400, owned by the proxy uid) with the token and have the
  addon read it at startup. Same trust properties, smaller exposure
  surface, less grep-able. Fefe-review (2026-04-21). Small refactor in
  `pangolin_egress.py` + `_ensure_proxy_running`.

- **PR-feedback Phase 2: inline review comments + thread resolution.**
  Phase 1 (merged) handles PR-level comments. Inline review comments
  (attached to a file/line) and the review-state machinery (CHANGES_REQUESTED
  reviews) are richer signals. Two sub-items:
  1. Read `reviewThreads` + `reviews` via `gh pr view --json`; feed the
     file/line context + comment body to the agent as "fix this on these
     lines". Same owner-authorship + watermark filtering as Phase 1.
  2. Resolve the thread after the fix lands (`resolveReviewThread`
     GraphQL mutation — REST doesn't expose this). Orchestrator-side write,
     not agent-side.
  Tracking-thorn: when is a thread "addressed"? Naïve rule: the committed
  diff touches at least one of the thread's original hunks. STRUCT.4-style
  inference filter.
