#!/usr/bin/env bash
# Unified post-run output validator. Replaces the three separate validators.
#
# Usage: validate-output.sh <config>
#
# Configs (define allowlist + schema checks per agent):
#   research    — wiki/fragment/*.md
#   wiki-ingest — wiki/*.md, wiki/{ref,project,draft}/*.md, index, log, watermark
#                 DENY: wiki/fragment/* (readonly), wiki/SCHEMA.md
#   self-improve — docs/*.md EXCEPT docs/self-improve.md
#
# For each changed/new file: check allowlist, revert violations.
# For allowed files: run schema checks (frontmatter, HTML patterns).
# Exit 0 always (valid output gets committed, violations are reverted).

set -euo pipefail

CONFIG="${1:-}"
[[ -n "$CONFIG" ]] || { echo "usage: validate-output.sh <research|wiki-ingest|self-improve>" >&2; exit 2; }

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

log() { echo "validate[$CONFIG]: $*"; }
warn() { echo "validate[$CONFIG]: VIOLATION: $*" >&2; }

violations=0

# ── Allowlist per config ──

is_allowed() {
  local f="$1"
  case "$CONFIG" in
    research)
      case "$f" in
        wiki/fragment/*.md) return 0 ;;
      esac ;;
    wiki-ingest)
      case "$f" in
        wiki/fragment/*|wiki/SCHEMA.md) return 1 ;;  # explicit deny
      esac
      case "$f" in
        wiki/index.md|wiki/log.md|.ingest-watermark) return 0 ;;
        wiki/*.md|wiki/ref/*.md|wiki/project/*.md|wiki/draft/*.md) return 0 ;;
      esac ;;
    self-improve)
      case "$f" in
        docs/self-improve.md) return 1 ;;  # explicit deny
        docs/*.md) return 0 ;;
      esac ;;
  esac
  return 1
}

# ── Per-config scope (which paths is THIS validator responsible for?) ──
#
# Without scoping, `validate-output.sh research` would also revert files
# written by triage (e.g. .inbox-watermark) because those are "outside the
# research allowlist". The scope limits Step 1 to files THIS agent might
# legitimately have written; everything else is someone else's business
# and we leave it alone.

declare -a SCOPE
case "$CONFIG" in
  research)     SCOPE=("wiki/fragment/") ;;
  wiki-ingest)  SCOPE=("wiki/" ".ingest-watermark" ":!wiki/fragment/") ;;
  self-improve) SCOPE=("docs/") ;;
esac

# ── Step 1: revert anything inside scope but outside allowlist ──

mapfile -d '' -t CHANGED < <(
  git diff --name-only -z HEAD -- "${SCOPE[@]}" 2>/dev/null
  git ls-files --others --exclude-standard -z -- "${SCOPE[@]}"
)
for f in "${CHANGED[@]}"; do
  [[ -z "$f" ]] && continue
  if is_allowed "$f"; then continue; fi
  warn "file outside allowlist: $f"
  violations=$((violations + 1))
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    git checkout -- "$f"
    log "reverted tracked: $f"
  else
    rm -rf "$f"
    log "removed untracked: $f"
  fi
done

# ── Step 2: schema checks on allowed files ──

check_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0

  case "$CONFIG" in
    research)
      # Fragments must have YAML frontmatter (opening + closing ---)
      if ! head -1 "$f" | grep -qE '^---$'; then
        warn "$f: missing frontmatter (no opening ---)"; return 1
      fi
      if ! sed -n '2,40p' "$f" | grep -qE '^---$'; then
        warn "$f: missing frontmatter (no closing ---)"; return 1
      fi
      local head
      head="$(awk '/^---$/{c++} c>=2{exit} {print}' "$f")"
      for field in title source date summary source_issue captured_at captured_by; do
        if ! grep -qE "^${field}:" <<< "$head"; then
          warn "$f: missing field '$field'"; return 1
        fi
      done ;;
    wiki-ingest)
      # Topic pages must NOT have frontmatter (nlkw convention)
      case "$f" in wiki/index.md|wiki/log.md|.ingest-watermark) return 0 ;; esac
      if head -1 "$f" | grep -qE '^---$'; then
        warn "$f: has YAML frontmatter (not allowed on topic pages)"; return 1
      fi ;;
    self-improve)
      ;; # no schema check for docs
  esac

  # HTML pattern scan (all configs)
  if grep -qiE '(<script|<iframe|javascript:)' "$f"; then
    warn "$f: forbidden HTML pattern"; return 1
  fi
  return 0
}

mapfile -d '' -t FILES < <(
  case "$CONFIG" in
    research)     git diff --name-only -z HEAD -- 'wiki/fragment/*.md' 2>/dev/null
                  git ls-files --others --exclude-standard -z -- 'wiki/fragment/*.md' ;;
    wiki-ingest)  git diff --name-only -z HEAD -- 'wiki/*.md' 'wiki/ref/*.md' 'wiki/project/*.md' 'wiki/draft/*.md' 2>/dev/null ;;
    self-improve) git diff --name-only -z HEAD -- 'docs/*.md' 2>/dev/null
                  git ls-files --others --exclude-standard -z -- 'docs/*.md' ;;
  esac
)
for f in "${FILES[@]}"; do
  [[ -z "$f" ]] && continue
  if ! check_file "$f"; then
    violations=$((violations + 1))
    if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
      git checkout -- "$f"; log "reverted invalid: $f"
    else
      rm -f "$f"; log "removed invalid: $f"
    fi
  fi
done

log "done ($violations violation(s))"
exit 0
