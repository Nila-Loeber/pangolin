# Sandburg Package Extraction — Plan

## Ziel

`sandburg` als pip-installierbares Paket aus einem eigenen Git-Repo, das in
beliebige Wiki-Repos eingebunden werden kann via:

```
pip install git+https://github.com/Nila-Loeber/sandburg.git@v0.1
```

Wiki-Repos bekommen damit: Orchestrator + Default-Config + Workflow-Templates.
Updates ziehen sie über neue Git-Tags.

## Repository-Trennung

| Repo | Inhalt |
|---|---|
| **`Nila-Loeber/sandburg`** (neu) | Orchestrator-Code, Containerfiles, GHCR-Image-Builds, Default-Config, Agent-SSoT-Prompts |
| **`Nila-Loeber/secure-conversational`** (dieses Repo) | Wird zum Dogfood-Wiki — nutzt sandburg als Dependency. Behält seinen Content, verliert den Python-Code. |
| **Dein echtes Wiki-Repo** | Neu aufzusetzen, nutzt sandburg als Dependency. |

## Ziel-Struktur `sandburg/` Repo

```
sandburg/
├── pyproject.toml
├── README.md
├── LICENSE
├── Containerfile                    # sandburg-agent (in-process SDK path)
├── Containerfile.agent              # sandburg-agent-epic8 (Claude CLI in gVisor)
├── src/
│   └── sandburg/
│       ├── __init__.py              # exports + __version__
│       ├── cli.py                   # `sandburg init/run/software/version`
│       ├── core.py                  # REPO, gh, make_logger, wrap_agent_body
│       ├── modes.py                 # SCHEMAS, Mode, load_modes
│       ├── orchestrate.py           # CycleRunner + run_cycle entry
│       ├── providers.py             # Anthropic/Scaleway providers
│       ├── software.py              # Software-task runner
│       ├── tools.py                 # ToolExecutor + CLI_TOOL_NAMES
│       ├── paths.py                 # Package-data resolvers
│       ├── scaffold.py              # `sandburg init` implementation
│       └── default_config/          # Files copied to wiki repo on init
│           ├── modes.yml
│           ├── wiki_schema.md
│           ├── validate_output.sh
│           ├── docs/
│           │   ├── inbox-triage.md
│           │   ├── inbox-summary.md
│           │   ├── research-agent.md
│           │   ├── self-improve.md
│           │   ├── software-agent.md
│           │   ├── thinking-agent.md
│           │   ├── wiki-ingest.md
│           │   └── writing-agent.md
│           └── workflows/
│               ├── agent-cycle.yml
│               └── agent-software.yml
├── .github/workflows/
│   ├── build-agent-images.yml       # baut + pushed sandburg-agent* nach GHCR
│   ├── test.yml                     # pytest on PRs
│   └── release.yml                  # git tag → PyPI + GHCR-Tag gleichzeitig
└── tests/
    ├── conftest.py
    └── test_security.py             # die 38 Tests aus dem secure-conversational Repo
```

## CLI Interface

```
sandburg init                 # scaffoldet Config-Files ins aktuelle Repo
sandburg run                  # führt einen Cycle aus
sandburg software             # führt einen Software-Task aus
sandburg version              # version printen
sandburg --help
```

### `sandburg init` Verhalten

- Copy `default_config/modes.yml` → `./modes.yml` (skip if exists)
- Copy `default_config/wiki_schema.md` → `./wiki/SCHEMA.md`
- Copy `default_config/docs/*.md` → `./docs/*.md` (skip each if exists)
- Copy `default_config/workflows/*.yml` → `./.github/workflows/*.yml`
- Create empty `wiki/fragment/.gitkeep`, `notes/ideas/.gitkeep`, `drafts/.gitkeep`, `content/.gitkeep`
- Create `.ingest-watermark` mit `1970-01-01T00:00:00Z`
- Print next steps (Secrets setzen, erster Dispatch)

