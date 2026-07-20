# linear-cli

The audited write path into Linear — a small [typer](https://typer.tiangolo.com/) CLI that talks directly to Linear's GraphQL API over `httpx`, one named operation per call. Every ticket, project, and label write goes through a tool verb, so each mutation is a single reviewable HTTP call rather than an ad-hoc `curl` or an opaque MCP server.

The ticketing conventions this tool enforces (declarative outcome-tickets, imperative titles, the `**Why:** / **Done when:** / **Links:**` body template, `blocks`-for-sequence) live in [`AGENTS.md`](./AGENTS.md). The multi-workspace profile system is documented in [`design/multi-workspace-profiles.md`](./design/multi-workspace-profiles.md).

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Create `~/.config/linear-cli/config.json` with one block per Linear workspace. Each profile carries the workspace's API key and the list of filesystem paths that route to it (paths are nested under profiles and flattened on load):

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

Then `linear --profile foundation list-issues --team PLE` works from anywhere; from `/workspace/pulsar/` the profile resolves automatically via the paths list, and only `--team TYL` is needed. `--team` is required on every team-scoped write — there is no path-level team default, because picking a team means picking a ticket lifecycle, and a single repo can produce tickets in multiple lifecycles. See [`design/multi-workspace-profiles.md`](./design/multi-workspace-profiles.md) for the full resolution rules.

## Usage

```bash
uv run linear --help                 # list every verb
uv run linear list-projects          # read verbs emit one JSON object per row on stdout
uv run linear list-issues --team PLE # team is explicit; omit for workspace-wide
```

`--team` is required on team-scoped writes (`create-issue`, `create-project`, `create-workflow-state`, `list-workflow-states`), optional as a filter on `list-issues`/`list-relations`/`lint`, and used for cross-team moves on `update-issue`/`update-project`. `create-issue` and `update-issue` validate the title and body against the conventions before sending the mutation and refuse to write anything off-template. `uv run linear lint` audits already-created tickets after the fact.

## Global install (optional)

Install once per machine so `linear` is on PATH from any repo, without per-repo `uv run`:

```bash
uv tool install git+https://github.com/outernet-foundation/linear-cli.git
```

## Consuming from another repo (legacy per-repo)

Git-reference the package and re-expose the `linear` console script from your own `pyproject.toml`:

```toml
[dependency-groups]
dev = ["linear-cli"]

[tool.uv.sources]
linear-cli = { git = "https://github.com/outernet-foundation/linear-cli.git", rev = "<pin-a-commit-sha>" }
```

Then `uv run linear ...` works from that repo's root. The global `uv tool install` flow above is preferred for new setups.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest
```

The validation tests are offline and need no profile config.
