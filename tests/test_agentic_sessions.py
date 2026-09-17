import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "agentic-sessions"
LOADER = importlib.machinery.SourceFileLoader("agentic_sessions", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
agentic_sessions = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = agentic_sessions
LOADER.exec_module(agentic_sessions)


class SearchTests(unittest.TestCase):
    def make_codex_config(self, root: Path) -> agentic_sessions.Config:
        agent_home = root / "agent"
        sessions_root = agent_home / "sessions"
        state_root = root / "state"
        sessions_root.mkdir(parents=True)
        state_root.mkdir()
        return agentic_sessions.Config(
            provider="codex",
            agent_home=agent_home,
            sessions_root=sessions_root,
            state_root=state_root,
            names_file=state_root / "session-names.json",
            trash_root=state_root / "trash",
        )

    def write_codex_session(self, config: agentic_sessions.Config, session_id: str, prompt: str) -> Path:
        path = config.sessions_root / f"rollout-{session_id}.jsonl"
        records = [
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": "2026-07-15T00:00:00Z",
                    "cwd": "/tmp/search-fixture",
                    "source": "cli",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"text": prompt}],
                },
            },
        ]
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        return path

    def test_session_index_search_falls_back_to_prompt_text(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            self.write_codex_session(config, session_id, "Find the sidebar-only search needle")

            sessions = agentic_sessions.load_session_index(config, query="needle")

        self.assertEqual([session.id for session in sessions], [session_id])
        self.assertEqual(sessions[0].first_prompt, "Find the sidebar-only search needle")

    def test_sidebar_loader_search_falls_back_to_prompt_text(self) -> None:
        session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            self.write_codex_session(config, session_id, "Use prompt text as the filtered title")

            loader = agentic_sessions.SidebarIndexLoader([config], query="filtered title")
            sessions = loader.load_more(0)

        self.assertEqual([session.id for session in sessions], [session_id])
        self.assertEqual(sessions[0].first_prompt, "Use prompt text as the filtered title")


class QgenieStatusTests(unittest.TestCase):
    SAMPLE = (
        "\x1b[1mCost Cap Usage\x1b[0m\n"
        "  Daily                       █░░░  4.2%  \x1b[2m($10.39 / $250.00)  resets in 6 hours\x1b[0m\n"
        "  Monthly                     ████   80.8%  ($1010.40 / $1250.00)  resets in 14 days\n"
    )

    def test_limits_are_compact_and_ansi_free(self) -> None:
        self.assertEqual(
            agentic_sessions.format_qgenie_limits(self.SAMPLE),
            "Qgenie D 4.2% $10.39/$250 · M 80.8% $1010.40/$1250",
        )

    def test_limits_status_uses_fresh_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "limits.txt"
            completed = SimpleNamespace(returncode=0, stdout=self.SAMPLE, stderr="")
            with mock.patch.object(agentic_sessions.subprocess, "run", return_value=completed) as run:
                first = agentic_sessions.qgenie_limits_status(
                    "/usr/bin/qgenie", cache_path=cache, cache_ttl=60
                )
                second = agentic_sessions.qgenie_limits_status(
                    "/usr/bin/qgenie", cache_path=cache, cache_ttl=60
                )

        self.assertEqual(first, second)
        run.assert_called_once()

    def test_tmux_hint_includes_qgenie_command_when_configured(self) -> None:
        with mock.patch.object(agentic_sessions, "tmux_prefix_key", return_value="`"):
            hint = agentic_sessions.tmux_status_hint(
                ["codex"], "/usr/bin/qgenie", "/opt/agentic-sessions"
            )
        self.assertIn("qgenie-status", hint)
        self.assertIn("--cache-ttl 60", hint)
        self.assertIn("`+? keys", hint)
        self.assertIn("`+b sidebar", hint)
        self.assertIn("`+←/→ panes", hint)
        self.assertIn("mouse focus", hint)

    def test_tmux_qgenie_segment_doubles_percent_for_strftime(self) -> None:
        segment = agentic_sessions.qgenie_status_segment(
            "/usr/bin/qgenie", "/opt/agentic-sessions"
        )
        self.assertIn("s/\\045/\\045\\045/g", segment)
        self.assertNotIn("s/%/pct/g", segment)


class TmuxProbeTests(unittest.TestCase):
    def test_current_tmux_pane_targets_tmux_pane_environment(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="%7\n", stderr="")
        with mock.patch.dict(
            agentic_sessions.os.environ,
            {"TMUX": "/tmp/tmux/default,123,0", "TMUX_PANE": "%7"},
            clear=False,
        ), mock.patch.object(agentic_sessions.subprocess, "run", return_value=completed) as run:
            pane = agentic_sessions.current_tmux_pane()

        self.assertEqual(pane, "%7")
        self.assertEqual(
            run.call_args.args[0],
            ["tmux", "display-message", "-p", "-t", "%7", "#{pane_id}"],
        )

    def test_current_tmux_pane_rejects_stale_tmux_environment(self) -> None:
        failed = SimpleNamespace(returncode=1, stdout="", stderr="no server")
        with mock.patch.dict(
            agentic_sessions.os.environ,
            {"TMUX": "/tmp/tmux/dead,123,0", "TMUX_PANE": "%11"},
            clear=False,
        ), mock.patch.object(
            agentic_sessions.subprocess, "run", return_value=failed
        ) as run:
            pane = agentic_sessions.current_tmux_pane()

        self.assertEqual(pane, "")
        self.assertEqual(run.call_count, 2)

    def test_tmux_server_available_checks_the_selected_socket(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="agentic: 1 windows", stderr="")
        with mock.patch.dict(
            agentic_sessions.os.environ,
            {"TMUX": "/tmp/tmux/default,123,0"},
            clear=False,
        ), mock.patch.object(agentic_sessions.subprocess, "run", return_value=completed) as run:
            available = agentic_sessions.tmux_server_available()

        self.assertTrue(available)
        self.assertEqual(run.call_args.args[0], ["tmux", "list-sessions"])


class ResumeCommandTests(unittest.TestCase):
    def make_session(self, session_id: str) -> agentic_sessions.Session:
        return agentic_sessions.Session(
            provider="codex",
            id=session_id,
            path=Path("/tmp/session.jsonl"),
            timestamp="",
            modified=0,
            cwd="",
            source="",
            model_provider="",
            cli_version="",
            first_prompt="",
            last_prompt="",
        )

    def make_config(self, root: Path) -> agentic_sessions.Config:
        return agentic_sessions.Config(
            provider="codex",
            agent_home=root,
            sessions_root=root / "sessions",
            state_root=root / "state",
            names_file=root / "state" / "names.json",
            trash_root=root / "state" / "trash",
        )

    def test_existing_process_in_tmux_pane_is_focused(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        info = agentic_sessions.ProcessInfo(123, 1, 123, "/dev/pts/7", "S", ("codex", "resume", session_id))
        pane = agentic_sessions.TmuxPane("%7", 99, "/dev/pts/7", "agentic", "0", True)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            agentic_sessions, "lock_holders", return_value=[info]
        ), mock.patch.object(agentic_sessions, "tmux_panes", return_value=[pane]), mock.patch.object(
            agentic_sessions, "focus_tmux_pane"
        ) as focus:
            handled, message = agentic_sessions.recover_existing_session(
                self.make_session(session_id), self.make_config(Path(tmp))
            )

        self.assertTrue(handled)
        self.assertIn("focused existing", message)
        focus.assert_called_once_with(pane)

    def test_stopped_process_in_tmux_pane_is_foregrounded(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        info = agentic_sessions.ProcessInfo(123, 1, 123, "/dev/pts/7", "T", ("codex", "resume", session_id))
        pane = agentic_sessions.TmuxPane("%7", 99, "/dev/pts/7", "agentic", "0", False)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            agentic_sessions, "lock_holders", return_value=[info]
        ), mock.patch.object(agentic_sessions, "tmux_panes", return_value=[pane]), mock.patch.object(
            agentic_sessions, "foreground_stopped_process"
        ) as foreground, mock.patch.object(agentic_sessions, "focus_tmux_pane"):
            handled, message = agentic_sessions.recover_existing_session(
                self.make_session(session_id), self.make_config(Path(tmp))
            )

        self.assertTrue(handled)
        self.assertIn("foregrounded existing", message)
        foreground.assert_called_once_with(pane)

    def test_unreachable_owner_is_cleared_before_new_resume(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        info = agentic_sessions.ProcessInfo(123, 1, 123, "/dev/pts/7", "S", ("codex", "resume", session_id))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            agentic_sessions, "lock_holders", return_value=[info]
        ), mock.patch.object(agentic_sessions, "tmux_panes", return_value=[]), mock.patch.object(
            agentic_sessions, "session_processes", return_value=[info]
        ), mock.patch.object(agentic_sessions, "stop_existing_session_processes", return_value=True) as stop:
            handled, message = agentic_sessions.recover_existing_session(
                self.make_session(session_id), self.make_config(Path(tmp))
            )

        self.assertFalse(handled)
        self.assertIn("cleared unreachable", message)
        stop.assert_called_once_with([info])

    def test_codex_args_are_inserted_before_resume_for_qgenie(self) -> None:
        commands = agentic_sessions.resume_commands(
            "codex",
            "/usr2/slingapp/.local/bin/qgenie",
            "01a03846-bb7b-7e02-a2ed-4fb31505afd3",
            ["-s", "danger-full-access"],
        )

        self.assertEqual(
            commands[0],
            [
                "/usr2/slingapp/.local/bin/qgenie",
                "codex",
                "-s",
                "danger-full-access",
                "resume",
                "01a03846-bb7b-7e02-a2ed-4fb31505afd3",
            ],
        )
        self.assertEqual(
            commands[1],
            ["/usr2/slingapp/.local/bin/qgenie", "resume", "01a03846-bb7b-7e02-a2ed-4fb31505afd3"],
        )

    def test_codex_args_are_inserted_before_resume_for_codex(self) -> None:
        commands = agentic_sessions.resume_commands(
            "codex",
            "/usr/bin/codex",
            "01a03846-bb7b-7e02-a2ed-4fb31505afd3",
            ["-s", "danger-full-access"],
        )

        self.assertEqual(
            commands,
            [["/usr/bin/codex", "-s", "danger-full-access", "resume", "01a03846-bb7b-7e02-a2ed-4fb31505afd3"]],
        )

    def test_codex_args_are_parsed_like_shell_words(self) -> None:
        args = SimpleNamespace(codex_args="-s danger-full-access -c 'model=\"gpt-5\"'")

        self.assertEqual(
            agentic_sessions.codex_args_for(args),
            ["-s", "danger-full-access", "-c", 'model="gpt-5"'],
        )

    def test_resume_shell_command_quotes_codex_args(self) -> None:
        session = agentic_sessions.Session(
            provider="codex",
            id="01a03846-bb7b-7e02-a2ed-4fb31505afd3",
            path=Path("/tmp/session.jsonl"),
            timestamp="",
            modified=0,
            cwd="/tmp/work tree",
            source="",
            model_provider="",
            cli_version="",
            first_prompt="",
            last_prompt="",
        )

        command = agentic_sessions.resume_shell_command(
            session,
            "/usr2/slingapp/.local/bin/qgenie",
            ["-s", "danger-full-access"],
        )

        self.assertIn(
            "'/usr2/slingapp/.local/bin/qgenie' 'codex' '-s' 'danger-full-access' 'resume'",
            command,
        )
        self.assertTrue(command.startswith("cd '/tmp/work tree' && "))


if __name__ == "__main__":
    unittest.main()
