---
name: dispatch-configure
description: Open the interactive AgentDispatch configurator to add/remove models, set tier spoofing, scan Ollama, and manage providers. Use when user says "configure dispatch", "add model", "dispatch config", "dispatch setup", or "/dispatch-configure".
---

# /dispatch-configure

Interactive configuration for AgentDispatch models, providers, and tier spoofing.

This is an interactive terminal tool — it requires direct user input. Tell the user to run it themselves.

## Action

First, find the plugin directory. Check `DISPATCH_PLUGIN_DIR` env var, or look for `agent-dispatch/scripts/configure.py` relative to the project root.

Then tell the user to type this in the prompt (the `!` prefix runs it interactively in the session):

```
! python <plugin-dir>/scripts/configure.py
```

For user-level config (applies to all projects):

```
! python <plugin-dir>/scripts/configure.py --user
```

To find the path, use:
```
Bash: echo $DISPATCH_PLUGIN_DIR
```
Or check `.mcp.json` for the dispatch server's `DISPATCH_PLUGIN_DIR` env value.

## What it does

The configurator provides a menu-driven interface:

1. **List current configuration** — shows all providers, models, tiers, defaults
2. **Add Ollama model** — auto-detects models from `ollama list`, pick by number
3. **Add OpenAI model** — enter model ID and alias
4. **Add custom provider** — Groq, Together, Fireworks, or any backend
5. **Remove model** — pick from list
6. **Set default model** — choose which model is used when none specified
7. **Set tier spoofing** — make Ollama models appear as Claude tiers (sonnet/haiku/opus)
8. **Toggle enforce dispatch** — enable/disable Agent tool interception
9. **Scan Ollama** — bulk-detect and add all installed Ollama models

## Important

Do NOT try to run configure.py via Bash tool — it needs interactive stdin from the user. Always instruct the user to run it with `!` prefix.
