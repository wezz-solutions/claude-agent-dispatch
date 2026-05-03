# AgentDispatch — Session Handoff

## What This Is
Standalone MCP plugin for multi-provider agent dispatch in Claude Code. Routes Anthropic models via Claude CLI, everything else via OpenCode CLI. Built 2026-05-04.

## Current State: BUILT + PROGRAMMATICALLY TESTED, NEEDS LIVE SESSION TESTING

### What's Done
- **16 Python/config/markdown files** in `agent-dispatch/`
- **6 MCP tools**: run, interactive, status, result, cancel, config
- **3 backends**: Claude CLI (Anthropic), OpenCode (Ollama/OpenAI/Groq), Interactive (terminal)
- **4 built-in agents**: general, explore, reviewer, implementer
- **Sentinel system**: parallel-safe .marker/.done files with hang detection
- **Status line**: shows dispatch status at bottom of Claude Code terminal
- **Hook**: intercepts native Agent tool, redirects to dispatch
- **Installer**: handles MCP registration, config, hooks, status line (project or user level)
- **Audit trail**: dispatch-audit.jsonl with cost tracking
- **3 git commits** on `main` branch in `agent-dispatch/` repo

### What Passed (Programmatic Tests)
All verified via subprocess/JSON-RPC in build session:
- All Python compiles clean
- Config resolution (project → user → defaults merge)
- Model routing: sonnet/opus/haiku/ollama/openai/groq
- Agent registry: general/explore/reviewer/implementer/raw + custom paths
- Sentinel lifecycle: 3 parallel markers, independent completion, cleanup
- MCP JSON-RPC handshake: server starts, 6 tools registered
- Config tool: full output
- Status tool: lists completed, queries specific
- Hook: blocks Agent, allows Read, bypasses at DISPATCH_DEPTH=1
- **Live dispatch haiku**: DONE, $0.06, 30s, output captured correctly
- .done files, audit log, marker cleanup all work
- Status line script: shows idle / active / hanging states

### What Needs Live Testing (Session Restart Required)
1. MCP server loads in Claude Code session
2. 6 tools visible and callable
3. Hook blocks Agent tool live
4. Status line renders at bottom of terminal
5. Headless dispatch (haiku, sonnet)
6. Agent-based dispatch (explore, implementer)
7. Parallel dispatch (2+ simultaneous)
8. Interactive dispatch (terminal split/window)
9. Cancel dispatch
10. Status/result polling
11. Permission prompts (may need to add mcp__dispatch__* to allow list)

## Key Files

```
agent-dispatch/
├── scripts/server.py          # MCP server entry point (6 tools, ~450 lines)
├── scripts/config.py          # Config resolution
├── scripts/sentinel.py        # .marker/.done management
├── scripts/backends.py        # Claude CLI + OpenCode + Interactive
├── scripts/output_parser.py   # Parse outputs → standard format
├── scripts/registry.py        # Agent definition loading
├── scripts/statusline.py      # Status line for Claude Code
├── scripts/install.py         # Install/uninstall helper
├── hooks/intercept-agent.py   # PreToolUse hook
├── agents/*.md                # 4 built-in agent definitions
├── config/defaults.json       # Default provider/model config
├── .claude-plugin/plugin.json # Plugin manifest
├── CLAUDE.md                  # Instructions for Claude
├── TESTING.md                 # 21-test plan with exact commands
└── HANDOFF.md                 # This file
```

## Configuration Files (Outside Plugin)

```
.mcp.json                      # MCP server registration (mcpServers.dispatch)
.claude/settings.json          # Hook + status line config
.claude/dispatch.json          # Dispatch configuration (providers, models, agents)
.claude/dispatches/            # Sentinel files (.marker, .done, audit log)
```

## How to Test

### Step 1: Restart Claude Code session
The MCP server, hook, and status line need a fresh session to load.

### Step 2: Verify basics
```
mcp__dispatch__config            # Should show providers, agents, backends
mcp__dispatch__status            # Should show "No active dispatches"
```

### Step 3: Run a dispatch
```
mcp__dispatch__run(
  query="Test dispatch",
  prompt="Reply with exactly: HELLO_DISPATCH",
  agent="raw",
  model="haiku"
)
```

### Step 4: Follow TESTING.md
Run through all 21 tests. Fix any issues found.

## Architecture Decisions to Know

1. **No --bare mode**: Removed because it skips OAuth login. Dispatched agents inherit normal auth + project hooks. DISPATCH_DEPTH env var prevents hook interference.

2. **Hook format**: Claude Code requires `{matcher, hooks: [{type, command, timeout}]}` — NOT flat `{matcher, command, timeout}`.

3. **Blocking vs non-blocking**: `run` blocks until agent finishes. `interactive` returns immediately. Parallel dispatch works by calling `run` multiple times in one Claude message.

4. **OpenCode model routing**: No CLI flags for model/provider. Uses `OPENCODE_AGENTS_CODER_MODEL` env var via Viper auto-binding.

5. **Status line**: Reads sentinel .marker/.done files every 3s. Shows active count, agent/model, elapsed, cost, hanging warnings.

## Known Issues / Future Work

- Token counts (input_tokens, output_tokens) not parsed from Claude CLI JSON yet
- OpenCode backend untested (requires `opencode` binary installed)
- Interactive dispatch cleanup (agent.md and prompt files in dispatches dir) not automated
- No `--bare` mode option for users with ANTHROPIC_API_KEY (could be faster startup)
- Custom TUI dashboard (full terminal multiplexer) not built — decided against it