## Wiki-Repo Struktur nach `sandburg init`

```
wiki-repo/
├── .github/workflows/
│   ├── agent-cycle.yml              # vom Template — referenziert sandburg via pip
│   └── agent-software.yml
├── docs/
│   ├── inbox-triage.md              # SSoT-Prompts, editierbar für Anpassung
│   └── ...
├── modes.yml                        # Permission-Profile, editierbar
├── wiki/
│   ├── SCHEMA.md
│   ├── fragment/.gitkeep
│   └── ...                          # eigentlicher Content
├── notes/ideas/.gitkeep
├── drafts/.gitkeep
├── content/.gitkeep
└── .ingest-watermark
```

## Wiki-Repo `agent-cycle.yml` (vereinfacht)

```yaml
name: agent-cycle
on:
  workflow_dispatch: {}
concurrency:
  group: agent-cycle
  cancel-in-progress: false
permissions:
  contents: write
  issues: write
  pull-requests: write
  packages: read

jobs:
  cycle:
    runs-on: ubuntu-latest
    steps:
      - uses: step-security/harden-runner@v2
        with:
          egress-policy: block
          allowed-endpoints: >
            api.anthropic.com:443
            api.github.com:443
            github.com:443
            objects.githubusercontent.com:443
            pypi.org:443
            files.pythonhosted.org:443
            gvisor.dev:443
            storage.googleapis.com:443
            ghcr.io:443

      - uses: actions/checkout@v6
        with:
          fetch-depth: 0

      - name: Install gVisor
        run: |
          curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor.gpg
          echo "deb [signed-by=/usr/share/keyrings/gvisor.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
          sudo apt-get update -qq && sudo apt-get install -y -qq runsc
          sudo runsc install && sudo systemctl reload docker

      - name: Pull agent images from GHCR
        run: |
          docker login ghcr.io -u ${{ github.actor }} -p ${{ secrets.GITHUB_TOKEN }}
          docker pull ghcr.io/nila-loeber/sandburg-agent:v1
          docker pull ghcr.io/nila-loeber/sandburg-agent-epic8:v1
          docker tag ghcr.io/nila-loeber/sandburg-agent:v1 sandburg-agent:latest
          docker tag ghcr.io/nila-loeber/sandburg-agent-epic8:v1 sandburg-agent-epic8:latest

      - name: Install sandburg
        run: pip install git+https://github.com/Nila-Loeber/sandburg.git@v0.1

      - name: Setup git identity
        run: |
          git config user.name "cycle-agent"
          git config user.email "cycle-agent@users.noreply.github.com"

      - name: Run cycle
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: sandburg run
```

## Design-Entscheidungen

### 1. Docs+modes.yml sind Repo-lokal, nicht im Paket

Default-Content wird beim `init` ins Wiki-Repo kopiert. Danach gehört es dem
User. Der Orchestrator liest **immer** aus dem Wiki-Repo, nicht aus dem
installierten Paket.

**Grund:** Nutzer wollen Prompts anpassen (Voice, Style, Domain-spezifische
Instruktionen). Wenn wir die Prompts im Paket hielten, würden Updates
User-Änderungen überschreiben.

**Konsequenz:** Wenn sandburg die Default-Prompts verbessert, müssen User
manuell mergen. Akzeptabel — Prompts sind Content, nicht Code.

### 2. Container-Images kommen von GHCR

Der sandburg-Repo hat `.github/workflows/build-agent-images.yml`, der bei jedem
Tag die Images neu baut und nach `ghcr.io/nila-loeber/sandburg-agent*:vX` pusht.

Wiki-Repos pullen diese Images, bauen nichts selbst.

**Vorteil:** Supply-Chain-Punkt ist im sandburg-Repo zentralisiert. Wiki-Repos
brauchen kein npm/Alpine-Mirror im `harden-runner`.

### 3. `validate_output.sh` lebt im Paket

