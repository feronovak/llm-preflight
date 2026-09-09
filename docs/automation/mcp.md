# MCP server for coding agents

**Last reviewed:** 2026-09-09 · **As of:** v2.14.0

`validate_config` and `dry_run_plan` also inspect configured local image inputs
without reading credentials or calling a provider. Their pre-run image cost is
reported as unavailable rather than guessed. Image generation remains outside
the MCP workflow.

LLM Preflight includes a local stdio MCP server so a coding agent can collect
the same preflight evidence without parsing shell output or gaining arbitrary
command execution. It is a local validation gate, not a hosted service.

## Configure a workspace

Configure your MCP client to start the installed command with the repository
that contains the benchmark configuration:

```json
{
  "mcpServers": {
    "llm-preflight": {
      "command": "llm-preflight-mcp",
      "args": ["--workspace", "/absolute/path/to/repository"]
    }
  }
}
```

The server accepts only workspace-relative paths. It supports the standard MCP
initialization flow used by current coding agents (protocol version
`2025-06-18`) as well as its existing `2026-07-28` discovery flow.

For a confirmed live run, a benchmark's relative `env_file` reference is
accepted only when its resolved path remains within that workspace. An explicit
MCP `env_file` argument has the same boundary. The server never returns a key
or env-file contents.

## Registry discovery

[`server.json`](../../server.json) is the versioned manifest for the official
MCP Registry. It identifies the public PyPI package and its local stdio
transport, including a required `--workspace` filepath argument; the registry
stores metadata, not the server artifact. The manifest is published only after
the matching package version is available on PyPI.

The repository also includes a small Codex plugin at
`plugins/llm-preflight/`. Its skill teaches the no-spend workflow but
deliberately does not bundle an MCP command: choosing the workspace remains an
explicit, project-local setup decision.

On the standard protocol path, `tools/list` also declares a client-visible
safety hint for every tool and a JSON output schema for its structured result.
`validate_config`, `dry_run_plan`, and `diff_baseline` are read-only and closed
to the external world. `run_preflight` is marked as external-world capable,
because a confirmed live configuration can contact a provider.

## Connect common coding agents

Install the package in an environment whose `llm-preflight-mcp` command the
agent can run, then choose the matching local MCP setup below. Keep the
workspace path absolute. The server reads only paths below it.

### Codex

From the repository you want to validate:

```bash
codex mcp add llm-preflight -- llm-preflight-mcp --workspace "$PWD"
codex mcp list
```

This configures the Codex CLI. The IDE extension also accepts a local stdio
command through its MCP servers settings. To make the CLI setup project-scoped,
add this to `.codex/config.toml` in a trusted repository:

```toml
[mcp_servers.llm-preflight]
command = "llm-preflight-mcp"
args = ["--workspace", "/absolute/path/to/repository"]
default_tools_approval_mode = "prompt"
```

The official Codex MCP configuration supports the `prompt` approval mode. Keep
that mode: the server’s read-only hints can streamline no-spend tools, while a
live preflight remains visible for review.

### Claude Code

From the repository you want to validate, add a project-scoped server:

```bash
claude mcp add llm-preflight --scope project -- \
  llm-preflight-mcp --workspace "$PWD"
claude mcp list
```

Claude Code records project-scoped servers in `.mcp.json`; review the resulting
configuration before committing it. Use `--scope user` instead when the same
server should be available across projects.

### Cursor

Create `.cursor/mcp.json` in the repository (or `~/.cursor/mcp.json` for a
personal global installation):

```json
{
  "mcpServers": {
    "llm-preflight": {
      "command": "llm-preflight-mcp",
      "args": ["--workspace", "/absolute/path/to/repository"]
    }
  }
}
```

Restart Cursor, enable the server in the MCP tools list, and ask the agent to
use `validate_config` or `dry_run_plan` by name. Leave tool approval enabled.

## Clean-install verification

The TestPyPI validation workflow installs the exact published package in a new
virtual environment, starts `llm-preflight-mcp`, and verifies `initialize` plus
the safe-workflow resource without credentials or provider traffic. The three
client setups above all invoke that same local stdio command; client UI setup
remains a user-controlled workspace decision.

## Available tools

| Tool | What it does | Provider access |
|---|---|---|
| `validate_config` | Validates one benchmark configuration. | Never contacts a provider or loads credentials. |
| `dry_run_plan` | Resolves the redacted request, cost plan, and per-model `smoke_eligibility`. | Never contacts a provider or loads credentials. |
| `run_preflight` | Runs the configured benchmark. | A live-provider run requires explicit paid-run confirmation. |
| `diff_baseline` | Compares two saved result artifacts. | Never contacts a provider. |

## Discover the safe workflow

Clients that support MCP resources can read
`llm-preflight://guides/safe-workflow`. It is a short, static no-spend-first
checklist: validate, inspect the dry-run plan, stop for explicit user approval,
then use `run_preflight` only with `confirm_paid_run: true`. Reading this
resource never accesses the workspace, loads credentials, or contacts a
provider.

`run_preflight` can run a mock benchmark without credentials. Before a live
run, the server requires `confirm_paid_run: true`. For standard clients, this
is an agent-supplied boolean, not proof of user approval. Keep client-side tool
approval enabled and require an explicit user instruction in the agent's
operating rules. Only a confirmed live run may read the
config-adjacent `.env.production` or an explicit workspace-relative environment
file, and both resolved paths must remain inside the workspace (including after
symlink resolution). Keys already supplied to the MCP client process remain
available. Mock and unconfirmed runs do not load environment files.

For a completed run, `run_preflight` returns the same `decision` object as the
saved JSON artifact. Agents must consume that structured object instead of
parsing terminal text. A `decision.state` of `inconclusive` requires reporting
each `blocking_warnings` entry verbatim before proposing paid work or approval.
See [Agent decision contract](../reference/decision.md).

## Safe agent workflow

1. Ask the agent to run `validate_config` after an LLM-related change.
2. Ask it to run `dry_run_plan` and report models, request count, estimated
   cost, and every non-eligible `smoke_eligibility` reason.
3. Review the plan and explicitly authorize a paid run only after the intended
   smoke cohort is eligible and bounded.
4. Use `run_preflight`, then retain the returned evidence or compare it with a
   reviewed baseline using `diff_baseline`.

An agent must not infer model IDs, weaken the application contract, approve a
model, increase a budget, or turn a paid run into an implicit action. See
[Coding agents](coding-agents.md) for the corresponding CLI workflow and
[CI and JSON output](ci.md) for baseline gates.
