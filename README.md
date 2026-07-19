# linear-cli

The audited write path into Linear — a small [typer](https://typer.tiangolo.com/) CLI that talks directly to Linear's GraphQL API over `httpx`, one named operation per call. Every ticket, project, and label write goes through a tool verb, so each mutation is a single reviewable HTTP call rather than an ad-hoc `curl` or an opaque MCP server.

The ticketing conventions this tool enforces (declarative outcome-tickets, imperative titles, the `**Why:** / **Done when:** / **Links:**` body template, `blocks`-for-sequence) live in [`AGENTS.md`](./AGENTS.md). The multi-workspace profile system is documented in [`design/multi-workspace-profiles.md`](./design/multi-workspace-profiles.md).

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Create `~/.config/linear-cli/config.json` with one block per Linear workspace plus a `path_defaults` map that routes each repo checkout to a profile:

```json
{
  "profiles": {
    "foundation": { "api_key": "lin_api_...", "team_key": "PLE", "labels": {} },
    "personal":   { "api_key": "lin_api_...", "team_key": null,  "labels": {} }
  },
  "path_defaults": {
    "/workspace/placeframe": "foundation",
    "/workspace/pulsar":     "personal"
  }
}
```

Then `linear list-issues` from `/workspace/pulsar/` uses the personal profile automatically; `--profile foundation` overrides per-call. See [`design/multi-workspace-profiles.md`](./design/multi-workspace-profiles.md) for the full resolution rules.

## Usage

```bash
uv run linear --help                 # list every verb
uv run linear list-projects          # read verbs emit one JSON object per row on stdout
uv run linear list-issues            # team defaults to the resolved profile's team_key

# write verbs take the markdown body on stdin and emit the created/updated ids as JSON
uv run linear create-issue --title "Delete the pair-consistency gate" <<'EOF'
**Why:** The gate rejects valid two-view pairs and blocks reconstruction.

**Done when:** No pair-consistency check remains in the reconstructor.

**Links:** [reconstructor/AGENTS.md](https://github.com/outernet-foundation/placeframe/blob/dev/docker/reconstructor/AGENTS.md)
EOF
```

`--team` defaults to the resolved profile's `team_key`; pass it explicitly to override. `create-issue` and `update-issue` validate the title and body against the conventions before sending the mutation and refuse to write anything off-template. `uv run linear lint` audits already-created tickets after the fact.

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
