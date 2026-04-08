from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from pathlib import Path


DEFAULT_BASE_DIR = Path.home() / ".local/share/mempalace-history-export"
DEFAULT_EXPORTS_DIR = DEFAULT_BASE_DIR / "exports"
CODEX_SESSIONS_DIR = Path.home() / ".codex/sessions"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude/projects"
OPENCODE_DB_PATH = Path.home() / ".local/share/opencode/opencode.db"


def project_to_claude_dirname(project_path: str) -> str:
    resolved = str(Path(project_path).expanduser().resolve())
    return re.sub(r"[^A-Za-z0-9]+", "-", resolved)


def normalize_project_path(project_path: str | None) -> Path:
    return Path(project_path or ".").expanduser().resolve()


def path_is_within(child: str | None, parent: Path) -> bool:
    if not child:
        return False
    try:
        Path(child).expanduser().resolve().relative_to(parent)
        return True
    except ValueError:
        return False


def extract_text_blocks(content: object, allowed_types: set[str]) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in allowed_types:
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()


def clean_codex_user_text(text: str) -> str:
    cleaned = text.strip()
    if "# AGENTS.md instructions for " in cleaned:
        env_end = cleaned.rfind("</environment_context>")
        if env_end != -1:
            cleaned = cleaned[env_end + len("</environment_context>") :].strip()
        else:
            instructions_end = cleaned.rfind("</INSTRUCTIONS>")
            if instructions_end != -1:
                cleaned = cleaned[instructions_end + len("</INSTRUCTIONS>") :].strip()
    return cleaned


def extract_codex_messages(entries: list[dict]) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload", {})
        if payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue
        if role == "user":
            text = clean_codex_user_text(extract_text_blocks(payload.get("content"), {"input_text"}))
            speaker = "User"
        else:
            text = extract_text_blocks(payload.get("content"), {"output_text"})
            speaker = "Assistant"
        if text:
            messages.append((speaker, text))
    return messages


def extract_claude_message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()


def should_skip_claude_user_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("<command-name>/clear</command-name>"):
        return True
    if stripped.startswith("<command-name>/exit</command-name>"):
        return True
    if stripped.startswith("<command-name>/status</command-name>"):
        return True
    if stripped.startswith("<local-command-caveat>"):
        return True
    return False


def extract_claude_messages(entries: list[dict]) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    for entry in entries:
        entry_type = entry.get("type")
        if entry_type not in {"user", "assistant"}:
            continue
        if entry.get("isMeta"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = extract_claude_message_text(message)
        if role == "user":
            if should_skip_claude_user_text(text):
                continue
            speaker = "User"
        else:
            if not text:
                continue
            speaker = "Assistant"
        messages.append((speaker, text))
    return messages


def extract_opencode_messages(messages: list[dict], parts: list[dict]) -> list[tuple[str, str]]:
    role_by_message_id: dict[str, str] = {}
    for message in messages:
        message_id = message.get("id")
        raw = message.get("data")
        if not isinstance(message_id, str) or not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        role = data.get("role")
        if role in {"user", "assistant"}:
            role_by_message_id[message_id] = "User" if role == "user" else "Assistant"

    text_parts_by_message_id: dict[str, list[tuple[int, str]]] = {}
    for part in parts:
        message_id = part.get("message_id")
        raw = part.get("data")
        time_created = part.get("time_created", 0)
        if not isinstance(message_id, str) or not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("type") != "text":
            continue
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        text_parts_by_message_id.setdefault(message_id, []).append((int(time_created), text.strip()))

    extracted: list[tuple[str, str, int]] = []
    for message in messages:
        message_id = message.get("id")
        if not isinstance(message_id, str):
            continue
        speaker = role_by_message_id.get(message_id)
        text_parts = text_parts_by_message_id.get(message_id)
        if not speaker or not text_parts:
            continue
        ordered_parts = [text for _, text in sorted(text_parts, key=lambda item: item[0])]
        created = int(message.get("time_created", 0))
        extracted.append((speaker, "\n\n".join(ordered_parts), created))

    return [(speaker, text) for speaker, text, _ in sorted(extracted, key=lambda item: item[2])]


def render_transcript(messages: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"{speaker}: {text}" for speaker, text in messages) + "\n"


def load_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                entries.append(obj)
    return entries


def codex_session_cwd(entries: list[dict]) -> str | None:
    for entry in entries:
        if entry.get("type") != "session_meta":
            continue
        payload = entry.get("payload", {})
        cwd = payload.get("cwd")
        if isinstance(cwd, str):
            return cwd
    return None


def find_codex_sessions(project_path: Path) -> list[Path]:
    matches: list[Path] = []
    if not CODEX_SESSIONS_DIR.exists():
        return matches
    for path in sorted(CODEX_SESSIONS_DIR.rglob("*.jsonl")):
        entries = load_jsonl(path)
        if path_is_within(codex_session_cwd(entries), project_path):
            matches.append(path)
    return matches


def find_claude_sessions(project_path: Path) -> list[Path]:
    project_dir = CLAUDE_PROJECTS_DIR / project_to_claude_dirname(str(project_path))
    if not project_dir.exists():
        return []
    return sorted(path for path in project_dir.glob("*.jsonl") if path.is_file())


def open_opencode_db() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{OPENCODE_DB_PATH}?mode=ro&immutable=1", uri=True)


def find_opencode_sessions(project_path: Path) -> list[dict]:
    if not OPENCODE_DB_PATH.exists():
        return []
    with open_opencode_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            select id, directory, title, time_created
            from session
            order by time_created
            """
        ).fetchall()
    return [dict(row) for row in rows if path_is_within(row["directory"], project_path)]


def load_opencode_session(session_id: str) -> tuple[list[dict], list[dict]]:
    with open_opencode_db() as conn:
        conn.row_factory = sqlite3.Row
        messages = conn.execute(
            """
            select id, time_created, data
            from message
            where session_id = ?
            order by time_created
            """,
            (session_id,),
        ).fetchall()
        parts = conn.execute(
            """
            select message_id, time_created, data
            from part
            where session_id = ?
            order by time_created
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in messages], [dict(row) for row in parts]


