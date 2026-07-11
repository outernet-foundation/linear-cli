# linear-cli

The audited write path into the team's Linear workspace — a small [typer](https://typer.tiangolo.com/) CLI that talks directly to Linear's GraphQL API over `httpx`, one named operation per call. Every ticket, project, and label write goes through a tool verb, so each mutation is a single reviewable HTTP call rather than an ad-hoc `curl` or an opaque MCP server.

The ticketing conventions this tool enforces (declarative outcome-tickets, imperative titles, the `**Why:** / **Done when:** / **Links:**` body template, `blocks`-for-sequence) and the workspace's team/label taxonomy live in [`AGENTS.md`](./AGENTS.md).

## Setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Provide a Linear API key either in the environment or in a `.env` file at (or above) the working directory:

```bash
export LINEAR_API_KEY=lin_api_...
# or
echo 'LINEAR_API_KEY=lin_api_...' > .env
```

## Usage

```bash
uv run linear --help                 # list every verb
uv run linear list-projects          # read verbs emit one JSON object per row on stdout
uv run linear list-issues --team PLE

# write verbs take the markdown body on stdin and emit the created/updated ids as JSON
uv run linear create-issue --team PLE --title "Delete the pair-consistency gate" <<'EOF'
**Why:** The gate rejects valid two-view pairs and blocks reconstruction.

**Done when:** No pair-consistency check remains in the reconstructor.

**Links:** [reconstructor/AGENTS.md](https://github.com/outernet-foundation/placeframe/blob/dev/docker/reconstructor/AGENTS.md)
EOF
```

`create-issue` and `update-issue` validate the title and body against the conventions before sending the mutation and refuse to write anything off-template. `uv run linear lint --team PLE` audits already-created tickets after the fact.

## Consuming from another repo

git-reference the package and re-expose the `linear` console script from your own `pyproject.toml`:

```toml
[dependency-groups]
dev = ["linear-cli"]

[tool.uv.sources]
linear-cli = { git = "https://github.com/outernet-foundation/linear-cli.git", rev = "<pin-a-commit-sha>" }
```

Then `uv run linear ...` works from that repo's root.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest
```

The validation tests are offline and need no `LINEAR_API_KEY`.
