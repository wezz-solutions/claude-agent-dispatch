# AgentDispatch — Testing Plan

## Prerequisites
- Plugin installed: `python agent-dispatch/scripts/install.py --enforce`
- MCP server registered in `.mcp.json` under `mcpServers.dispatch`
- Hook registered in `.claude/settings.json` under `hooks.PreToolUse`
- Session restarted after install (MCP server needs fresh load)

## Test 1: MCP Server Loads
**Action:** Check that `dispatch` MCP server is listed in session
**Verify:** 6 tools visible: `mcp__dispatch__run`, `mcp__dispatch__interactive`, `mcp__dispatch__status`, `mcp__dispatch__result`, `mcp__dispatch__cancel`, `mcp__dispatch__config`

## Test 2: Config Tool
**Action:** Call `mcp__dispatch__config`
**Expected:**
- Shows 4 providers (anthropic, ollama, openai, groq)
- Shows 4 agents (general, explore, reviewer, implementer)
- claude-cli: available
- opencode: NOT INSTALLED (unless user installed it)

## Test 3: Hook Blocks Agent Tool
**Action:** Try using native `Agent` tool
**Expected:** Hook blocks with message suggesting `mcp__dispatch__run` translation
**Note:** Hook only blocks at DISPATCH_DEPTH=0 (orchestrator). Dispatched agents bypass.

## Test 4: Headless Dispatch — Haiku (Cheapest)
**Action:** 
```
mcp__dispatch__run(
  query="Test haiku",
  prompt="Reply with exactly: TEST_OK. Nothing else.",
  agent="raw",
  model="haiku"
)
```
**Expected:** DONE status, output contains "TEST_OK", cost ~$0.06, duration ~30s
**Verify:** `.claude/dispatches/d-*.done` file created, `dispatch-audit.jsonl` entry added

## Test 5: Headless Dispatch — Sonnet with Agent
**Action:**
```
mcp__dispatch__run(
  query="Explore project",
  prompt="List the top-level directories in this project and describe what each contains. Be brief.",
  agent="explore",
  model="sonnet"
)
```
**Expected:** DONE, output describes project structure, agent="explore"

## Test 6: Headless Dispatch — Implementer Agent
**Action:**
```
mcp__dispatch__run(
  query="Create test file",
  prompt="Create a file agent-dispatch/tests/test_placeholder.py with a single test function that asserts True. Use pytest style.",
  agent="implementer",
  model="sonnet"
)
```
**Expected:** DONE, file created, FILES_MODIFIED includes test file

## Test 7: Parallel Dispatch
**Action:** Call `mcp__dispatch__run` 2-3 times in a single message
```
# Message 1:
mcp__dispatch__run(query="Task A", prompt="Reply: PARALLEL_A", agent="raw", model="haiku")
# Message 2 (same turn):
mcp__dispatch__run(query="Task B", prompt="Reply: PARALLEL_B", agent="raw", model="haiku")
```
**Expected:** Both complete, both return results. Check dispatch-audit.jsonl has both entries with close timestamps.

## Test 8: Status Tool — No Active
**Action:** `mcp__dispatch__status()`
**Expected:** Lists recent completed dispatches from previous tests

## Test 9: Status Tool — Specific ID
**Action:** `mcp__dispatch__status(id="d-XXXX")` using a dispatch ID from previous test
**Expected:** Shows completed status with agent, model, duration, started timestamp

## Test 10: Interactive Dispatch (Manual)
**Action:**
```
mcp__dispatch__interactive(
  query="Interactive test",
  prompt="Help me understand the project structure",
  model="sonnet"
)
```
**Expected:** 
- Windows Terminal: new split pane opens with Claude session
- Other terminal: new window opens
- Returns dispatch ID immediately
- `mcp__dispatch__status(id="d-XXXX")` shows RUNNING while terminal is open

## Test 11: Cancel Dispatch
**Action:** Start a long dispatch, then cancel:
```
# Start:
mcp__dispatch__run(query="Long task", prompt="Count from 1 to 10000, one number per line", agent="raw", model="haiku")
# In parallel or after timeout: 
mcp__dispatch__cancel(id="d-XXXX")
```
**Expected:** CANCELLED status in .done file

## Test 12: Model Routing — Ollama (Requires OpenCode)
**Skip if** OpenCode not installed
**Action:**
```
mcp__dispatch__run(
  query="Ollama test",
  prompt="Reply: OLLAMA_OK",
  agent="raw",
  model="ollama/qwen3:30b"
)
```
**Expected:** Routes through OpenCode backend. If OpenCode not installed, clear error message.

## Test 13: Custom Agent Definition
**Action:** Create a custom agent file, then dispatch with it:
```
# First create: agent-dispatch/agents/custom-test.md
# Content: "You are a test agent. Always reply with JSON: {\"test\": true}"
# Then:
mcp__dispatch__run(
  query="Custom agent",
  prompt="Respond",
  agent="agent-dispatch/agents/custom-test.md",
  model="haiku"
)
```
**Expected:** Output contains JSON response from custom agent definition

## Test 14: Hang Detection
**Action:** After a dispatch completes, check that marker files are cleaned up
**Verify:** No `.marker` files in `.claude/dispatches/` after all dispatches done

## Test 15: Audit Trail
**Action:** `cat .claude/dispatches/dispatch-audit.jsonl`
**Expected:** One JSONL entry per dispatch with: ts, id, agent, model, provider, status, cost_usd

## Known Limitations (Not Bugs)
- `--bare` mode removed because it skips OAuth. Dispatched agents load project hooks/MCP.
- OpenCode backend untested (requires `go install github.com/opencode-ai/opencode@latest`)
- Interactive dispatch on non-WT/non-tmux terminals opens new window (not split pane)
- Token counts (input_tokens, output_tokens) not parsed from Claude CLI JSON output yet
- Cost is reported but comes from Claude CLI `total_cost_usd` field

## Programmatic Tests Already Passed (Pre-Session)
All of these were verified in the build session:
- [x] All 7 Python files compile clean
- [x] Config resolution (project -> user -> defaults merge)
- [x] Model routing (sonnet/opus/haiku/ollama/openai/groq + empty)
- [x] Agent registry (general/explore/reviewer/implementer/raw)
- [x] Sentinel lifecycle (3 parallel markers, independent completion, cleanup)
- [x] MCP JSON-RPC handshake
- [x] 6 tools registered
- [x] Config tool returns full config
- [x] Status tool lists completed dispatches
- [x] Hook blocks Agent, allows Read, bypasses at DISPATCH_DEPTH=1
- [x] Live dispatch haiku: DONE, $0.06, 30s
- [x] .done file has all fields
- [x] Audit log records both failed + success
- [x] .marker cleanup on completion
