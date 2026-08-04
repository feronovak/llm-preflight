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

The server accepts only workspace-relative paths. It supports MCP protocol
version `2026-07-28`.

## Available tools

| Tool | What it does | Provider access |
|---|---|---|
| `validate_config` | Validates one benchmark configuration. | Never contacts a provider or loads credentials. |
| `dry_run_plan` | Resolves the redacted request and cost plan. | Never contacts a provider or loads credentials. |
| `run_preflight` | Runs the configured benchmark. | A live-provider run requires explicit paid-run confirmation. |
| `diff_baseline` | Compares two saved result artifacts. | Never contacts a provider. |

`run_preflight` can run a mock benchmark without credentials. Before a live
run, the client must support paid-run confirmation and the user must approve
it. Only after that confirmation may the server read the config-adjacent
`.env.production`, an explicit workspace-relative environment file, or keys
already supplied to the MCP client process.

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
