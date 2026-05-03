---
name: dispatch
description: Multi-provider agent dispatch — route tasks to Anthropic, Ollama, OpenAI, or any supported model
---

# /dispatch

Manage agent dispatches via the AgentDispatch MCP server.

## Quick Reference

| Tool | Purpose |
|------|---------|
| `mcp__dispatch__run` | Dispatch headless agent (blocks until done) |
| `mcp__dispatch__interactive` | Open interactive terminal session (non-blocking) |
| `mcp__dispatch__status` | Check active dispatches |
| `mcp__dispatch__result` | Get completed result |
| `mcp__dispatch__cancel` | Cancel running dispatch |
| `mcp__dispatch__config` | Show available models/agents/providers |

## Dispatching an Agent

```
mcp__dispatch__run(
  query="Fix auth bug",           # Short label (max 20 chars)
  prompt="Fix the JWT validation  # Full task description
    bug in auth.py line 42...",
  agent="implementer",            # Optional — general if omitted
  model="sonnet"                  # Optional — config default if omitted
)
```

## Model Selection

- **Anthropic** (via Claude CLI): `"sonnet"`, `"opus"`, `"haiku"`
- **Ollama** (via OpenCode): `"ollama/qwen3:30b"`, `"ollama/qwen3:235b"`
- **OpenAI** (via OpenCode): `"openai/gpt-4.1"`
- **Groq** (via OpenCode): `"groq/llama-4-scout"`
- Empty = uses `default_model` from dispatch.json

## Built-in Agents

- `general` — Any task, full tool access
- `explore` — Read-only search and analysis
- `reviewer` — Code review, read-only
- `implementer` — Code implementation, full tool access
- `raw` — No agent definition, prompt goes directly
- Custom: pass file path like `"./my-agents/security.md"`

## Parallel Dispatch

Call `mcp__dispatch__run` multiple times in one message — they execute concurrently:

```
# These run in parallel:
mcp__dispatch__run(query="Fix auth", prompt="...", agent="implementer", model="sonnet")
mcp__dispatch__run(query="Add tests", prompt="...", agent="implementer", model="sonnet")
mcp__dispatch__run(query="Review API", prompt="...", agent="reviewer", model="haiku")
```

## Interactive Sessions

For tasks needing human input, use `mcp__dispatch__interactive`:
- Opens new terminal pane (Windows Terminal split / tmux split)
- Falls back to new window if not in WT or tmux
- User interacts directly with the agent
- Check completion via `mcp__dispatch__status`
