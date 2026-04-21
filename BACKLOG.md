# Backlog

## Pre-GA

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
