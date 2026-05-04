# claude-agent-dispatch

Multi-provider agent dispatch plugin for [Claude Code](https://claude.com/claude-code).

Route tasks to **Anthropic**, **Ollama** (local + cloud), **OpenAI**, **Groq**, or any compatible provider — with parallel execution, tier spoofing, live status, and cost tracking.

---

## Highlights

- **Multi-provider** — Anthropic, Ollama, OpenAI, Groq through one MCP interface
- **True parallel dispatch** — multiple agents run concurrently in a single message
- **Tier spoofing** — Ollama models adopt Claude identity via model aliasing
- **Built-in agents** — general, explore, reviewer, implementer, or bring your own `.md`
- **Interactive sessions** — split terminal pane for human-in-the-loop (Windows Terminal, tmux)
- **Live status line** — real-time token counts, cost, elapsed time, hang detection
- **Audit trail** — JSONL log of every dispatch with cost and token accounting
- **Agent-intercept hook** — optionally redirect all native `Agent` tool calls through dispatch
- **Interactive configurator** — menu-driven model/provider management with Ollama auto-scan

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| [Claude Code](https://claude.com/claude-code) | CLI — desktop app, web app, or IDE extension |
| Python 3.10+ | Runs the MCP server and tools |
| `mcp` package | `pip install mcp` |
| [Ollama](https://ollama.com) | *Optional* — for local/cloud model routing |
| [OpenCode](https://github.com/opencode-ai/opencode) | *Optional* — for OpenAI/Groq backends |

---

## Installation

### From Claude Code (recommended)

```
/plugin install wezz-solutions/claude-agent-dispatch
```

Or install at a specific scope:

```
/plugin install wezz-solutions/claude-agent-dispatch --scope project   # shared via git
/plugin install wezz-solutions/claude-agent-dispatch --scope user      # all your projects
/plugin install wezz-solutions/claude-agent-dispatch --scope local     # this project only, gitignored
```

The plugin automatically:
- Registers the MCP server (6 dispatch tools)
- Creates default `dispatch.json` on first session
- Makes `/dispatch` and `/dispatch-configure` skills available

### Uninstall

```
/plugin uninstall claude-agent-dispatch
```

### Manual install (alternative)

```bash
git clone https://github.com/wezz-solutions/claude-agent-dispatch.git
python claude-agent-dispatch/scripts/install.py            # project-level
python claude-agent-dispatch/scripts/install.py --user     # user-level
python claude-agent-dispatch/scripts/install.py --enforce  # + Agent-intercept hook
```

Restart Claude Code after manual install.

---

## Quick Start

Once installed and Claude Code restarted:

```python
# Dispatch a task
mcp__dispatch__run(
  query="Fix auth bug",
  prompt="Fix the JWT validation bug in auth.py...",
  model="sonnet"
)

# Parallel dispatch — all run concurrently
mcp__dispatch__run(query="Fix auth",   prompt="...", agent="implementer", model="sonnet")
mcp__dispatch__run(query="Add tests",  prompt="...", agent="implementer", model="haiku")
mcp__dispatch__run(query="Review API", prompt="...", agent="reviewer",    model="haiku")

# Use Ollama model
mcp__dispatch__run(query="Quick task", prompt="...", model="ollama/kimi-k2.6:cloud")

# Interactive session (opens split terminal pane)
mcp__dispatch__interactive(query="Debug", prompt="Help debug the auth flow", model="sonnet")

# Check status and configuration
mcp__dispatch__status()
mcp__dispatch__config()
```

### Skills (slash commands)

The plugin registers two Claude Code skills:

| Command | Purpose |
|---------|---------|
| `/dispatch` | Quick reference — tools, models, agents, parallel usage |
| `/dispatch-configure` | Launch the interactive configurator |

---

## MCP Tools

| Tool | Purpose | Blocking |
|------|---------|----------|
| `run` | Dispatch headless agent | Yes — returns result when done |
| `interactive` | Open agent in terminal pane | No — returns immediately |
| `status` | List active/recent dispatches | No |
| `result` | Get completed dispatch result | Polls up to 60s |
| `cancel` | Terminate a running dispatch | No |
| `config` | Show current configuration | No |

### Parameters for `run` and `interactive`

| Parameter | Required | Description |
|-----------|----------|-------------|
| `query` | Yes | Short label, max 20 chars (e.g. `"Fix auth bug"`) |
| `prompt` | Yes | Full task description |
| `agent` | No | Agent type: `general`, `explore`, `reviewer`, `implementer`, `raw`, or path to `.md` file |
| `model` | No | Model alias: `"sonnet"`, `"haiku"`, `"ollama/kimi-k2.6:cloud"`, `"openai/gpt-4.1"` |

---

## Configuration

Configuration resolves in order: **project** > **user** > **defaults**.

| File | Scope |
|------|-------|
| `.claude/dispatch.json` | Project (highest priority) |
| `~/.claude/dispatch.json` | User (all projects) |
| `config/defaults.json` | Plugin defaults (lowest) |

### Interactive configurator

The easiest way to manage configuration. From Claude Code:

```
/dispatch-configure
```

Or directly:

```bash
! python claude-agent-dispatch/scripts/configure.py         # project config
! python claude-agent-dispatch/scripts/configure.py --user  # user config
```

Menu options:
1. List current configuration
2. Add Ollama model (auto-detects from `ollama list`)
3. Add OpenAI model
4. Add custom provider (Groq, Together, etc.)
5. Remove model
6. Set default model
7. Set tier spoofing
8. Toggle enforce dispatch
9. Scan Ollama and bulk-add new models

### Manual configuration

#### dispatch.json reference

```json
{
  "version": 1,
  "default_model": "sonnet",
  "enforce_dispatch": false,
  "max_concurrent": 8,
  "audit": true,
  "default_timeout": 3600,
  "inactivity_threshold": 300,

  "providers": {
    "anthropic": {
      "backend": "claude-cli",
      "models": {
        "opus":   { "id": "claude-opus-4-6",          "timeout": 3600 },
        "sonnet": { "id": "claude-sonnet-4-6",         "timeout": 3600 },
        "haiku":  { "id": "claude-haiku-4-5-20251001", "timeout": 1800 }
      }
    }
  },

  "agents": {
    "general":     { "file": "agents/general.md",     "default_tools": "Bash,Read,Write,Edit,Glob,Grep" },
    "explore":     { "file": "agents/explore.md",      "default_tools": "Read,Glob,Grep" },
    "reviewer":    { "file": "agents/reviewer.md",     "default_tools": "Read,Glob,Grep" },
    "implementer": { "file": "agents/implementer.md",  "default_tools": "Bash,Read,Write,Edit,Glob,Grep" }
  }
}
```

#### Adding Ollama models

```json
"ollama": {
  "backend": "claude-cli",
  "base_url": "http://localhost:11434",
  "models": {
    "kimi-k2.6:cloud":    { "id": "kimi-k2.6:cloud",    "timeout": 3600, "tier": "sonnet" },
    "qwen3.5:397b-cloud": { "id": "qwen3.5:397b-cloud", "timeout": 3600, "tier": "sonnet" },
    "qwen3:8b":           { "id": "qwen3:8b",           "timeout": 1800 },
    "deepseek-r1:8b":     { "id": "deepseek-r1:8b",     "timeout": 1800 }
  }
}
```

Use with provider prefix: `model="ollama/kimi-k2.6:cloud"`.

#### Adding OpenAI / Groq

```json
"openai": {
  "backend": "opencode",
  "opencode_provider": "openai",
  "models": {
    "gpt-4.1":      { "id": "gpt-4.1",      "timeout": 3600 },
    "gpt-4.1-mini": { "id": "gpt-4.1-mini", "timeout": 1800 }
  }
},
"groq": {
  "backend": "opencode",
  "opencode_provider": "groq",
  "models": {
    "llama-4-scout": { "id": "meta-llama/llama-4-scout-17b-16e-instruct", "timeout": 1800 }
  }
}
```

#### Setting a default model

```json
"default_model": "haiku"
```

Per-agent defaults:

```json
"agents": {
  "reviewer": {
    "file": "agents/reviewer.md",
    "default_tools": "Read,Glob,Grep",
    "default_model": "ollama/kimi-k2.6:cloud"
  }
}
```

---

## Tier Spoofing

Tier spoofing routes Ollama models through Claude CLI by aliasing them to Anthropic model names. The dispatched model receives Claude's full system prompt and adopts its identity.

### How it works

1. You set `"tier": "sonnet"` on an Ollama model in `dispatch.json`
2. On dispatch, the plugin runs `ollama cp kimi-k2.6:cloud claude-sonnet-4-6`
3. Claude CLI launches with `--model claude-sonnet-4-6` and `ANTHROPIC_BASE_URL` pointing to Ollama
4. Ollama resolves the alias and serves the actual model (kimi, qwen, etc.)
5. The model receives Claude Code's full system prompt (CLAUDE.md, hooks, skills, memory)

### Configuration

Add `"tier"` to any Ollama model:

```json
"kimi-k2.6:cloud": {
  "id": "kimi-k2.6:cloud",
  "timeout": 3600,
  "tier": "sonnet"       // or "haiku", "opus"
}
```

Or use the interactive configurator: `/dispatch-configure` → option 7.

### Alias management

| Scenario | Behavior |
|----------|----------|
| Alias already correct | Hash check passes, `ollama cp` skipped (instant) |
| Different model mapped to same tier | Hash mismatch detected, re-aliases automatically |
| Multiple concurrent dispatches | Serialized through async lock, no race conditions |
| Alias missing | Created on first dispatch |

### What tier spoofing does and doesn't do

| Aspect | Effect |
|--------|--------|
| Model identity | Model believes it's Claude (reads name from system prompt) |
| System prompt | Full Claude Code context injected (CLAUDE.md, hooks, memory) |
| Cost display | Calculated at tier pricing (cosmetic — no actual charge) |
| Token counts | Vary by model tokenizer, not by tier name |
| Actual inference | Performed by the Ollama model, not by Anthropic |

---

## Agents

### Built-in agents

| Agent | Purpose | Tools |
|-------|---------|-------|
| `general` | Any task | Bash, Read, Write, Edit, Glob, Grep |
| `explore` | Read-only search and analysis | Read, Glob, Grep |
| `reviewer` | Code review | Read, Glob, Grep |
| `implementer` | Code changes | Bash, Read, Write, Edit, Glob, Grep |
| `raw` | No agent definition — prompt goes directly | (inherited) |

### Custom agents

Create a markdown file with your agent system prompt:

```markdown
<!-- my-agents/security-auditor.md -->
You are a security auditor. Review code for OWASP top 10 vulnerabilities.
Focus on: injection, auth flaws, data exposure, misconfigurations.
Report findings with file paths, line numbers, and severity.
```

Dispatch with the file path:

```python
mcp__dispatch__run(
  query="Security scan",
  prompt="Audit the auth module",
  agent="./my-agents/security-auditor.md",
  model="sonnet"
)
```

---

## Agent-Intercept Hook

When installed with `--enforce`, a `PreToolUse` hook intercepts native `Agent` tool calls and redirects them to `mcp__dispatch__run`. This ensures all subagent work flows through the dispatch system.

- Dispatched agents bypass the hook (via `DISPATCH_DEPTH` env var)
- Toggle without reinstalling: set `"enforce_dispatch": true/false` in `dispatch.json`

---

## Status Line

Live dispatch status at the bottom of your Claude Code terminal:

```
3 running | $1.01 (19 done)
  kimi-k2.6:cloud(raw) 23s ↑24.7k/↓17  |  sonnet(explore) 25s ↑42.0k/↓329
  haiku(reviewer) 23s ↑46.2k/↓162
```

| Element | Color | Meaning |
|---------|-------|---------|
| Model name | Blue | Which model is running |
| Agent | Dim | Agent type in parentheses |
| ↑ tokens | Cyan | Input token count |
| ↓ tokens | Magenta | Output token count |
| Running | Bold green | Active dispatch count |
| Cost | Yellow | Cumulative session cost |
| Idle warning | Red | No activity for 5+ minutes |

Refreshes every 1 second.

---

## Architecture

```
claude-agent-dispatch/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── scripts/
│   ├── server.py                # MCP server — 6 tools, FastMCP, async
│   ├── backends.py              # Claude CLI + OpenCode + Interactive backends
│   ├── config.py                # Hierarchical config resolution
│   ├── sentinel.py              # .marker/.done parallel-safe state tracking
│   ├── output_parser.py         # CLI output → structured DispatchResult
│   ├── registry.py              # Agent definition loading
│   ├── statusline.py            # Terminal status line renderer
│   ├── install.py               # Installer / uninstaller
│   └── configure.py             # Interactive model/provider configurator
├── hooks/
│   └── intercept-agent.py       # PreToolUse hook for Agent interception
├── agents/
│   ├── general.md               # General-purpose agent
│   ├── explore.md               # Read-only explorer
│   ├── reviewer.md              # Code reviewer
│   └── implementer.md           # Code implementer
├── config/
│   └── defaults.json            # Default configuration
├── skills/
│   ├── dispatch/SKILL.md        # /dispatch skill
│   └── dispatch-configure/SKILL.md  # /dispatch-configure skill
├── requirements.txt
├── LICENSE                      # MIT
└── README.md
```

### How dispatch flows

```
User calls mcp__dispatch__run(model="ollama/kimi-k2.6:cloud")
  → server.py resolves model via config.py
  → backends.py creates Ollama alias (if tier spoofing)
  → backends.py spawns: claude -p --model claude-sonnet-4-6
    with ANTHROPIC_BASE_URL=http://localhost:11434
  → claude CLI sends request to Ollama
  → Ollama resolves alias → runs kimi-k2.6:cloud
  → response streams back through claude CLI → parsed → returned
```

---

## License

MIT
