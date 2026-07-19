# Bookmark — multi-workspace linear-cli + cross-repo install

Session-continuity artifact. Read end-to-end before starting work. Captured 2026-07-19 after a design discussion that scoped the project end-to-end and resolved the open questions blocking implementation. This file plus the linked repo state is the entire context — a fresh sandbox + fresh session reading this should be ready to start implementing.

## TL;DR

linear-cli is the team's audited Linear write path. Today it (a) authenticates via a single `LINEAR_API_KEY` env var or `.env` file, and (b) is git-referenced into placeframe as a per-repo `dev` dependency. The operator wants to invoke `linear` from any repo (not just placeframe), and pulsar needs to land tickets in a **personal** Linear workspace while placeframe lands them in the **foundation** workspace — so the single-key, single-workspace assumption no longer holds.

Three workstreams, sequenced:

1. **linear-cli (here)**: extend the tool to read named profiles from `~/.config/linear-cli/config.json` (with per-repo path-defaults), add a `--profile` global flag, and switch the install story from per-repo git-reference to global `uv tool install`. Design lives in this repo's `design/`; ticket files against the foundation workspace.
2. **pulsar**: add host→sandbox credential plumbing that mirrors the existing GitHub App pattern (`scripts/src/scripts/sandbox/configure_github_app.py` is the template). Independent of workstream 1 — pulsar can adopt either the old single-key flow or the new profile flow depending on sequencing.
3. **operator setup**: mint a personal-workspace API key (workspace already exists), populate `~/.config/linear-cli/config.json` on the host with both profiles. Prerequisite for end-to-end use, not for code changes.

## Why this project, in one paragraph

linear-cli was placeframe-shaped — one workspace, one team (`PLE`), one repo consuming it. It is now cross-cutting infrastructure: every outernet-foundation repo (and the operator's personal repos like pulsar) wants to write to Linear, and pulsar specifically needs a different workspace than placeframe. Per-repo git-referencing leaks the tool's deps into every consumer's lockfile (confirmed: running `uv run linear` from `/workspace/placeframe/` inside the pulsar container wiped `/home/code/.venvs/pulsar` and re-synced placeframe's deps into it — the existing pulsar AGENTS.md `Don't uv sync inside a service directory` rule, generalized). Single-key auth forces one workspace per environment. Both assumptions need to go.

## linear-cli today

- Repo: `github.com/outernet-foundation/linear-cli`, default branch `main`, HEAD `b296f93`, public. Bind-mounted at `/workspace/linear-cli/` inside the pulsar sandbox.
- Package: `linear_cli` (src-layout, `src/linear_cli/`), exposes `linear = "linear_cli.cli:app"` in `pyproject.toml:19-20`.
- Operations doc: `src/linear_cli/linear_operations.graphql`, loaded at runtime via `Path(__file__).with_name(...)` — must ship in the wheel (`[tool.hatch.build.targets.wheel] include` in `pyproject.toml`).
- Verbs: `list-issues`, `get-issue`, `list-relations`, `list-projects`, `list-labels`, `lint`, `ensure-label`, `update-label`, `delete-label`, `create-project`, `create-issue`, `update-project`, `update-issue`, `link`, `comment`, `delete-comment`. The `--team` flag (e.g. `--team PLE`) selects a team within the authed workspace.
- Auth: `_api_key()` at `src/linear_cli/cli.py:682` reads `LINEAR_API_KEY` from env, falls back to `_parse_env_file(_find_up(".env"))` (walks from CWD upward). The Authorization header is built at `cli.py:572`.
- Workspaces are API-key-scoped. There is no concept of multiple keys or multiple workspaces in the tool today.
- The team conventions currently live in this repo's `AGENTS.md`: the body template (universal, tool-enforced via `validation.py`) and the foundation-workspace facts (one `Engineering` team keyed `PLE`, the `repo`/`type` label groups). Phase 1 splits these — the universal rules stay in `AGENTS.md`, the workspace facts migrate into `~/.config/linear-cli/config.json` as deterministic data.

## How linear-cli is consumed today

- placeframe: root `pyproject.toml` line 9 lists `linear-cli` in `[dependency-groups] dev`, line 53 git-pins it under `[tool.uv.sources]` to rev `b296f93e64a14178eca47813d263c30d05cf3a39`. `uv run linear` works from anywhere inside the placeframe tree.
- The `LINEAR_API_KEY` lives in `/workspace/placeframe/.env` (host: `/home/tyler/repos/placeframe/.env`) alongside docker-compose secrets. That key authenticates the **plerionplatforms** workspace (`https://linear.app/plerionplatforms/`) — confirmed by running `uv run --no-sync linear list-projects` from `/workspace/placeframe/`.
- pulsar: does not consume linear-cli at all today. No entry in `pyproject.toml`, no `LINEAR_API_KEY` anywhere. The pulsar overhaul that just landed (HEAD `e190b87` on `design/sandbox-overhaul`, 50 commits ahead of origin, unpushed) left `tickets/` as a local-only markdown tier pending this very project.
- No other repo currently consumes linear-cli.

## How the pulsar sandbox injects host credentials today (the template to copy)

