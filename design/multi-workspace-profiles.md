# Multi-workspace profile support

Design rationale for the profile system that lets `linear-cli` write to multiple Linear workspaces from the same machine. The implementation lives in `src/linear_cli/profiles.py` and the `cli.py` resolution helpers; this doc covers the *why* behind the shape.

## Problem

`linear-cli` was placeframe-shaped: one workspace, one team (`PLE`), one consumer repo. It now serves cross-cutting infrastructure — every outernet-foundation repo plus the operator's personal repos want to write to Linear, and pulsar specifically needs a different workspace than placeframe. The single `LINEAR_API_KEY` env var (or walked-up `.env`) forces one workspace per environment. That assumption has to go.

## Config file

Workspace facts and per-repo routing live in `~/.config/linear-cli/config.json`:

```json
{
  "profiles": {
    "foundation": {
      "api_key": "lin_api_...",
      "team_key": "PLE",
      "labels": {
        "repo": ["placeframe", "make-it-sing", "infra"],
        "type": ["bug", "feature", "improvement", "chore", "refactor", "docs"]
      }
    },
    "personal": {
      "api_key": "lin_api_...",
      "team_key": null,
      "labels": {}
    }
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

### Why deterministic workspace facts live in config, not prose

Team keys and label taxonomies are deterministic data, not conventions. An earlier draft kept them in this repo's `AGENTS.md` as prose ("one Engineering team keyed PLE"). That conflated two layers: universal conventions the tool enforces (ticket body template, declarative-outcome rules — these apply to *any* workspace) and workspace-specific facts that the tool and agents need to know but that differ per workspace. The split: universal rules stay in `AGENTS.md`; workspace facts migrate to `config.json` where they can differ per profile and where the tool can read them at runtime.

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

## Team-optional behavior

A profile's `team_key` provides the default for every team-scoped verb (`list-issues`, `list-relations`, `lint`, `create-issue`, `create-project`, `update-issue`'s `--state` resolution). `--team` overrides it.

When `team_key` is `null`:

- **Reads** (`list-issues`, `list-relations`, `lint`): no team filter applied, queries paginate workspace-wide.
- **Writes requiring a team** (`create-issue`, `create-project`, `update-issue --state`): the verb errors if no `--team` is passed. Linear requires every issue to belong to a team, so the tool refuses to guess.

This supports both workspace shapes: foundation (one team, `team_key: "PLE"`, conventional defaults) and personal (no team default, `team_key: null`, explicit `--team` per write or a single-team workspace where the user sets `team_key` to whatever Linear created).

## Why not one env var per workspace

`LINEAR_API_KEY_FOUNDATION` / `LINEAR_API_KEY_PERSONAL` would scale linearly with workspace count, survive poorly across `coi shell` env-var limits, and provide no per-repo defaulting. The config-file approach scales to N workspaces without env-var proliferation, supports per-repo routing via `path_defaults`, and keeps secrets out of shell history and process listings.