Das Shell-Script wird beim Orchestrator-Lauf via `sandburg.paths.validate_output_script()`
aufgelöst und mit Full-Path aufgerufen. Kein Kopieren ins Wiki-Repo — ein
Ding weniger, das der User maintainen muss.

### 4. Workflow-Files werden kopiert (nicht als reusable workflow)

`sandburg init` kopiert `agent-cycle.yml` und `agent-software.yml` ins
`.github/workflows/` des Wiki-Repos. Vorteil: User sieht + versteht +
modifiziert den Workflow. Nachteil: Bei sandburg-Updates muss der User
ggf. manuell den Workflow updaten.

**Alternative für später:** Reusable-Workflow aus dem sandburg-Repo via
`uses: Nila-Loeber/sandburg/.github/workflows/cycle.yml@v1`. Verschiebe auf
v0.2 wenn das Basis-Pattern steht.

### 5. Kein PyPI initially

`pip install git+https://github.com/...` reicht für die frühe Phase. PyPI
kommt wenn das Package stabil ist.

## Migration-Path für `secure-conversational`

Nach Extraktion wird das aktuelle Repo das Dogfood-Wiki:

1. `scripts/sandburg/` rauswerfen
2. `Containerfile*` rauswerfen
3. `scripts/{validate-output,audit-tcb,smoke-test,setup-vm}.sh` rauswerfen
4. `tests/` rauswerfen (gehört zu sandburg)
5. `.github/workflows/agent-cycle.yml` durch Template ersetzen
6. `.github/workflows/agent-software.yml` durch Template ersetzen
7. `.github/workflows/build-agent-images.yml` raus (gehört zu sandburg)
8. `.github/workflows/validate-modes.yml` raus (gehört zu sandburg-Tests)
9. `BACKLOG.md`, `PROGRESS.md`, `THREAT_MODEL.md`, `docs/security-target.md`
   entweder zu sandburg migrieren oder als Wiki-Content belassen
10. Content-only bleiben: `wiki/`, `notes/`, `drafts/`, `content/`, `docs/`,
    `modes.yml`, `.ingest-watermark`

Was übrig bleibt: ein schlankes Content-Repo das sandburg als Dependency hat.

## Reihenfolge der Arbeit

1. **Jetzt** (dieser Session): Repo-Struktur-Skizze, pyproject.toml, CLI-Skeleton
2. **Nächste Session**: Real Extraktion — Code aus secure-conversational rüberkopieren, Tests ans neue Layout anpassen
3. **Dann**: Neues GitHub-Repo anlegen, pushen, build-agent-images laufen lassen
4. **Dann**: secure-conversational auf die Dependency umstellen, einen Cycle laufen lassen zur Validierung
5. **Dann**: Dein echtes Wiki-Repo initialisieren

## Offene Fragen

- **Namespace-Konflikt**: Current layout ist `scripts/sandburg/` (Python Module innerhalb eines scripts-Verzeichnisses). Neue Struktur ist `src/sandburg/` (src-Layout für Packages). Import-Statements bleiben gleich (`from sandburg.modes import ...`). ✓
- **Version-Tag-Schema**: `v0.1`, `v0.2` (major.minor, keine semver-Patches) oder echtes semver `v0.1.0`? Empfehlung: semver ab Start.
- **Default-modes.yml**: Momentan hat modes.yml deinen konkreten Workflow-Zuschnitt (7 Modes). Soll das Default bleiben, oder gibt's einen reduzierten "minimal" Default für kleinere Wikis? Für v0.1: der aktuelle 7-Mode-Default, User kann modes.yml bearbeiten.
- **secure-conversational Dogfooding-Phase**: Dieses Repo hat ~20 existierende Issues, eine PR-History, Workflow-Logs. Beim Umstellen verlieren wir nichts, aber die History-Semantik ändert sich (vorher: "kleines Forschungs-Repo", nachher: "Demo-Wiki"). Keine Aktion nötig.
