# linear-cli

## What this is

`linear-cli` is the audited write path into Linear: a small typer CLI (`uv run linear`) that talks directly to Linear's GraphQL API over `httpx`, one named operation per call. It exists so that every ticket or project write — from an agent or a human — is transparent, reviewable, and on-convention, rather than an ad-hoc `curl` or an opaque MCP server. Beyond the tool, this doc is the home for **the universal conventions every ticket follows** — the rules the tool enforces via `validation.py`, applicable to any workspace the tool is pointed at. Workspace-specific facts (team keys) are deterministic data living in `~/.config/linear-cli/config.json`, not prose here; label taxonomy is introspectable live via `list-labels`.

The package is `linear_cli` (src-layout under `src/linear_cli/`); consumer repos git-reference it and re-expose the `linear` console script through their own `[project.scripts]`, or install it globally via `uv tool install`.

## Shape

### The tool

- `cli.py` — the typer app plus the `httpx` GraphQL client. `graphql()` sends the whole operations document with an `operationName` and validates the reply into a pydantic model. Credentials resolve via `~/.config/linear-cli/config.json` profiles (with a `--profile` global override and per-cwd `path_defaults` longest-prefix resolution); the tool errors if no config exists. Verbs: `list-issues`, `get-issue`, `list-relations`, `list-projects`, `list-labels`, `snapshot`, `lint`, `ensure-label`, `update-label`, `delete-label`, `create-project`, `create-issue`, `update-project`, `delete-project`, `update-issue`, `link`, `comment`, `delete-comment`. Six read verbs: `list-issues` paginates a team's issues so a caller can dedup before writing (each row carries its `project` name, or null when the issue is loose, plus `created_at` so a caller can triage by age — e.g. separate pre-pivot legacy tickets from recent ones; with no team resolved, paginates workspace-wide), `get-issue` fetches one issue's full body (identifier, title, description, state, project, created_at, url) by id so a caller can read a ticket's current scope before folding related work into it, `list-relations` paginates the same issues and emits one `{source, target, type}` row per outgoing relation (each `blocks` edge exactly once, read off the blocker's `relations` connection — the mirror `inverseRelations` on the blocked issue is not walked) so a caller can reconstruct the dependency graph the `link` verb writes, `list-projects` paginates the workspace's projects (id, name, state, url) so a caller can resolve a project id for `create-issue --project` and audit which initiatives exist, `list-labels` dumps the whole label tree (id, name, color, group flag, resolved parent name) so a caller can resolve ids and audit the label taxonomy, and `snapshot` freezes a set of issues (`--issue` repeatable, or `--label`) as a single indented JSON document on stdout carrying each issue's id, identifier, title, description, state, labels, and comments — sorted by numeric-aware identifier key — so a caller can capture Linear state into git at a point in time and re-render derived artifacts from the snapshot alone without further Linear access; the rest are writes, save `lint`, which reads every non-closed team issue and emits one row per body that violates the template (missing a canonical section header, a non-absolute or retired link, an ordinal/label title prefix), exiting non-zero if any do — the audit backstop for tickets authored directly in the Linear web UI, which the write-path gate below cannot reach. Its `--design-orphans` flag adds the reverse check — it walks `design/*.md` (relative to the working directory) and flags any design doc that no open ticket links, enforcing the rule that every design doc has a tracking ticket. The three label writes cover a label's full lifecycle: `ensure-label` find-or-creates a leaf (optionally nested under a group), `update-label` renames, recolors, and/or reparents an existing label by id, and `delete-label` removes one by id. Because a reparent is a partial update that leaves color untouched, a caller preserving a label's color across a group move reads the current hex from `list-labels` and passes it straight back through `update-label --color`. `update-issue` also moves an issue through its workflow: `--state NAME --team KEY` resolves the named state against that team's workflow states and sets it, which is how an issue is closed. `--project ID` re-homes a loose issue under a project (or moves it between projects), the write counterpart to the loose-issue triage `list-issues` enables. `comment` posts a markdown comment (from stdin) onto an issue by id — the home for concrete, point-in-time working notes such as sweep findings or specific file sites, which the status-free, declarative description rules deliberately keep out of the issue body. `delete-comment` removes a comment by id — the corrective counterpart to `comment`, since Linear comments cannot be edited in place, so fixing one means deleting and reposting. `delete-project` removes a project by id — the container-level corrective when an initiative is retired outright rather than completed; the tool exposes no project state mutation (the web UI's cancel/archive is not surfaced here), so deletion is the only retirement path through this CLI, and the project's direct issues should be retired first (`update-issue --state Canceled --team`) so the container is empty. `--team` on every team-scoped verb defaults to the resolved profile's `team_key`; pass it explicitly to override. Rich markdown bodies arrive on **stdin**; created/updated ids (and, for the read verbs, one line per row) are emitted as JSON on **stdout** so a caller can thread them into later calls.
- `profiles.py` — pydantic models and resolver for `~/.config/linear-cli/config.json`. Holds the profile schema (`api_key`, `team_key` per profile; `path_defaults` mapping repo paths to profile names) and the longest-prefix resolver that picks a profile from CWD. No `default_profile` — resolution errors loudly rather than silently falling back, since a wrong-workspace write on a write path is the exact bug silent defaults produce.
- `snapshot.py` — pure helpers for the `snapshot` verb: the Linear `IssueFilter` shape for label-based selection and the numeric-aware identifier sort key (`PLE-9` before `PLE-10`). Separated from `cli.py` so the pure logic is unit-testable without standing up the typer/httpx stack.
- `linear_operations.graphql` — the named GraphQL operations, one per verb, kept as a real `.graphql` file for syntax highlighting. It is loaded at runtime by relative path next to `cli.py`, so it must ship inside the wheel (see the packaging constraint below).
- `validation.py` — the title/body convention checks, shared by the `create-issue`/`update-issue` write gate and the `lint` audit so the two can never disagree.

