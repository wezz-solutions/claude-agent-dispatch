# AgentDispatch Plugin

## Dispatch Protocol
When you need a subagent for any task, use `mcp__dispatch__run` instead of the native Agent tool. The hook enforces this when `enforce_dispatch: true` in dispatch.json.

## Tools

| Tool | Params | Blocks? |
|------|--------|---------|
| `mcp__dispatch__run` | query, prompt, agent?, model? | Yes — returns when agent finishes |
| `mcp__dispatch__interactive` | query, prompt, agent?, model? | No — opens terminal, returns immediately |
| `mcp__dispatch__status` | id? | No |
| `mcp__dispatch__result` | id | Polls up to 60s |
| `mcp__dispatch__cancel` | id | No |
| `mcp__dispatch__config` | (none) | No |

## Parameter Convention
- `query`: mandatory, max 20 chars, short label for what the dispatch does
- `prompt`: mandatory, full task description
- `agent`: optional, defaults to "general". Built-in: general, explore, reviewer, implementer, raw
- `model`: optional, defaults to dispatch.json `default_model`. Examples: "sonnet", "opus", "haiku", "ollama/qwen3:30b"

## Model Routing
- Anthropic models (sonnet, opus, haiku) → Claude CLI backend
- Everything else → OpenCode CLI backend
- Model aliases resolved from dispatch.json providers section
- Explicit provider prefix: `"ollama/qwen3:30b"`, `"openai/gpt-4.1"`

## Parallel Dispatch
Call `mcp__dispatch__run` multiple times in a single message for concurrent execution. The MCP server handles them in parallel via asyncio.

## Hang Detection
Dispatches track last stdout activity. If no activity for 5+ minutes, status reports "possibly hanging". Use `mcp__dispatch__cancel` to terminate stuck agents.

## Configuration
Resolved: project `.claude/dispatch.json` > user `~/.claude/dispatch.json` > plugin defaults.