Pulsar's existing GitHub App flow is the canonical pattern for "host-side secret → in-container tool." All file paths below are pulsar-repo-relative.

- **Host config file**: `~/.config/pulsar/config.json` (host-side, outside the bind mounts, invisible from the container). Schema in `scripts/src/scripts/sandbox/sandbox_common.py:162-167` (`PulsarConfig` pydantic model with a `github_app: GithubApp | None = None` block).
- **Host secret file**: `~/.config/pulsar/github-app/private-key.pem`. Path constants in `sandbox_common.py:49-51` (`GITHUB_APP_DIR_ROOT`, `SLOT_GITHUB_APP_DIR_MOUNT`, `GITHUB_APP_KEY_FILENAME`).
- **forward_env list**: `.coi/profiles/pulsar/config.toml` top-level `forward_env = [...]`. COI bakes these env vars into the container at creation time.
- **start_slot.py exports them**: `scripts/src/scripts/sandbox/start_slot.py:188-199` reads `config.github_app`, exports `GITHUB_APP_ID` + `GITHUB_APP_INSTALLATION_ID` to its own process env before invoking `coi shell`. The pulsar profile's `forward_env` carries them into the container.
- **Mount the key dir read-only**: `scripts/src/scripts/sandbox/configure_github_app.py:18+` (`ensure_github_app_key_mount`) adds an Incus disk device for the github-app dir. Runs on every container start; idempotent.
- **In-container minting**: `scripts/src/scripts/mint_github_app_token.py:16` reads the mounted key at `/home/code/.config/github-app/private-key.pem` plus the env-var ids, mints a one-hour installation token, caches it at `~/.cache/pulsar/github-app-token.json`.
- **Call sites wrap the mint**: `GH_TOKEN=$(uv run mint-github-app-token) gh ...`. Documented in pulsar's `AGENTS.md` item 4.

The pattern: **non-secret ids ride env vars via `forward_env`; the secret itself is a file bind-mounted into a known container path; an in-container mint/resolve step combines them at the point of use.** Linear is simpler than GitHub App because the secret IS the API key (no minting needed), so the pattern collapses to "bind-mount the config dir, point linear-cli at it."

## The plan, sequenced

### Phase 1 — linear-cli changes (this repo)

Files touched in `src/linear_cli/`:

