# google-tasks-mcp

MCP server that lets Claude read, create and complete Google Tasks.

## Tools

| Tool | Purpose |
|---|---|
| `tasks_context` | Open tasks from all lists, grouped: overdue, due soon, no due date, later, created by Claude. Meant to be loaded at the start of a conversation. |
| `list_task_lists` | Task lists. |
| `list_tasks` | Tasks in one list, filtered by text, due date, completion or creator. |
| `create_task` | New task: title, notes, due date (`YYYY-MM-DD`), list, parent task. |
| `update_task` | Change title, notes or due date. |
| `complete_task`, `reopen_task` | Change status. |

Tasks created through the server get `[created-by: claude]` appended to their notes. Claude completes such tasks on its own when the work is done; any other task is completed only with `user_requested=true`, which the server enforces.

## Requirements

- Python 3.10+
- A Google Cloud project with the **Google Tasks API** enabled and an OAuth client of type **Desktop app** (download its JSON). Add your account as a test user on the OAuth consent screen. While the app is in *Testing*, the token expires after 7 days; publish the app to avoid that.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/google-tasks-mcp auth --client-secret client_secret.json
```

`auth` opens a browser for Google sign-in and stores a Tasks-only token in `~/.config/google-tasks-mcp/token.json` (mode 0600; override the directory with `GOOGLE_TASKS_MCP_HOME`). The client JSON is deleted afterwards unless `--keep-client-secret` is passed.

Other commands: `status` checks the token, `logout` revokes and deletes it.

Register with Claude Code:

```bash
claude mcp add google-tasks --scope user -- /path/to/.venv/bin/google-tasks-mcp
```

or in Claude Desktop's `claude_desktop_config.json`:

```json
{ "mcpServers": { "google-tasks": { "command": "/path/to/.venv/bin/google-tasks-mcp" } } }
```

## Tests

```bash
.venv/bin/pip install -e '.[test]' && .venv/bin/pytest
```
