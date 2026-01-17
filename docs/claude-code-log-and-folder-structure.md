# Claude Code Log Structure & Folder Architecture

## Overview

This document provides a comprehensive reference for Claude Code's data storage and logging architecture in `~/.claude/`.

---

## Part 1: Session Log Structure (JSONL Files)

### File Location
```
~/.claude/projects/{project-path-hash}/{session-id}.jsonl
```

Example:
```
~/.claude/projects/-Users-thein-repos-my-project/08fce8c2-8453-42da-a52c-e03472c24e0f.jsonl
```

### Entry Type Taxonomy

#### Core Entry Types

| Type | Frequency | Purpose |
|------|-----------|---------|
| `progress` | High | Execution flow and hook lifecycle tracking |
| `attachment` | High | Hook results, system reminders, plan mode state |
| `assistant` | Medium | Claude's responses (with streaming) |
| `user` | Medium | User input messages |
| `system` | Low | System-level events with subtypes |
| `summary` | Low | Session summaries |
| `file-history-snapshot` | Low | File backup tracking for undo |
| `queue-operation` | Rare | Queue management |

#### Universal Base Fields

All entries share these common fields:

```json
{
  "parentUuid": "uuid",           // Links to parent entry (forms tree structure)
  "isSidechain": boolean,         // True for subagent/parallel execution
  "userType": "external",         // User type classification
  "cwd": "/path/to/directory",    // Current working directory
  "sessionId": "uuid",            // Session identifier
  "version": "2.1.9",             // Claude Code version
  "gitBranch": "branch-name",     // Current git branch (if in repo)
  "type": "string",               // Entry type
  "uuid": "uuid",                 // Unique entry identifier
  "timestamp": "ISO8601",         // Entry timestamp
  "slug": "plan-name"             // Plan mode identifier (optional)
}
```

---

### Detailed Entry Structures

#### 1. User Entry

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": "string or array of content blocks"
  },
  "isMeta": boolean,              // True for system/metadata messages
  "thinkingMetadata": {           // Extended thinking configuration
    "level": "high|medium|low",
    "disabled": boolean,
    "triggers": []
  },
  "todos": [],                    // Current todo list state
  "toolUseResult": {              // Present when returning tool results
    "query": "search query",
    "results": [],
    "durationSeconds": 18.23
  },
  "sourceToolAssistantUUID": "uuid"  // Links to assistant that invoked tool
}
```

**Content Variants:**
- Simple text: `"content": "user message text"`
- Tool result: `"content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]`
- Command output: `"content": "<local-command-stdout>...</local-command-stdout>"`
- Meta message: `"content": "<local-command-caveat>...</local-command-caveat>"`

