import importlib.machinery
import importlib.util
import json
import os
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
        state_root.mkdir(parents=True)
        return agentic_sessions.Config(
            provider="codex",
            agent_home=agent_home,
            sessions_root=sessions_root,
            state_root=state_root,
            names_file=state_root / "session-names.json",
            trash_root=state_root / "trash",
        )

    def write_codex_session(
        self, config: agentic_sessions.Config, session_id: str, prompt: str, extra_records: list | None = None
    ) -> Path:
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
        if extra_records:
            records.extend(extra_records)
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

    def test_session_index_search_scans_deep_content(self) -> None:
        session_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            self.write_codex_session(
                config,
                session_id,
                "Ordinary first prompt",
                [
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"text": "The hidden implementation detail is frobnicate"}],
                        },
                    }
                ],
            )

            sessions = agentic_sessions.load_session_index(config, query="frobnicate")

        self.assertEqual([session.id for session in sessions], [session_id])
        self.assertIn("frobnicate", sessions[0].search_snippet)

    def test_sidebar_loader_search_scans_deep_content(self) -> None:
        session_id = "cccccccc-dddd-eeee-ffff-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            self.write_codex_session(
                config,
                session_id,
                "Visible prompt text",
                [
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"text": "Only the transcript body mentions quasar-token"}],
                        },
                    }
                ],
            )

            loader = agentic_sessions.SidebarIndexLoader([config], query="quasar-token")
            sessions = loader.load_more(0)

        self.assertEqual([session.id for session in sessions], [session_id])
        self.assertIn("quasar-token", sessions[0].search_snippet)

    def test_session_search_ranks_title_match_before_newer_content_match(self) -> None:
        title_id = "dddddddd-eeee-ffff-0000-111111111111"
        content_id = "eeeeeeee-ffff-0000-1111-222222222222"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            title_path = self.write_codex_session(config, title_id, "Ordinary prompt")
            content_path = self.write_codex_session(
                config,
                content_id,
                "Ordinary prompt",
                [
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"text": "The transcript mentions rankneedle only here"}],
                        },
                    }
                ],
            )
            agentic_sessions.atomic_write_json(
                config.names_file,
                {title_id: {"title": "rankneedle title", "provider": "codex"}},
            )
            os.utime(title_path, (1000, 1000))
            os.utime(content_path, (2000, 2000))

            sessions = agentic_sessions.load_session_index(config, query="rankneedle", limit=1)

        self.assertEqual([session.id for session in sessions], [title_id])

    def test_codex_resume_id_uses_rollout_filename_when_metadata_differs(self) -> None:
        display_id = "ffffffff-0000-1111-2222-333333333333"
        resume_id = "00000000-1111-2222-3333-444444444444"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            path = config.sessions_root / f"rollout-2026-09-15T00-00-00-{resume_id}.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in [
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": resume_id,
                                "session_id": display_id,
                                "source": {"subagent": {}},
                            },
                        },
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": display_id,
                                "timestamp": "2026-09-15T00:00:00Z",
                                "cwd": "/tmp/search-fixture",
                                "source": "cli",
                            },
                        },
                    ]
                )
                + "\n"
            )

            session = agentic_sessions.parse_codex_session(path, {})

        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.id, display_id)
        self.assertEqual(session.resumable_id, resume_id)

    def test_id_selector_can_match_metadata_id_not_in_filename(self) -> None:
        display_id = "ffffffff-0000-1111-2222-333333333333"
        resume_id = "00000000-1111-2222-3333-444444444444"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            path = config.sessions_root / f"rollout-2026-09-15T00-00-00-{resume_id}.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in [
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": resume_id,
                                "session_id": display_id,
                                "source": {"subagent": {}},
                            },
                        },
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": display_id,
                                "timestamp": "2026-09-15T00:00:00Z",
                                "cwd": "/tmp/search-fixture",
                                "source": "cli",
                            },
                        },
                    ]
                )
                + "\n"
            )

            session = agentic_sessions.resolve_session_selector_any(
                [config], display_id[:8], include_generated=True
            )

        self.assertEqual(session.id, display_id)
        self.assertEqual(session.resumable_id, resume_id)

    def test_session_files_follows_symlinked_session_directories(self) -> None:
        session_id = "22222222-3333-4444-5555-666666666666"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_codex_config(root)
            real_shard = root / "real-sessions" / "2026" / "09" / "21"
            real_shard.mkdir(parents=True)
            linked_year = config.sessions_root / "2026"
            linked_year.symlink_to(real_shard.parent.parent, target_is_directory=True)
            path = real_shard / f"rollout-{session_id}.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in [
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": session_id,
                                "timestamp": "2026-09-21T00:00:00Z",
                                "cwd": "/tmp/symlink-fixture",
                                "source": "cli",
                            },
                        }
                    ]
                )
                + "\n"
            )

            sessions = agentic_sessions.load_session_index(config, include_generated=True)

        self.assertEqual([session.id for session in sessions], [session_id])

    def test_session_files_avoids_symlink_loops(self) -> None:
        session_id = "33333333-4444-5555-6666-777777777777"
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_codex_config(Path(tmp))
            self.write_codex_session(config, session_id, "Loop-safe scanner")
            loop = config.sessions_root / "loop"
            loop.symlink_to(config.sessions_root, target_is_directory=True)

            files = agentic_sessions.session_files(config)

        self.assertEqual(len(files), 1)
        self.assertEqual(agentic_sessions.session_id_from_path(files[0]), session_id)

    def test_default_codex_home_prefers_workspace_relocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale_home = root / ".codex"
            relocated_home = root / "workspace" / ".codex"
            (stale_home / "sessions").mkdir(parents=True)
            (relocated_home / "sessions").mkdir(parents=True)

            with mock.patch.dict(
                agentic_sessions.os.environ,
                {"HOME": str(root)},
                clear=True,
            ):
                agentic_sessions.home_path_aliases.cache_clear()
                try:
                    home = agentic_sessions.default_agent_home("codex")
                finally:
                    agentic_sessions.home_path_aliases.cache_clear()

        self.assertEqual(home, relocated_home.resolve())

    def test_build_configs_includes_workspace_and_legacy_codex_homes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_home = root / ".codex"
            relocated_home = root / "workspace" / ".codex"
            (legacy_home / "sessions").mkdir(parents=True)
            (relocated_home / "sessions").mkdir(parents=True)

            with mock.patch.dict(
                agentic_sessions.os.environ,
                {"HOME": str(root)},
                clear=True,
            ):
                configs = agentic_sessions.build_configs(SimpleNamespace(provider="codex"))

        self.assertEqual(
            [config.sessions_root for config in configs],
            [relocated_home.resolve() / "sessions", legacy_home.resolve() / "sessions"],
        )

    def test_codex_home_env_does_not_hide_default_codex_homes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_home = root / ".config" / "qgenie-cli" / "agent"
            legacy_home = root / ".codex"
            relocated_home = root / "workspace" / ".codex"
            env_home.mkdir(parents=True)
            (legacy_home / "sessions").mkdir(parents=True)
            (relocated_home / "sessions").mkdir(parents=True)

            with mock.patch.dict(
                agentic_sessions.os.environ,
                {"HOME": str(root), "CODEX_HOME": str(env_home)},
                clear=True,
            ):
                configs = agentic_sessions.build_configs(SimpleNamespace(provider="codex"))

        self.assertEqual(
            [config.sessions_root for config in configs],
            [relocated_home.resolve() / "sessions", legacy_home.resolve() / "sessions"],
        )

    def test_session_index_from_configs_loads_workspace_and_legacy_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_config = self.make_codex_config(root / "legacy")
            relocated_config = self.make_codex_config(root / "relocated")
            legacy_id = "44444444-5555-6666-7777-888888888888"
            relocated_id = "55555555-6666-7777-8888-999999999999"
            self.write_codex_session(legacy_config, legacy_id, "Legacy session")
            self.write_codex_session(relocated_config, relocated_id, "Relocated session")

            sessions = agentic_sessions.load_session_index_from_configs(
                [relocated_config, legacy_config], include_generated=True
            )

        self.assertEqual({session.id for session in sessions}, {legacy_id, relocated_id})

    def test_id_selector_dedupes_same_session_across_codex_homes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_config = self.make_codex_config(root / "legacy")
            relocated_config = self.make_codex_config(root / "relocated")
            session_id = "66666666-7777-8888-9999-aaaaaaaaaaaa"
            self.write_codex_session(legacy_config, session_id, "Legacy duplicate")
            self.write_codex_session(relocated_config, session_id, "Relocated duplicate")

            session = agentic_sessions.resolve_session_selector_any(
                [relocated_config, legacy_config], session_id[:8], include_generated=True
            )

        self.assertEqual(session.id, session_id)

    def test_sidebar_search_includes_generated_sessions(self) -> None:
        args = SimpleNamespace(all=False)

        self.assertFalse(agentic_sessions.include_generated_for_sidebar(args, ""))
        self.assertTrue(agentic_sessions.include_generated_for_sidebar(args, "KVM_MPXY"))

    def test_sidebar_card_title_falls_back_to_prompt_title(self) -> None:
        session = agentic_sessions.Session(
            provider="codex",
            id="01a0c251-7672-7be2-a368-7ffb52c26058",
            path=Path("/tmp/session.jsonl"),
            timestamp="",
            modified=0,
            cwd="",
            source="",
            model_provider="",
            cli_version="",
            first_prompt="KVM_MPXY",
            last_prompt="KVM_MPXY",
        )

        title = agentic_sessions.sidebar_card_title(session, 56, selected=False)

        self.assertIn("KVM_MPXY", title)

    def test_sidebar_context_prefers_search_snippet(self) -> None:
        session = agentic_sessions.Session(
            provider="codex",
            id="01a0c251-7672-7be2-a368-7ffb52c26058",
            path=Path("/tmp/session.jsonl"),
            timestamp="",
            modified=0,
            cwd="",
            source="",
            model_provider="",
            cli_version="",
            first_prompt="Initial task without the matching token",
            last_prompt="Initial task without the matching token",
            search_snippet="Later user message mentions KVM_MPXY explicitly",
        )

        lines = agentic_sessions.prompt_context_lines(session, 56)

        self.assertIn("KVM_MPXY", " ".join(lines))


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

    def test_sidebar_shell_command_can_include_all_sessions(self) -> None:
        command = agentic_sessions.sidebar_shell_command(
            "/opt/agentic-sessions/bin/agentic-sessions",
            "%2",
            "/usr/bin/codex",
            "",
            "/usr/bin/claude",
            "/usr/bin/python3",
            "codex",
            None,
            include_all=True,
        )

        self.assertIn(" sidebar --target-pane ", command)
        self.assertIn(" --all ", command)


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

    def test_tmux_panes_scans_recovered_socket_candidates(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="%7\t99\t/dev/pts/7\tagentic\t0\t1\n", stderr="")
        with mock.patch.object(
            agentic_sessions, "tmux_socket_candidates", return_value=["/tmp/tmux-1000/server-99.sock"]
        ), mock.patch.object(agentic_sessions.subprocess, "run", return_value=completed) as run:
            panes = agentic_sessions.tmux_panes()

        self.assertEqual(len(panes), 1)
        self.assertEqual(panes[0].socket, "/tmp/tmux-1000/server-99.sock")
        self.assertEqual(run.call_args.args[0][:3], ["tmux", "-S", "/tmp/tmux-1000/server-99.sock"])

    def test_attach_tmux_session_to_pane_sends_attach_command(self) -> None:
        pane = agentic_sessions.TmuxPane(
            "%7", 99, "/dev/pts/7", "agentic session", "0", True, "/tmp/tmux-1000/server-99.sock"
        )
        with mock.patch.object(agentic_sessions.time, "sleep"), mock.patch.object(
            agentic_sessions.subprocess, "run"
        ) as run:
            agentic_sessions.attach_tmux_session_to_pane("%2", pane, suspend_running=True)

        sent_commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(sent_commands[0], ["tmux", "send-keys", "-t", "%2", "C-z"])
        self.assertIn("tmux -S '/tmp/tmux-1000/server-99.sock' attach -t 'agentic session'", sent_commands[1])
        self.assertEqual(sent_commands[-1], ["tmux", "select-pane", "-t", "%2"])


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

    def test_existing_process_in_foreign_tmux_server_is_attached_to_target_pane(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        info = agentic_sessions.ProcessInfo(123, 1, 123, "/dev/pts/7", "S", ("codex", "resume", session_id))
        pane = agentic_sessions.TmuxPane(
            "%7", 99, "/dev/pts/7", "agentic", "0", True, "/tmp/tmux-1000/server-99.sock"
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            agentic_sessions.os.environ,
            {"TMUX": "/tmp/tmux-1000/default,456,0"},
            clear=False,
        ), mock.patch.object(agentic_sessions, "lock_holders", return_value=[info]), mock.patch.object(
            agentic_sessions, "tmux_panes", return_value=[pane]
        ), mock.patch.object(agentic_sessions, "attach_tmux_session_to_pane") as attach, mock.patch.object(
            agentic_sessions, "focus_tmux_pane"
        ) as focus:
            handled, message = agentic_sessions.recover_existing_session(
                self.make_session(session_id),
                self.make_config(Path(tmp)),
                reattach_target_pane="%2",
                suspend_reattach_target=True,
            )

        self.assertTrue(handled)
        self.assertIn("attached existing", message)
        attach.assert_called_once_with("%2", pane, True)
        focus.assert_not_called()

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

    def test_unreachable_owner_confirmation_decline_keeps_running(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        info = agentic_sessions.ProcessInfo(123, 1, 456, "/dev/pts/7", "S", ("codex", "resume", session_id))
        confirm = mock.Mock(return_value=False)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            agentic_sessions, "lock_holders", return_value=[info]
        ), mock.patch.object(agentic_sessions, "tmux_panes", return_value=[]), mock.patch.object(
            agentic_sessions, "session_processes", return_value=[info]
        ), mock.patch.object(agentic_sessions, "interrupt_process_group_for_lock") as interrupt:
            handled, message = agentic_sessions.recover_existing_session(
                self.make_session(session_id),
                self.make_config(Path(tmp)),
                confirm_terminate=confirm,
                interrupt_group_only=True,
            )

        self.assertTrue(handled)
        self.assertIn("left existing", message)
        confirm.assert_called_once()
        interrupt.assert_not_called()

    def test_unreachable_owner_confirmation_interrupts_process_group(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        info = agentic_sessions.ProcessInfo(123, 1, 456, "/dev/pts/7", "S", ("codex", "resume", session_id))
        confirm = mock.Mock(return_value=True)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            agentic_sessions, "lock_holders", return_value=[info]
        ), mock.patch.object(agentic_sessions, "tmux_panes", return_value=[]), mock.patch.object(
            agentic_sessions, "session_processes", return_value=[info]
        ), mock.patch.object(
            agentic_sessions, "interrupt_process_group_for_lock", return_value=True
        ) as interrupt, mock.patch.object(agentic_sessions, "stop_existing_session_processes") as stop:
            handled, message = agentic_sessions.recover_existing_session(
                self.make_session(session_id),
                self.make_config(Path(tmp)),
                confirm_terminate=confirm,
                interrupt_group_only=True,
            )

        self.assertFalse(handled)
        self.assertIn("interrupted old process group 456", message)
        confirm.assert_called_once()
        interrupt.assert_called_once()
        stop.assert_not_called()

    def test_process_group_interrupt_sends_sigint_and_waits_for_lock_release(self) -> None:
        session_id = "11111111-2222-3333-4444-555555555555"
        info = agentic_sessions.ProcessInfo(123, 1, 456, "/dev/pts/7", "S", ("codex", "resume", session_id))
        lock_path = Path("/tmp") / f"{session_id}.lock"
        with mock.patch.object(agentic_sessions.os, "getpgrp", return_value=999), mock.patch.object(
            agentic_sessions.os, "killpg"
        ) as killpg, mock.patch.object(agentic_sessions, "lock_holders", side_effect=[[info], []]):
            released = agentic_sessions.interrupt_process_group_for_lock(info, lock_path, session_id)

        self.assertTrue(released)
        killpg.assert_called_once_with(456, agentic_sessions.signal.SIGINT)

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
            [
                "/usr2/slingapp/.local/bin/qgenie",
                "codex",
                "-s",
                "danger-full-access",
                "-c",
                "model_providers.qgenie.supports_websockets=false",
                "resume",
                "01a03846-bb7b-7e02-a2ed-4fb31505afd3",
            ],
        )
        self.assertEqual(
            commands[2],
            ["/usr2/slingapp/.local/bin/qgenie", "resume", "01a03846-bb7b-7e02-a2ed-4fb31505afd3"],
        )

    def test_qgenie_does_not_duplicate_explicit_websocket_config(self) -> None:
        commands = agentic_sessions.resume_commands(
            "codex",
            "/usr2/slingapp/.local/bin/qgenie",
            "01a03846-bb7b-7e02-a2ed-4fb31505afd3",
            ["-c", "model_providers.qgenie.supports_websockets=false"],
        )

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][2:5], ["-c", "model_providers.qgenie.supports_websockets=false", "resume"])

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

    def test_resume_shell_command_sets_codex_home_and_uses_resume_id(self) -> None:
        session = agentic_sessions.Session(
            provider="codex",
            id="01a065e4-5834-70c2-9fec-9294009167f2",
            path=Path("/tmp/session.jsonl"),
            timestamp="",
            modified=0,
            cwd="/tmp/work tree",
            source="",
            model_provider="",
            cli_version="",
            first_prompt="",
            last_prompt="",
            resume_id="01a0a341-7363-7bd1-b737-34f4b38b56e1",
        )
        config = self.make_config(Path("/tmp/codex-home"))

        command = agentic_sessions.resume_shell_command(
            session,
            "/usr2/slingapp/.local/bin/qgenie",
            ["-s", "danger-full-access"],
            config,
        )

        self.assertIn("export CODEX_HOME='/tmp/codex-home';", command)
        self.assertIn("'resume' '01a0a341-7363-7bd1-b737-34f4b38b56e1'", command)
        self.assertNotIn("'resume' '01a065e4-5834-70c2-9fec-9294009167f2'", command)


if __name__ == "__main__":
    unittest.main()
