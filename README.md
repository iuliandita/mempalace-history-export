# mempalace-history-export

Export local Codex, Claude, and OpenCode project sessions into plain text
transcripts that `mempalace` can mine reliably.

`mempalace` can already ingest some chat exports, but Codex session logs are not
supported directly, Claude project logs are event-heavy, and OpenCode stores its
session history in SQLite rather than plain transcripts. This tool normalizes all
three into clean `User:` / `Assistant:` transcripts, scoped to the current repo
by default.

## What It Does

- Detects the current project from `pwd` by default
- Finds matching Codex sessions from `~/.codex/sessions`
- Finds matching Claude sessions from `~/.claude/projects`
- Finds matching OpenCode sessions from `~/.local/share/opencode/opencode.db`
- Writes stable transcript files for rerunnable imports
- Optionally runs `mempalace mine ... --mode convos`

## Install

```bash
pip install .
```

## Usage

From inside a repo, using the current working directory by default:

```bash
mempalace-history-export --dry-run
mempalace-history-export --mine
```

Real example for the current repo:

```bash
cd ~/projects/sample-app
mempalace-history-export --dry-run
```

Explicit project path:

```bash
mempalace-history-export --project-path ~/code/my-app --wing my-app --mine
```

Codex only:

```bash
mempalace-history-export --sources codex --dry-run
```

OpenCode only:

```bash
mempalace-history-export --sources opencode --dry-run
```

Choose multiple sources explicitly:

```bash
mempalace-history-export --sources codex,claude,opencode --dry-run
```

## Notes

- Default export path: `~/.local/share/mempalace-history-export/exports/<wing>`
- Claude subagent sidechains are skipped by default; this keeps exports focused
  on the main project conversations
- OpenCode exports read the local SQLite store in read-only immutable mode
- Sessions are matched to the current repo by comparing the stored project path
  against `pwd` unless `--project-path` is set
- The tool uses only the Python standard library
