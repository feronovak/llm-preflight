# MCP server for coding agents

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

This works in Codex CLI, the IDE extension, and the ChatGPT desktop app when
they share Codex configuration. To make it project-scoped instead, add this to
`.codex/config.toml` in a trusted repository:

```toml
[mcp_servers.llm-preflight]
command = "llm-preflight-mcp"
args = ["--workspace", "/absolute/path/to/repository"]
default_tools_approval_mode = "prompt"
```

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

## Available tools

| Tool | What it does | Provider access |
|---|---|---|
| `validate_config` | Validates one benchmark configuration. | Never contacts a provider or loads credentials. |
| `dry_run_plan` | Resolves the redacted request and cost plan. | Never contacts a provider or loads credentials. |
| `run_preflight` | Runs the configured benchmark. | A live-provider run requires explicit paid-run confirmation. |
| `diff_baseline` | Compares two saved result artifacts. | Never contacts a provider. |

`run_preflight` can run a mock benchmark without credentials. Before a live
run, the server requires `confirm_paid_run: true`. For standard clients, this
is an agent-supplied boolean, not proof of user approval. Keep client-side tool
approval enabled and require an explicit user instruction in the agent's
operating rules. Only a confirmed live run may read the
config-adjacent `.env.production`, an explicit workspace-relative environment
file, or keys already supplied to the MCP client process. Mock and
unconfirmed runs do not load those files.

For a completed run, `run_preflight` returns the same `decision` object as the
saved JSON artifact. Agents must consume that structured object instead of
parsing terminal text. A `decision.state` of `inconclusive` requires reporting
each `blocking_warnings` entry verbatim before proposing paid work or approval.
See [Agent decision contract](../reference/decision.md).

## Safe agent workflow

1. Ask the agent to run `validate_config` after an LLM-related change.
2. Ask it to run `dry_run_plan` and report models, request count, and estimated
   cost.
3. Review the plan and explicitly authorize a paid run when appropriate.
4. Use `run_preflight`, then retain the returned evidence or compare it with a
   reviewed baseline using `diff_baseline`.

An agent must not infer model IDs, weaken the application contract, approve a
model, increase a budget, or turn a paid run into an implicit action. See
[Coding agents](coding-agents.md) for the corresponding CLI workflow and
[CI and JSON output](ci.md) for baseline gates.
