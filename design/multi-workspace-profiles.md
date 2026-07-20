# Multi-workspace profile support

Design rationale for the profile system that lets `linear-cli` write to multiple Linear workspaces from the same machine. The implementation lives in `src/linear_cli/profiles.py` and the `cli.py` resolution helpers; this doc covers the *why* behind the shape.

## Problem

`linear-cli` was placeframe-shaped: one workspace, one team (`PLE`), one consumer repo. It now serves cross-cutting infrastructure — every outernet-foundation repo plus the operator's personal repos want to write to Linear, and pulsar specifically needs a different workspace than placeframe. The single `LINEAR_API_KEY` env var (or walked-up `.env`) forces one workspace per environment. That assumption has to go.

## Config file

Workspace credentials and per-repo routing live in `~/.config/linear-cli/config.json`:

```json
{
  "profiles": {
    "foundation": {
      "api_key": "lin_api_...",
      "paths": ["/workspace/placeframe", "/workspace/governance", "/workspace/linear-cli"]
    },
    "personal": {
      "api_key": "lin_api_...",
      "paths": ["/workspace/pulsar"]
    }
  }
}
```

Location: `~/.config/linear-cli/` (the `-cli` suffix disambiguates from any future official Linear Inc. tooling). Format: JSON, matching the pulsar config convention at `~/.config/pulsar/config.json`. Schema: `profiles.py` pydantic models.

### Why paths are nested under profiles, with flattening on load

Paths are claimed by exactly one workspace — a checkout routes to one credential, not many. Nesting `paths` under the profile they belong to makes that ownership visual: every path in `foundation.paths` resolves to foundation's API key, with no separate `path_defaults` map referencing profiles by name and no per-entry repetition of the profile field. The schema mirrors the natural hierarchy (workspace owns paths) instead of inverting it through a foreign-key-style flat map.

The resolver's lookup pattern is path → profile, which is the inverse of the on-disk nesting. `flatten_paths` resolves that on load: it walks `profiles[*].paths` and produces a single `dict[path, profile_name]` that longest-prefix resolution runs against. The flattening is one pass at config-load time, cached, and the resolver's access pattern stays aligned with its lookup key. The on-disk shape optimizes for human editing and visual grouping; the in-memory shape optimizes for resolver performance. They don't have to match.

An earlier draft used a flat top-level `path_defaults` map keyed by path with profile-name (or `{profile, team}` object) values. That works mechanically but repeats the profile field on every entry and scatters a single workspace's paths alphabetically across the map. The cost of the repetition is small per entry but adds up: scanning "which paths route to foundation?" requires walking every entry, while with nesting the answer is one subtree.

### Why team is not in the config at all

Linear's team concept IS the lifecycle concept — workflow states are team-scoped, so picking a team means picking a lifecycle. A governance resolution moves Drafted → On Agenda → Voted Adopted; a build-script bug moves Backlog → In Progress → Done. Those are categorically different work types that happen to live in the same git repo. `/workspace/governance` produces both, and which lifecycle a given ticket belongs to is a per-ticket decision, not a per-path property.

Forcing `--team` on every team-scoped call surfaces that decision rather than hiding it behind a misleading default. The friction is the feature: it prevents "filed into the wrong lifecycle" mistakes at write time, the way silent defaults cannot. The cost is real (every `create-issue` needs `--team`), but the alternative — a path-level default — only works for single-team repos, and the multi-team case is common enough that the schema shouldn't pretend it doesn't exist.

Two earlier drafts put team in the config:

- `team_key` directly on `Profile`, paired one team per workspace. That shape assumed "one team per workspace," which broke the moment `GOV` was added to the foundation workspace — it forced api_key duplication into a synthetic `governance` profile, which was the smell that surfaced the design weakness.
- `team` on a `path_defaults` entry paired with a profile. That admitted multi-team workspaces but still assumed each path had a natural team, which the governance case disproves: a path can be multi-lifecycle.

The structurally honest position is that team is a per-invocation choice, full stop. The CLI reflects that by making `--team` a required flag on team-scoped writes and never inheriting it from path or profile.

### Why the routing lives in user config, not in the repo

An earlier design proposed a `.linear-profile` marker file committed to each repo root (analogous to `.python-version` or `.nvmrc`). That couples the repo to a specific workspace — wrong layer. The same repo cloned by a different operator (or forked) would inherit a workspace routing decision that doesn't match their setup. Putting paths in user-side config keeps the repo workspace-agnostic: each operator's machine decides which profile a checkout uses, and changing the routing is a local edit, not a commit.

Label taxonomy, by contrast, is workspace state — Linear owns it, exposes it via `list-labels`, and any local mirror goes stale the moment a label is added or renamed in the web UI. The config schema does not carry labels; agents and humans call `list-labels` for the authoritative current tree.

## Profile resolution

Order:

1. `--profile <name>` global flag → use that profile (errors if the name isn't in `profiles`).
2. Longest-prefix match on the flattened path map against the resolved CWD → use the matching profile.
3. Hard error: `no profile resolved for <cwd>; pass --profile or add the path to a profile's paths list`.

### Longest-prefix match

For CWD `/workspace/pulsar/scripts/src`, the resolver walks the flattened path map and keeps every prefix that matches at a directory boundary (`cwd == prefix` or `cwd.startswith(prefix.rstrip("/") + "/")`). `/workspace/pulsar` matches; `/workspace/placeframe` does not. Among multiple matches, the longest wins — so `/workspace/placeframe/deeply/nested` resolves via a `/workspace/placeframe/deeply/nested` entry if present, falling back to `/workspace/placeframe`.

The directory-boundary check (`prefix.rstrip("/") + "/"`) prevents `/workspace/place` from matching `/workspace/placeframe`. Plain `str.startswith` would false-positive on sibling directory names that share a stem.

### No `default_profile`

A `default_profile` field was considered and rejected. The only case it would fire: `linear` invoked from a directory with no matching path entry (home dir, fresh clone, `/tmp`). For a *write path*, silently falling back to a default workspace in those cases is exactly how "filed in the wrong workspace" bugs happen. Error-on-ambiguity is the safe default for a tool whose mutations are auditable and durable. If the operator wants to invoke from an unmapped directory, `--profile <name>` is one flag away and explicit.

## Team behavior

`--team KEY` is required on verbs where team is structurally needed (`create-issue`, `create-project`, `create-workflow-state`, `list-workflow-states`); optional as a filter on `list-issues`, `list-relations`, `lint` (omitting means workspace-wide); conditional on `update-issue` (`--state` requires `--team`; `--team` alone performs a cross-team move) and `update-project` (`--team` alone performs a cross-team move). Every team choice is an explicit per-call decision; the config never supplies one.

## Why not one env var per workspace

`LINEAR_API_KEY_FOUNDATION` / `LINEAR_API_KEY_PERSONAL` would scale linearly with workspace count, survive poorly across `coi shell` env-var limits, and provide no per-repo defaulting. The config-file approach scales to N workspaces without env-var proliferation, supports per-repo routing via the profile's `paths` list, and keeps secrets out of shell history and process listings.