def export_transcripts(
    project_path: Path,
    wing: str,
    sources: list[str],
    output_dir: Path,
    dry_run: bool,
) -> tuple[int, int]:
    output_dir = output_dir.expanduser().resolve()
    exported = 0
    seen_messages = 0

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    if "codex" in sources:
        for session_path in find_codex_sessions(project_path):
            entries = load_jsonl(session_path)
            messages = extract_codex_messages(entries)
            if len(messages) < 2:
                continue
            target = output_dir / f"codex-{session_path.stem}.txt"
            print(f"[codex] {session_path} -> {target.name} ({len(messages)} turns)")
            if not dry_run:
                target.write_text(render_transcript(messages), encoding="utf-8")
            exported += 1
            seen_messages += len(messages)

    if "claude" in sources:
        for session_path in find_claude_sessions(project_path):
            entries = load_jsonl(session_path)
            messages = extract_claude_messages(entries)
            if len(messages) < 2:
                continue
            target = output_dir / f"claude-{session_path.stem}.txt"
            print(f"[claude] {session_path} -> {target.name} ({len(messages)} turns)")
            if not dry_run:
                target.write_text(render_transcript(messages), encoding="utf-8")
            exported += 1
            seen_messages += len(messages)

    if "opencode" in sources:
        for session in find_opencode_sessions(project_path):
            messages_rows, parts_rows = load_opencode_session(session["id"])
            messages = extract_opencode_messages(messages_rows, parts_rows)
            if len(messages) < 2:
                continue
            target = output_dir / f"opencode-{session['id']}.txt"
            print(f"[opencode] {session['directory']} :: {session['id']} -> {target.name} ({len(messages)} turns)")
            if not dry_run:
                target.write_text(render_transcript(messages), encoding="utf-8")
            exported += 1
            seen_messages += len(messages)

    print(f"exported_sessions={exported} total_turns={seen_messages} wing={wing}")
    return exported, seen_messages


def parse_sources(raw: str) -> list[str]:
    allowed = {"codex", "claude", "opencode"}
    sources = [item.strip().lower() for item in raw.split(",") if item.strip()]
    invalid = [item for item in sources if item not in allowed]
    if invalid:
        raise SystemExit(f"unsupported sources: {', '.join(invalid)}")
    if not sources:
        raise SystemExit("at least one source is required")
    return sources


def run_mempalace_mine(output_dir: Path, wing: str, dry_run: bool) -> int:
    cmd = [
        "mempalace",
        "mine",
        str(output_dir),
        "--mode",
        "convos",
        "--wing",
        wing,
    ]
    if dry_run:
        cmd.append("--dry-run")
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export Codex and Claude project sessions into MemPalace-friendly transcripts."
    )
    parser.add_argument("--project-path", help="Project path to match. Defaults to the current directory.")
    parser.add_argument("--wing", help="MemPalace wing name. Defaults to the project directory name.")
    parser.add_argument(
        "--sources",
        default="codex,claude,opencode",
        help="Comma-separated sources: codex, claude, opencode",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for exported transcripts. Defaults to ~/.local/share/mempalace-history-export/exports/<wing>",
    )
    parser.add_argument("--mine", action="store_true", help="Run mempalace mine after exporting.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without writing files.")
    args = parser.parse_args(argv)

    project_path = normalize_project_path(args.project_path)
    wing = args.wing or project_path.name
    sources = parse_sources(args.sources)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else DEFAULT_EXPORTS_DIR / wing

    print(f"project_path={project_path}")
    print(f"sources={','.join(sources)}")
    print(f"output_dir={output_dir}")
    print(f"dry_run={args.dry_run}")

    exported, _ = export_transcripts(project_path, wing, sources, output_dir, args.dry_run)
    if args.mine and exported > 0:
        return run_mempalace_mine(output_dir, wing, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
