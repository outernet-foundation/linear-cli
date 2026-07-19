# Multi-workspace profile support

Design rationale for the profile system that lets `linear-cli` write to multiple Linear workspaces from the same machine. The implementation lives in `src/linear_cli/profiles.py` and the `cli.py` resolution helpers; this doc covers the *why* behind the shape.

## Problem

`linear-cli` was placeframe-shaped: one workspace, one team (`PLE`), one consumer repo. It now serves cross-cutting infrastructure — every outernet-foundation repo plus the operator's personal repos want to write to Linear, and pulsar specifically needs a different workspace than placeframe. The single `LINEAR_API_KEY` env var (or walked-up `.env`) forces one workspace per environment. That assumption has to go.

## Config file

Workspace facts and per-repo routing live in `~/.config/linear-cli/config.json`:

```json
{
  "profiles": {
    "foundation": { "api_key": "lin_api_...", "team_key": "PLE" },
    "personal":   { "api_key": "lin_api_...", "team_key": "TYL" }
  },
  "path_defaults": {
    "/workspace/placeframe": "foundation",
    "/workspace/pulsar": "personal"
  }
}
```

Location: `~/.config/linear-cli/` (the `-cli` suffix disambiguates from any future official Linear Inc. tooling). Format: JSON, matching the pulsar config convention at `~/.config/pulsar/config.json`. Schema: `profiles.py` pydantic models.

### Why the routing lives in user config, not in the repo

An earlier design proposed a `.linear-profile` marker file committed to each repo root (analogous to `.python-version` or `.nvmrc`). That couples the repo to a specific workspace — wrong layer. The same repo cloned by a different operator (or forked) would inherit a workspace routing decision that doesn't match their setup. Putting `path_defaults` in user-side config keeps the repo workspace-agnostic: each operator's machine decides which profile a checkout uses, and changing the routing is a local edit, not a commit.

### Why team keys live in config, not introspected

A team key is a user-routing fact, not workspace state. Linear exposes the list of teams in a workspace, but cannot tell you which one *this operator* means when writing tickets from *this repo* — that's a per-operator routing decision (foundation has one team today; a workspace with multiple teams would need to pick one per profile). Putting `team_key` in user config makes the choice explicit, profile-scoped, and overridable per-call via `--team`. The field is required on every profile because every Linear workspace has at least one team — Linear creates one on workspace setup, and every issue must belong to a team. An earlier draft allowed `team_key: null` for "team-less personal workspace," but that shape doesn't exist in Linear; nullability only created per-write friction (each write needed `--team` looked up out-of-band) for a hypothetical multi-team case that the `--team` override already handles.

Label taxonomy, by contrast, is workspace state — Linear owns it, exposes it via `list-labels`, and any local mirror goes stale the moment a label is added or renamed in the web UI. The config schema does not carry labels; agents and humans call `list-labels` for the authoritative current tree.

## Profile resolution

Order:

1. `--profile <name>` global flag → use that profile (errors if the name isn't in `profiles`)
2. Longest-prefix match on `path_defaults` against the resolved CWD → use the matching profile
3. Hard error: `no profile resolved for <cwd>; pass --profile or add a path_defaults entry`

### Longest-prefix match

For CWD `/workspace/pulsar/scripts/src`, the resolver walks `path_defaults` keys and keeps every prefix that matches at a directory boundary (`cwd == prefix` or `cwd.startswith(prefix.rstrip("/") + "/")`). `/workspace/pulsar` matches; `/workspace/placeframe` does not. Among multiple matches, the longest wins — so `/workspace/placeframe/deeply/nested` resolves via a `/workspace/placeframe/deeply/nested` entry if present, falling back to `/workspace/placeframe`.

The directory-boundary check (`prefix.rstrip("/") + "/"`) prevents `/workspace/place` from matching `/workspace/placeframe`. Plain `str.startswith` would false-positive on sibling directory names that share a stem.

### No `default_profile`

A `default_profile` field was considered and rejected. The only case it would fire: `linear` invoked from a directory with no `path_defaults` entry (home dir, fresh clone, `/tmp`). For a *write path*, silently falling back to a default workspace in those cases is exactly how "filed in the wrong workspace" bugs happen. Error-on-ambiguity is the safe default for a tool whose mutations are auditable and durable. If the operator wants to invoke from an unmapped directory, `--profile <name>` is one flag away and explicit.

## Team behavior

A profile's `team_key` provides the default for every team-scoped verb (`list-issues`, `list-relations`, `lint`, `create-issue`, `create-project`, `update-issue`'s `--state` resolution). `--team` overrides it for writes to other teams in the same workspace.

## Why not one env var per workspace

`LINEAR_API_KEY_FOUNDATION` / `LINEAR_API_KEY_PERSONAL` would scale linearly with workspace count, survive poorly across `coi shell` env-var limits, and provide no per-repo defaulting. The config-file approach scales to N workspaces without env-var proliferation, supports per-repo routing via `path_defaults`, and keeps secrets out of shell history and process listings.