### Profiles

Workspace facts and per-repo routing live in `~/.config/linear-cli/config.json`, not in this doc and not committed to any repo. Shape:

```json
{
  "profiles": {
    "foundation": { "api_key": "...", "team_key": "PLE" },
    "personal":   { "api_key": "...", "team_key": "TYL" }
  },
  "path_defaults": {
    "/workspace/placeframe": "foundation",
    "/workspace/pulsar":     "personal"
  }
}
```

Profile resolution order: `--profile <name>` flag (if given) → longest-prefix match on `path_defaults` against the resolved CWD → hard error. No silent default. A profile's `team_key` provides the default for every team-scoped verb; pass `--team` to override. `team_key` is required on every profile because every Linear workspace has at least one team — Linear creates one on workspace setup, and every issue must belong to a team. Label taxonomy is not mirrored in config — `list-labels` is authoritative and always current.

### Projects

**Projects** exist only for real multi-issue initiatives. A project's direct issues are its phases/workstreams; sequence between them is modeled with `blocks` relations, and each phase explodes into ~1:1-with-PR sub-issues when it is picked up.

## Constraints

**Direct GraphQL, not MCP and not hand-rolled `curl`.** The workspace is written to rarely and by few actors, so MCP's managed-OAuth convenience does not pay for its opacity; a direct client is portable to every context (agent, CI, by hand) and every mutation is one auditable HTTP call. Every write goes through a tool verb — do not hand-write mutations or add an MCP. When a new kind of write is needed, add a verb and its named operation.

**The operations document must ship in the wheel.** `linear_operations.graphql` is loaded at runtime via `Path(__file__).with_name(...)`, so an editable install works from the source tree by accident — but a real wheel omits non-Python files unless they are named explicitly. `[tool.hatch.build.targets.wheel] include` lists both `linear_operations.graphql` and `py.typed`; drop either and the built wheel breaks every command (the `.graphql` at first API call, the marker silently for downstream type checkers). The CI wheel-build is the guard.