#### 2. Assistant Entry

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-5-20251101",
    "id": "msg_xxxxx",            // Same ID across streaming entries
    "type": "message",
    "role": "assistant",
    "content": [
      {"type": "text", "text": "Response text..."},
      {"type": "tool_use", "id": "toolu_xxx", "name": "ToolName", "input": {}},
      {"type": "thinking", "thinking": "Extended thinking...", "signature": "..."}
    ],
    "stop_reason": "end_turn|tool_use|null",
    "stop_sequence": null,
    "usage": {
      "input_tokens": 9,
      "output_tokens": 100,
      "cache_creation_input_tokens": 1172,
      "cache_read_input_tokens": 29916,
      "cache_creation": {
        "ephemeral_5m_input_tokens": 1172,
        "ephemeral_1h_input_tokens": 0
      },
      "service_tier": "standard"
    }
  },
  "requestId": "req_xxxxx"
}
```

**Content Block Types:**
- `text` - Regular text response
- `tool_use` - Tool invocation with id, name, and input
- `thinking` - Extended thinking with cryptographic signature

#### 3. Progress Entry

```json
{
  "type": "progress",
  "data": {
    "type": "hook_progress|agent_progress|query_update|search_results_received|turn_duration",
    "hookEvent": "PreToolUse|PostToolUse|SessionStart|Stop",
    "hookName": "PreToolUse:Bash",
    "command": "script path or variable",
    "query": "search query",          // For search operations
    "resultCount": 10,                // For search results
    "durationMs": 32853               // For turn_duration
  },
  "toolUseID": "toolu_xxxxx",
  "parentToolUseID": "toolu_xxxxx"
}
```

**Data Type Variants:**
- `hook_progress` - Hook execution progress
- `agent_progress` - Subagent task progress
- `query_update` - Search query updates
- `search_results_received` - Search results received
- `turn_duration` - Turn timing information

#### 4. Attachment Entry

```json
{
  "type": "attachment",
  "attachment": {
    "type": "hook_success|plan_mode|critical_system_reminder|todo_reminder",

    // For hook_success:
    "hookName": "PreToolUse:Bash",
    "hookEvent": "PreToolUse",
    "toolUseID": "toolu_xxxxx",
    "exitCode": 0,
    "stdout": "",
    "stderr": "",
    "content": "",

    // For plan_mode:
    "reminderType": "full",
    "isSubAgent": boolean,
    "planFilePath": "/path/to/plan.md",
    "planExists": boolean,

    // For critical_system_reminder:
    "content": "reminder text"
  }
}
```

#### 5. System Entry

```json
{
  "type": "system",
  "subtype": "stop_hook_summary|turn_duration|local_command",
  "hookCount": 2,
  "hookInfos": [{"command": "script path"}],
  "hookErrors": [],
  "preventedContinuation": boolean,
  "stopReason": "",
  "hasOutput": boolean,
  "durationMs": 32853,
  "level": "suggestion|info|warning",
  "content": "command output",         // For local_command
  "isMeta": boolean
}
```

#### 6. File History Snapshot

```json
{
  "type": "file-history-snapshot",
  "messageId": "uuid",
  "snapshot": {
    "messageId": "uuid",
    "trackedFileBackups": {
      "/path/to/file": {
        "backupFileName": "hash@v1",
        "version": 1,
        "backupTime": "ISO8601"
      }
    },
    "timestamp": "ISO8601"
  },
  "isSnapshotUpdate": boolean
}
```

#### 7. Summary Entry

```json
{
  "type": "summary",
  "summary": "Brief description of the session",
  "leafUuid": "uuid"              // Reference to last message
}
```

#### 8. Queue Operation Entry

```json
{
  "type": "queue-operation",
  "operation": "enqueue|popAll",
  "content": "queued content",
  "sessionId": "uuid",
  "timestamp": "ISO8601"
}
```

---

### Streaming Behavior

Claude logs streaming responses as multiple entries with the same `message.id`:

1. Assistant entry with `thinking` block
2. Assistant entry with `text` content
3. Assistant entry with `tool_use` block
4. Progress entries (PreToolUse hooks)
5. Attachment entries (hook results)
6. User entry with `tool_result`
7. Progress entries (PostToolUse hooks)

---

## Part 2: ~/.claude/ Folder Structure

### Complete Directory Map

```
~/.claude/
├── CLAUDE.md                    # Global user instructions for all projects
├── settings.json                # Main configuration (model, hooks, plugins)
├── settings.local.json          # Local permission overrides
├── stats-cache.json             # Usage statistics cache
├── history.jsonl                # All user prompts across sessions
│
├── projects/                    # Project-specific session data
│   └── {project-path-hash}/
│       ├── {session-id}.jsonl   # Session conversation logs
│       ├── sessions-index.json  # Index of all sessions
│       ├── subagents/           # Subagent conversation logs
│       │   └── agent-{id}.jsonl
│       └── tool-results/        # Cached tool execution results
│
├── todos/                       # Per-session todo files
│   └── {uuid}.json
│
├── file-history/                # File version backups for undo
│   └── {session-id}/
│       └── {hash}@v{version}
│
├── plans/                       # Plan mode documents
│   ├── {slug}.md                # Main session plans (e.g., lazy-jumping-glacier.md)
│   └── {slug}-agent-{agentId}.md  # Subagent plans
│
├── skills/                      # Custom skill definitions
│   └── {skill-name}/
│       ├── SKILL.md
│       ├── scripts/
│       └── references/
│
├── plugins/
│   ├── repos/                   # Plugin source repositories
│   └── cache/                   # Installed plugin cache
│       └── {plugin-name}/
│           ├── agents/
│           ├── commands/
│           ├── scripts/
│           └── .claude-plugin/
│
├── session-env/                 # Session environment snapshots
│   └── {session-id}/
│
├── shell-snapshots/             # Shell state captures
│   └── snapshot-zsh-{timestamp}-{random}.sh
│
├── debug/                       # Session debug logs
│   └── {uuid}.txt
│
├── config/                      # Configuration state
│   └── notification_states.json
│
├── cache/                       # General cache (changelog, etc.)
├── ide/                         # IDE lock files
├── downloads/                   # Download cache
├── paste-cache/                 # Clipboard paste history
├── telemetry/                   # Usage telemetry data
└── statsig/                     # Feature flag configuration
```

---

### Key File Formats

#### todos/{uuid}.json
```json
[
  {
    "content": "Task description",
    "status": "pending|in_progress|completed",
    "id": "unique-id",
    "activeForm": "Doing task description"  // Present tense form
  }
]
```

#### sessions-index.json
```json
{
  "version": 1,
  "entries": [{
    "sessionId": "uuid",
    "fullPath": "/full/path/to/session.jsonl",
    "fileMtime": 1768607527071,
    "firstPrompt": "User's first message",
    "messageCount": 17,
    "created": "ISO8601",
    "modified": "ISO8601",
    "gitBranch": "main",
    "projectPath": "/path/to/project",
    "isSidechain": false
  }]
}
```

#### stats-cache.json
```json
{
  "version": 1,
  "lastComputedDate": "2026-01-16",
  "dailyActivity": [
    {"date": "2026-01-16", "messageCount": 50, "sessionCount": 3, "toolCallCount": 120}
  ],
  "dailyModelTokens": {
    "2026-01-16": {
      "claude-opus-4-5": {"input": 50000, "output": 10000}
    }
  },
  "modelUsage": {
    "claude-opus-4-5-20251101": {
      "inputTokens": 1000000,
      "outputTokens": 200000,
      "cacheCreationInputTokens": 500000,
      "cacheReadInputTokens": 300000
    }
  },
  "totalSessions": 200,
  "totalMessages": 13514,
  "longestSession": {
    "sessionId": "uuid",
    "messageCount": 150
  },
  "firstSessionDate": "2025-01-01",
  "hourCounts": [0, 0, 5, 10, 15, ...]  // 24-hour distribution
}
```

#### settings.json
```json
{
  "env": {
    "DISABLE_AUTOUPDATER": "1"
  },
  "model": "opus",
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "script.sh"}]}
    ],
    "PostToolUse": [...],
    "UserPromptSubmit": [...],
    "Notification": [...],
    "Stop": [...],
    "SubagentStop": [...],
    "PermissionRequest": [...]
  },
  "enabledPlugins": {
    "feature-dev": true,
    "code-review": true,
    "commit-commands": true
  }
}
```

#### settings.local.json
```json
{
  "permissions": {
    "allow": ["Bash(npm install:*)"],
    "deny": [],
    "ask": []
  }
}
```

---

## Part 3: Key Patterns & Relationships

### Entry Relationships

1. **parentUuid chains** - Entries form a tree structure representing conversation flow
2. **toolUseID/parentToolUseID** - Track tool execution lifecycle from invocation to result
3. **sessionId** - Groups all entries within a single session
4. **slug** - Identifies plan mode sessions with whimsical names
5. **agentId** - Identifies subagents spawned by Task tool
6. **message.id** - Groups streaming response fragments

### Data Flow Sequence

```
1. User prompt       → user entry
2. Claude thinks     → assistant entry (thinking block)
3. Claude responds   → assistant entry (text block)
4. Tool invoked      → assistant entry (tool_use block)
5. PreToolUse hook   → progress entry
6. Hook completes    → attachment entry (hook_success)
7. Tool executes     → (external execution)
8. Tool returns      → user entry (tool_result)
9. PostToolUse hook  → progress entry
10. File modified    → file-history-snapshot entry
11. Session ends     → summary entry
```

### Subagent (Task Tool) Logging

When Task tool spawns a subagent:
- Main session logs the Task invocation and final result
- Subagent gets its own log file: `subagents/agent-{id}.jsonl`
- Progress entries track `agent_progress` with `normalizedMessages`
- Subagent internal tool usage is logged in subagent file, not main session

### Plan Files ↔ Session Mapping

Plan files in `~/.claude/plans/` are linked to sessions via the `slug` field:

**How to find which session(s) use a plan file:**
```bash
# Find sessions using a specific plan slug
grep -l '"slug":"lazy-jumping-glacier"' ~/.claude/projects/*/*.jsonl
```

**How to find the plan file for a session:**
```bash
# Extract slug from a session log
grep '"slug"' ~/.claude/projects/{project}/{session-id}.jsonl | head -1 | jq -r '.slug'
```

**Relationship Details:**

| Log Entry Field | Plan File |
|-----------------|-----------|
| `"slug": "lazy-jumping-glacier"` | `~/.claude/plans/lazy-jumping-glacier.md` |
| Subagent with `agentId: "a8defb8"` | `~/.claude/plans/{slug}-agent-a8defb8.md` |

**Key Fields:**
- **`slug`** (in most entry types): The whimsical plan name identifier
- **`planFilePath`** (in `plan_mode` attachment): Full path to the plan file
- **`planExists`** (in `plan_mode` attachment): Whether the plan file exists

**Example `plan_mode` Attachment:**
```json
{
  "type": "attachment",
  "attachment": {
    "type": "plan_mode",
    "reminderType": "full",
    "isSubAgent": false,
    "planFilePath": "/Users/thein/.claude/plans/lazy-jumping-glacier.md",
    "planExists": true
  }
}
```

**Notes:**

- Multiple sessions can share the same `slug` (e.g., when continuing a plan across sessions)
- Subagents in plan mode get their own plan file with suffix: `{slug}-agent-{agentId}.md`
- The `slug` field appears on entries only after `EnterPlanMode` is called

---

## Part 4: Parsing Logs with jq

### Basic Queries

```bash
# Count entries by type
cat session.jsonl | jq -s 'group_by(.type) | map({type: .[0].type, count: length})'

# List all unique entry types
cat session.jsonl | jq -s '[.[].type] | unique'

# Get all user messages (text only)
cat session.jsonl | jq 'select(.type == "user") | .message.content' | head -20

# Get all assistant tool calls
cat session.jsonl | jq 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | {name, id}'
```

### Token Usage Analysis

```bash
# Sum total tokens by type
cat session.jsonl | jq -s '
  [.[] | select(.type == "assistant") | .message.usage | select(.)]
  | {
      input: (map(.input_tokens) | add),
      output: (map(.output_tokens) | add),
      cache_creation: (map(.cache_creation_input_tokens) | add),
      cache_read: (map(.cache_read_input_tokens) | add)
    }'

# Get token usage per assistant response
cat session.jsonl | jq 'select(.type == "assistant") | {id: .message.id, usage: .message.usage}'
```

### Tool Usage Analysis

```bash
# Count tool calls by tool name
cat session.jsonl | jq -s '
  [.[] | select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name]
  | group_by(.) | map({tool: .[0], count: length}) | sort_by(-.count)'

# List all Bash commands executed
cat session.jsonl | jq 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use" and .name == "Bash") | .input.command'

# Find tool errors
cat session.jsonl | jq 'select(.type == "user") | .message.content[]? | select(.type == "tool_result" and .is_error == true)'
```

### Session Timeline

```bash
# Get conversation flow (user prompts and assistant responses)
cat session.jsonl | jq 'select(.type == "user" or .type == "assistant") | {type, timestamp, content: (.message.content | if type == "string" then .[0:100] else .[0].text?[0:100] // .[0].name? end)}'

# Get session duration
cat session.jsonl | jq -s 'sort_by(.timestamp) | {start: .[0].timestamp, end: .[-1].timestamp}'

# List all timestamps with entry types
cat session.jsonl | jq '{timestamp, type, uuid}' | head -50
```

### Plan Mode Queries

```bash
# Find all plan mode sessions
cat session.jsonl | jq 'select(.slug) | {sessionId, slug, timestamp}' | head -5

# Get plan mode attachment details
cat session.jsonl | jq 'select(.type == "attachment" and .attachment.type == "plan_mode") | .attachment'
```

### Hook Analysis

```bash
# List all hook events
cat session.jsonl | jq 'select(.type == "progress" and .data.type == "hook_progress") | {hookEvent: .data.hookEvent, hookName: .data.hookName}'

# Find hook errors
cat session.jsonl | jq 'select(.type == "system" and .hookErrors | length > 0)'

# Get turn durations
cat session.jsonl | jq 'select(.type == "system" and .subtype == "turn_duration") | {durationMs, timestamp}'
```

### Extended Thinking

```bash
# Extract thinking blocks
cat session.jsonl | jq 'select(.type == "assistant") | .message.content[]? | select(.type == "thinking") | .thinking[0:500]'

# Check thinking metadata
cat session.jsonl | jq 'select(.type == "user" and .thinkingMetadata) | {timestamp, thinkingMetadata}'
```

### Cross-Session Analysis

```bash
# Analyze all sessions in a project
for f in ~/.claude/projects/-Users-*/*.jsonl; do
  echo "=== $f ==="
  cat "$f" | jq -s '{
    entries: length,
    types: ([.[].type] | unique),
    tools: ([.[] | select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name] | unique)
  }'