- **`cli.py`**: extend `_api_key()` (line 682) to `_resolve_api_key(profile: str | None)`. Resolution order: `--profile` flag value (if given) → longest-prefix match on `path_defaults` in `~/.config/linear-cli/config.json` against CWD → hard error if neither ("no profile resolved for `<cwd>`; pass `--profile` or add a `path_defaults` entry"). No silent default — a fallback `default_profile` is a write-path footgun (filed-in-the-wrong-workspace bugs). The HTTP Authorization header at line 572 uses the resolved key. Also: `list-issues` and `lint` currently paginate a *team's* issues; both need a team-optional path (paginate workspace issues when the resolved profile has `team_key: null`). `--team` becomes an override that errors if the resolved profile is team-less. The legacy `LINEAR_API_KEY` env-var / `.env` walk-up path is removed entirely — no backward-compat surface, the tool requires a config.json.
- **New module** `profiles.py`: pydantic model for `~/.config/linear-cli/config.json`. Shape:
  ```json
  {
    "profiles": {
      "foundation": { "api_key": "...", "team_key": "PLE", "labels": { "repo": ["placeframe", "make-it-sing", "infra"], "type": ["bug", "feature", "improvement", "chore", "refactor", "docs"] } },
      "personal":   { "api_key": "...", "team_key": null, "labels": {} }
    },
    "path_defaults": {
      "/workspace/placeframe": "foundation",
      "/workspace/pulsar":     "personal"
    }
  }
  ```
  No `default_profile` — error on unresolved CWD instead. `team_key` and `labels` per profile carry the deterministic workspace facts an agent needs to write well-formed tickets (replaces the prose conventions that used to live in this repo's `AGENTS.md`); `labels` is a `dict[str, list[str]]` keyed by group name. Read function, write function (for an eventual `linear profile add` verb, out of scope here).
- **`pyproject.toml`**: no structural changes; the existing `[project.scripts] linear = "linear_cli.cli:app"` is already correct for both `uv tool install` and per-repo git-reference.
- **`AGENTS.md`**: drop the workspace-specific content (the `Engineering/PLE` team sentence, the `repo`/`type` label group definitions) — those are deterministic data now living in config.json. Keep the universal tool-enforced conventions (ticket body template, declarative-outcome rules, absolute-link rule, "priority ignored," "sequence lives in `blocks`"). Add a brief Profiles section pointing at `~/.config/linear-cli/config.json` as the source of truth for workspace facts.

Design doc to create at `design/multi-workspace-profiles.md` covering: the config-file format and pydantic schema, the `path_defaults` longest-prefix resolution (no marker file, no walk-up — per-repo routing lives in user config, not committed to the repo, decoupling the repo from any particular workspace choice), the no-default-profile decision (silent fallback is a write-path footgun), the team-optional behavior for team-less workspaces, and the why-not-just-env-vars answer (env-var-per-workspace scales linearly with workspace count, doesn't survive across `coi shell` env-var limits, and provides no per-repo defaulting).

Ticket to file in the **foundation** Linear workspace (the linear-cli repo's own work surfaces there): "Add multi-workspace profile support to linear-cli" — declarative outcome-ticket, links to the design doc by blob URL.

### Phase 2 — pulsar credential plumbing

Mirror `configure_github_app.py` with a new `configure_linear.py`:

- New `Linear` pydantic block on `PulsarConfig` (`sandbox_common.py`): `linear: Linear | None = None` where `Linear` carries `host_config_dir: Path` (default `~/.config/linear-cli`).
- `configure_linear.py`: bind-mount the host's `~/.config/linear-cli/` dir read-only into the container at `/home/code/.config/linear-cli/`. Idempotent disk-device add, same pattern as `ensure_github_app_key_mount`.
- `start_slot.py`: no env-var forwarding needed (the mounted dir is sufficient once linear-cli reads from `~/.config/linear-cli/config.json`).
- Pulsar's `AGENTS.md`: add a "Linear" item documenting the in-container path. Pulsar's workspace facts (no team, any labels pulsar uses) are deterministic data living in config.json's `profiles.personal` block, not prose.
- `build.sh` or `populate_sandbox_volumes`: add `uv tool install git+https://github.com/outernet-foundation/linear-cli.git@${LINEAR_CLI_REV}` so every fresh container has the `linear` binary on PATH without per-repo ceremony. `LINEAR_CLI_REV` is sourced from pulsar's `config.toml [environment]`, so bumps don't require image rebuild. Ad-hoc override during active linear-cli development: `uv tool install --force --with-editable /workspace/linear-cli/` (operator-run, not config-driven); re-install the pinned rev to exit dev mode.

### Phase 3 — operator setup

Personal workspace already exists. Remaining steps:

- Mint a personal-workspace API key.
- Populate host `~/.config/linear-cli/config.json` with both profiles (foundation + personal) and `path_defaults` entries for `/workspace/placeframe` and `/workspace/pulsar`. No `.linear-profile` marker files — routing lives in config.
- File the pulsar-overhaul close-out ticket in the personal workspace, link from pulsar's `bookmark.md`.

### Phase 4 — retire placeframe's per-repo git-reference

After Phase 1 ships and the operator has the global tool working:

- Remove `linear-cli` from placeframe's `[dependency-groups] dev` and `[tool.uv.sources]`.
- Update placeframe's `AGENTS.md` Linear section: drop the "git-referenced in the root pyproject.toml" sentence, replace with "installed globally via `uv tool install`; run as `linear ...` without the `uv run` prefix."
- Run `uv sync` to update placeframe's `uv.lock`.

This is its own foundation-workspace ticket, sequenced after Phase 1 so the global tool is available before the per-repo install is removed.

## State of relevant repos at capture time

- **linear-cli** (`/workspace/linear-cli/`): HEAD `b296f93` on `main`, working tree will be dirty after this bookmark lands. Public at `github.com/outernet-foundation/linear-cli`. Push access: agent has read-only GitHub App token, cannot push — operator pushes from host.
- **pulsar** (`/workspace/pulsar/`): HEAD `e190b87` on `design/sandbox-overhaul`, 50 commits ahead of origin, unpushed. The overhaul is complete; see pulsar's `bookmark.md` for the full state. Push access: same as linear-cli, operator-side.
- **placeframe** (`/workspace/placeframe/`): not modified by the linear-cli project until Phase 4. Currently git-pins linear-cli at `b296f93e...`.
- **Host config**: `~/.config/pulsar/config.json` (invisible from inside the container) is where the new `linear` block on `PulsarConfig` will be authored by the operator. `~/.config/linear-cli/` does not exist yet on the host.

## First moves for a fresh session

1. Read this file end-to-end. ✓
2. Read `/workspace/linear-cli/AGENTS.md` end-to-end — it carries the universal ticket-template conventions (tool-enforced via `validation.py`) that Phase 1 preserves verbatim. The workspace-specific facts (team key, labels) currently in that doc are scheduled to migrate into config.json under Phase 1.
3. Skim `/workspace/linear-cli/src/linear_cli/cli.py` lines 560-590 (the HTTP call site), 670-706 (the `_find_up` + `_api_key` pair). These are the surgical sites for Phase 1.
4. Skim `/workspace/pulsar/scripts/src/scripts/sandbox/configure_github_app.py` end-to-end — it's the template for the Phase 2 `configure_linear.py`. Pulsar's `AGENTS.md` items 3 and 4 cover the GitHub App flow at a higher level.
5. Skim pulsar's `~/.config/pulsar/config.json` schema at `scripts/src/scripts/sandbox/sandbox_common.py:162-167` (`PulsarConfig`) as the structural template for `~/.config/linear-cli/config.json`.
6. File the foundation-workspace ticket for Phase 1 ("Add multi-workspace profile support to linear-cli") using the existing `linear create-issue` verb against the foundation workspace. Design is locked; begin implementing `profiles.py` + the `cli.py` resolution change against the schema above.