**Tickets are declarative and durable, not plan files.** A ticket states an *outcome that is not yet true*, not a sequence of steps to reach it. This is the root convention; the rest follow from it.

- **No implementation plans in a ticket** — no file lists, no step sequences. Which files are relevant goes stale between authoring and pickup, and discovering the current surface is the first act of implementation. The implementer captures it as just-in-time sub-issues or in the PR, not the author up front.
- **The done-condition is a verifiable invariant, not a task checklist.** "Zero `NDArray` imports outside generated code" survives a year and a grep confirms it; "migrate the thirteen files" rots the moment the tree moves.
- **Descriptions are status-free.** Progress lives in the issue's state, sub-issue completion, comments, and the project bar — never baked into description prose ("already done: X"). Status in prose is wrong the moment it is written.
- **Design depth lives in the co-located `AGENTS.md`; the ticket links to it.** Ticket ≠ doc. Mechanism and rationale that outlive the ticket belong in that doc, not inlined into the ticket body.

**Titles are imperative, verb-first, and outcome-oriented.** No ordinal prefixes — sequence is the `blocks` graph's job, and a prefix is a second, dumber copy that goes stale on reorder. No `repo`/`type` prefixes — labels carry those. Titles are the primary index and generate branch slugs, so they stay short and jargon-free.

**Body template: three parts, one canonical dialect.** The section headers are exactly `**Why:**`, `**Done when:**`, and `**Links:**` — bold, trailing colon, that spelling — and each section's text begins on the *same line* as its header (`**Why:** <text>`, not the header alone on its own line), so bodies can't drift into the `**Why.**` / `**Why**` / `### Why` or header-then-blank-line variants a hand-authored board accumulates. `**Why:**` is one to three self-contained sentences (a cold reader with no other docs open still understands the ticket); `**Done when:**` is the invariant; `**Links:**` is the spec, project, and related issues. The same-line rule is enforced for `Why` and `Done when`; `Links` takes the colon too but may run its references as a following bulleted list. Nothing else by default.

**The template is enforced at the write path, not by convention alone.** `create-issue` and `update-issue` validate the title and body before sending the mutation and refuse — non-zero exit, nothing written — anything off-template: a missing canonical header, a link target that isn't an absolute URL, a retired `SPEC.md` or `.pulsar/memories` pointer, or an ordinal/label title prefix. Because this tool is the sole sanctioned write path, a malformed ticket cannot be created *through it*; the one hole the model can't close is a body typed directly into the Linear web UI, which the `lint` sweep catches after the fact. The rules live in `validation.py`, shared by both write verbs and `lint`, so the gate and the audit can never disagree.

**Links are real URLs, never repo-relative paths.** Linear has no repo context, so a bare `core/AGENTS.md` renders as inert monospace text that resolves to nothing — a breadcrumb, not a link. A spec link must be a full GitHub blob URL on `dev` with the complete path (`https://github.com/outernet-foundation/placeframe/blob/dev/packages/python/core/AGENTS.md`), so it stays clickable and tracks the living file.

**Sequence lives in `blocks` relations, never in titles or prose.** The graph is queryable ("what is unblocked right now?") and stays correct when the plan changes; prose ordering is neither.

**A big initiative is a Project + phase-issues + a `blocks` graph + just-in-time file sub-issues.** The project's direct issues are coarse phases. The fine, ~1:1-with-PR units are sub-issues created at the last responsible moment when a phase is picked up — never enumerated up front, because per-file scope goes stale before it is worked.

**Priority is ignored.** The built-in priority field is unused; do not set it.

## See also

- `README.md` — human-facing setup and usage.
- [`design/multi-workspace-profiles.md`](./design/multi-workspace-profiles.md) — design rationale for the profile system: config schema, path-defaults resolution, no-default-profile decision, team-optional behavior.
