import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mempalace_history_export.cli import (
    extract_claude_messages,
    extract_codex_messages,
    extract_opencode_messages,
    parse_sources,
    project_to_claude_dirname,
    render_transcript,
)


class ClaudeDirnameTests(unittest.TestCase):
    def test_project_path_maps_to_claude_projects_dirname(self) -> None:
        self.assertEqual(
            project_to_claude_dirname("/home/user/projects/sample-app"),
            "-home-user-projects-sample-app",
        )


class CodexExtractionTests(unittest.TestCase):
    def test_extracts_user_and_assistant_messages_and_drops_agent_prelude(self) -> None:
        payloads = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "# AGENTS.md instructions for /tmp/project\n\n"
                                "<INSTRUCTIONS>\nIgnore this block.\n</INSTRUCTIONS>\n"
                                "<environment_context>\nfoo\n</environment_context>\n\n"
                                "actual request"
                            ),
                        }
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "skip me"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "actual answer"}],
                },
            },
        ]

        self.assertEqual(
            extract_codex_messages(payloads),
            [
                ("User", "actual request"),
                ("Assistant", "actual answer"),
            ],
        )


class ClaudeExtractionTests(unittest.TestCase):
    def test_extracts_text_messages_and_skips_meta_and_tool_noise(self) -> None:
        payloads = [
            {
                "type": "user",
                "isMeta": True,
                "message": {"role": "user", "content": "skip this meta message"},
            },
            {
                "type": "user",
                "message": {"role": "user", "content": "real question"},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "skip"},
                        {"type": "text", "text": "real answer"},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}},
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "content": "skip result", "tool_use_id": "x"}
                    ],
                },
            },
        ]

        self.assertEqual(
            extract_claude_messages(payloads),
            [
                ("User", "real question"),
                ("Assistant", "real answer"),
            ],
        )


class TranscriptRenderingTests(unittest.TestCase):
    def test_render_transcript_separates_turns(self) -> None:
        self.assertEqual(
            render_transcript([("User", "hello"), ("Assistant", "hi")]),
            "User: hello\n\nAssistant: hi\n",
        )


class OpenCodeExtractionTests(unittest.TestCase):
    def test_extracts_text_parts_and_skips_reasoning_and_tool_noise(self) -> None:
        messages = [
            {
                "id": "msg-user",
                "data": '{"role":"user"}',
            },
            {
                "id": "msg-assistant",
                "data": '{"role":"assistant"}',
            },
        ]
        parts = [
            {
                "message_id": "msg-user",
                "time_created": 1,
                "data": '{"type":"text","text":"review this diff"}',
            },
            {
                "message_id": "msg-assistant",
                "time_created": 2,
                "data": '{"type":"step-start"}',
            },
            {
                "message_id": "msg-assistant",
                "time_created": 3,
                "data": '{"type":"reasoning","text":"internal"}',
            },
            {
                "message_id": "msg-assistant",
                "time_created": 4,
                "data": '{"type":"tool","tool":"bash"}',
            },
            {
                "message_id": "msg-assistant",
                "time_created": 5,
                "data": '{"type":"text","text":"looks safe"}',
            },
        ]

        self.assertEqual(
            extract_opencode_messages(messages, parts),
            [
                ("User", "review this diff"),
                ("Assistant", "looks safe"),
            ],
        )


class SourceParsingTests(unittest.TestCase):
    def test_accepts_opencode_source(self) -> None:
        self.assertEqual(parse_sources("codex,claude,opencode"), ["codex", "claude", "opencode"])


if __name__ == "__main__":
    unittest.main()
