# Multi-workspace profile support

Design rationale for the profile system that lets `linear-cli` write to multiple Linear workspaces from the same machine. The implementation lives in `src/linear_cli/profiles.py` and the `cli.py` resolution helpers; this doc covers the *why* behind the shape.

## Problem

`linear-cli` was placeframe-shaped: one workspace, one team (`PLE`), one consumer repo. It now serves cross-cutting infrastructure — every outernet-foundation repo plus the operator's personal repos want to write to Linear, and pulsar specifically needs a different workspace than placeframe. The single `LINEAR_API_KEY` env var (or walked-up `.env`) forces one workspace per environment. That assumption has to go.

## Config file

Workspace credentials and per-repo routing live in `~/.config/linear-cli/config.json`:

```json
{
  "profiles": {
    "foundation": { "api_key": "lin_api_..." },
    "personal":   { "api_key": "lin_api_..." }
  },
  "path_defaults": {
    "/workspace/placeframe": { "profile": "foundation", "team": "PLE" },
    "/workspace/governance": { "profile": "foundation", "team": "GOV" },
    "/workspace/pulsar":     { "profile": "personal",   "team": "TYL" }
  }
}
```

Location: `~/.config/linear-cli/` (the `-cli` suffix disambiguates from any future official Linear Inc. tooling). Format: JSON, matching the pulsar config convention at `~/.config/pulsar/config.json`. Schema: `profiles.py` pydantic models.

### Why the routing lives in user config, not in the repo

An earlier design proposed a `.linear-profile` marker file committed to each repo root (analogous to `.python-version` or `.nvmrc`). That couples the repo to a specific workspace — wrong layer. The same repo cloned by a different operator (or forked) would inherit a workspace routing decision that doesn't match their setup. Putting `path_defaults` in user-side config keeps the repo workspace-agnostic: each operator's machine decides which profile a checkout uses, and changing the routing is a local edit, not a commit.

### Why profile holds only the API key, and team routes via path_defaults

A Linear API key is scoped to a **workspace**, not a team. A workspace owns many teams; a key opens the workspace; which team a particular invocation is scoping to is a property of *where the operator is standing*, not of *which credential they hold*. The schema reflects that distinction: `Profile` carries only `api_key`, and the team default lives on the path binding paired with that profile.

An earlier draft put `team_key` directly on `Profile`. That shape assumed one team per workspace, so the profile → team mapping was 1:1 and the conflation was invisible. The assumption broke the moment a second team (`GOV`) was added to the foundation workspace: creating a "governance profile" meant duplicating the foundation API key into a new profile entry, which is the smell that surfaced the design weakness. Secret duplication is a maintenance liability (rotation becomes N edits) and a security smell (more places to leak from); the architecturally correct fix is to lift team routing one level, out of the credential and into the path binding where it belongs.

Team routing is a per-operator, per-checkout decision — Linear exposes the list of teams in a workspace, but cannot tell you which one *this operator* means when writing tickets from *this repo*. Putting `team` on the path binding makes the choice explicit, path-scoped, and overridable per-call via `--team`. The field is optional on a binding: verbs where team is structurally required (`create-issue`, `create-project`, `update-issue --state`, etc.) error with a clear message if no team resolves; verbs where team is a filter (`list-issues`, `lint`) treat a missing team as workspace-wide.

Label taxonomy, by contrast, is workspace state — Linear owns it, exposes it via `list-labels`, and any local mirror goes stale the moment a label is added or renamed in the web UI. The config schema does not carry labels; agents and humans call `list-labels` for the authoritative current tree.

## Profile resolution

Order:

1. `--profile <name>` global flag → returns a synthetic binding with that profile and `team=null`. The path's team default does not carry across, because the team was paired with a different profile in the config — the operator is explicitly swapping credentials, so the prior team routing is void. Pass `--team` to set one. Errors if the name isn't in `profiles`.
2. Longest-prefix match on `path_defaults` against the resolved CWD → use the matching binding (profile + team together).
3. Hard error: `no path binding for <cwd>; pass --profile or add a path_defaults entry`.

### Longest-prefix match

For CWD `/workspace/pulsar/scripts/src`, the resolver walks `path_defaults` keys and keeps every prefix that matches at a directory boundary (`cwd == prefix` or `cwd.startswith(prefix.rstrip("/") + "/")`). `/workspace/pulsar` matches; `/workspace/placeframe` does not. Among multiple matches, the longest wins — so `/workspace/placeframe/deeply/nested` resolves via a `/workspace/placeframe/deeply/nested` entry if present, falling back to `/workspace/placeframe`.

The directory-boundary check (`prefix.rstrip("/") + "/"`) prevents `/workspace/place` from matching `/workspace/placeframe`. Plain `str.startswith` would false-positive on sibling directory names that share a stem.

### No `default_profile`

A `default_profile` field was considered and rejected. The only case it would fire: `linear` invoked from a directory with no `path_defaults` entry (home dir, fresh clone, `/tmp`). For a *write path*, silently falling back to a default workspace in those cases is exactly how "filed in the wrong workspace" bugs happen. Error-on-ambiguity is the safe default for a tool whose mutations are auditable and durable. If the operator wants to invoke from an unmapped directory, `--profile <name>` is one flag away and explicit.

## Team behavior

A path binding's `team` field provides the default for every team-scoped verb (`list-issues`, `list-relations`, `lint`, `create-issue`, `create-project`, `update-issue`'s `--state` resolution, `create-workflow-state`, `list-workflow-states`). `--team` overrides it — for writes to other teams in the same workspace, or to repair a path whose binding omits `team`.

## Why not one env var per workspace

`LINEAR_API_KEY_FOUNDATION` / `LINEAR_API_KEY_PERSONAL` would scale linearly with workspace count, survive poorly across `coi shell` env-var limits, and provide no per-repo defaulting. The config-file approach scales to N workspaces without env-var proliferation, supports per-repo routing via `path_defaults`, and keeps secrets out of shell history and process listings.