done

# Find sessions with specific tool usage
grep -l '"name":"WebSearch"' ~/.claude/projects/*/*.jsonl
```

### Building Entry Trees

```bash
# Trace parent-child relationships
cat session.jsonl | jq '{uuid, parentUuid, type}' | head -20

# Find root entries (no parent)
cat session.jsonl | jq 'select(.parentUuid == null) | {uuid, type, timestamp}'
```

---

## Part 5: Quick Reference

### Entry Types at a Glance

| Entry Type | Key Fields | When Created |
|------------|------------|--------------|
| `user` | message, thinkingMetadata, todos | User input or tool results |
| `assistant` | message, requestId | Claude responses |
| `progress` | data.type, toolUseID | Hook/agent execution |
| `attachment` | attachment.type | Hook results, reminders |
| `system` | subtype, hookCount | System events |
| `summary` | summary, leafUuid | Session end |
| `file-history-snapshot` | snapshot | File modifications |
| `queue-operation` | operation | Queue changes |

### Common Tool Names

- File: `Read`, `Write`, `Edit`, `Glob`, `Grep`, `LS`
- System: `Bash`, `Task`, `TaskOutput`, `KillShell`
- Web: `WebFetch`, `WebSearch`
- Planning: `TodoWrite`, `EnterPlanMode`, `ExitPlanMode`, `AskUserQuestion`
- Jupyter: `NotebookRead`, `NotebookEdit`
- Skills: `Skill`
- MCP: `mcp__{server}__{tool}` (e.g., `mcp__hugging-face__model_search`)

### Hook Events

| Event | When Triggered |
|-------|----------------|
| `SessionStart` | Session begins |
| `PreToolUse` | Before tool execution |
| `PostToolUse` | After tool execution |
| `UserPromptSubmit` | User sends message |
| `Stop` | Session ends |
| `SubagentStop` | Subagent completes |
| `Notification` | System notification |
| `PermissionRequest` | Permission prompt |
