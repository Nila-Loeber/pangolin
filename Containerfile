# Minimal agent image for Sandburg.
#
# Provides filesystem isolation for tool execution. The LLM API call
# happens on the host — the container only runs tool implementations
# (Read, Write, Edit, Glob, Grep, Bash).
#
# Design:
#   - Alpine base, Python + PyYAML only
#   - No Node, no npm, no Claude CLI, no Anthropic SDK
#   - No sudo, no ssh, no compilers, no wget, no curl
#   - Non-root (uid 1000)
#   - Target: ~50 MB

FROM alpine@sha256:a4f4213abb84c497377b8544c81b3564f313746700372ec4fe84653e4fb03805

# Pinned package versions — see SFR.SUPPLY.1.
# Bump requires updating both digest (above) and versions (below) atomically.
RUN apk add --no-cache \
      bash=5.2.26-r0 \
      ca-certificates=20250911-r0 \
      git=2.45.4-r0 \
      grep=3.11-r0 \
      jq=1.7.1-r0 \
      python3=3.12.13-r0 \
      py3-yaml=6.0.1-r3

RUN adduser -D -u 1000 -s /bin/bash agent

USER agent
WORKDIR /repo

ENV HOME=/home/agent
