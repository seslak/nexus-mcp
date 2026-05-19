#!/usr/bin/env python3
"""Unit tests for Nexus MCP gateway behavior."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server as nexus_server


class NexusActionsTests(unittest.TestCase):
    def test_all_actions_have_dot(self):
        for action in nexus_server.NEXUS_ACTIONS:
            self.assertIn(".", action, f"Action missing dot: {action}")

    def test_namespaces_present(self):
        namespaces = {item.split(".")[0] for item in nexus_server.NEXUS_ACTIONS}
        for expected in ("nexus", "router", "governor", "thrift", "mnemo"):
            self.assertIn(expected, namespaces)

    def test_actions_sorted(self):
        self.assertEqual(nexus_server.NEXUS_ACTIONS, sorted(nexus_server.NEXUS_ACTIONS))

    def test_minimum_action_count(self):
        self.assertGreaterEqual(len(nexus_server.NEXUS_ACTIONS), 50)

    def test_contains_new_interaction_actions(self):
        self.assertIn("nexus.start_interaction", nexus_server.NEXUS_ACTIONS)
        self.assertIn("nexus.finish_interaction", nexus_server.NEXUS_ACTIONS)
        self.assertIn("nexus.status", nexus_server.NEXUS_ACTIONS)

    def test_contains_router_workflow_registry_actions(self):
        self.assertIn("router.match_workflow", nexus_server.NEXUS_ACTIONS)
        self.assertIn("router.get_workflow", nexus_server.NEXUS_ACTIONS)
        self.assertIn("router.list_workflows", nexus_server.NEXUS_ACTIONS)
        self.assertIn("router.validate_workflow_params", nexus_server.NEXUS_ACTIONS)

    def test_contains_new_governor_and_mnemo_query_actions(self):
        for action in [
            "governor.recent_runs",
            "governor.get_run",
            "governor.search_runs",
            "governor.recent_events",
            "governor.search_events",
            "governor.get_event",
            "governor.maintenance",
            "mnemo.recent_events",
            "mnemo.search_events",
            "mnemo.get_event",
            "mnemo.memory_events",
        ]:
            self.assertIn(action, nexus_server.NEXUS_ACTIONS)


class DispatchErrorTests(unittest.TestCase):
    def test_missing_action(self):
        result = nexus_server.nexus_gateway({})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "missing_action")

    def test_invalid_args_not_dict(self):
        result = nexus_server.nexus_gateway("not-a-dict")  # type: ignore[arg-type]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "invalid_args")

    def test_invalid_params_not_dict(self):
        result = nexus_server.nexus_gateway({"action": "nexus.status", "params": "bad"})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "invalid_params")

    def test_invalid_action_format_no_dot(self):
        result = nexus_server.nexus_gateway({"action": "nodot"})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "invalid_action_format")

    def test_unknown_namespace(self):
        result = nexus_server.nexus_gateway({"action": "unknown_ns.action"})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "unknown_namespace")

    def test_unknown_nexus_action(self):
        result = nexus_server.nexus_gateway({"action": "nexus.unknown"})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "unknown_action")

    def test_router_validate_workflow_params_dispatch_succeeds(self):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"valid": True, "workflowId": "workflow.small-refactor"},
        }
        with patch.object(nexus_server, "_call_router", return_value=payload) as mock_router:
            result = nexus_server.nexus_gateway(
                {
                    "action": "router.validate_workflow_params",
                    "params": {
                        "name": "workflow.small-refactor",
                        "params": {"task_summary": "Update README", "target_files": ["README.md"]},
                    },
                }
            )
        self.assertFalse(result["isError"], result)
        mock_router.assert_called_once()
        self.assertEqual(mock_router.call_args.args[0], "validate_workflow_params")


class StateBackedInteractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / "state" / "nexus"
        self.env = patch.dict(
            os.environ,
            {
                "NEXUS_WORKSPACE_ROOT": str(self.root),
                "NEXUS_STATE_DIR": str(self.state_dir),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        nexus_server._MODULE_CACHE.clear()
        if self.state_dir.exists():
            for item in self.state_dir.glob("*"):
                item.unlink()

    def _start_run_payload(self):
        return {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {
                "run_id": "run_123",
                "run": {"run_id": "run_123", "started_at": "2026-05-17T10:00:00Z"},
            },
        }

    def _status_payload(self):
        return {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"run_id": "run_123", "decision": "continue"},
        }

    def _finish_payload(self):
        return {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"run_id": "run_123", "status": "success"},
        }

    def _set_active_state(self):
        nexus_server._save_nexus_state(
            {
                "active_run_id": "run_123",
                "task": "Task",
                "profile": "small_patch",
                "metadata": {},
                "started_at": "2026-05-17T10:00:00Z",
                "last_action_at": "2026-05-17T10:00:00Z",
                "middleware_event_count": 0,
            }
        )

    def test_start_interaction_starts_governor_run_and_persists_state(self):
        with patch.object(nexus_server, "_call_governor", return_value=self._start_run_payload()) as mock_governor:
            result = nexus_server.nexus_gateway(
                {
                    "action": "nexus.start_interaction",
                    "params": {
                        "task": "Update inbox/iban.php",
                        "profile": "small_patch",
                        "metadata": {"ticket": "ABC-1"},
                    },
                }
            )
        self.assertFalse(result["isError"], result)
        sc = result["structuredContent"]
        self.assertEqual(sc["run_id"], "run_123")
        self.assertEqual(sc["profile"], "small_patch")
        state = nexus_server._load_nexus_state()
        self.assertEqual(state["active_run_id"], "run_123")
        self.assertEqual(state["task"], "Update inbox/iban.php")
        self.assertEqual(state["profile"], "small_patch")
        self.assertEqual(state["middleware_event_count"], 0)
        mock_governor.assert_called_once()
        self.assertEqual(mock_governor.call_args.args[0], "start_run")

    def test_status_returns_active_run_and_governor_status(self):
        self._set_active_state()
        with patch.object(nexus_server, "_call_governor", return_value=self._status_payload()) as mock_governor:
            result = nexus_server.nexus_gateway({"action": "nexus.status", "params": {}})
        self.assertFalse(result["isError"], result)
        sc = result["structuredContent"]
        self.assertIsNotNone(sc["active_interaction"])
        self.assertEqual(sc["active_interaction"]["active_run_id"], "run_123")
        self.assertIn("middleware", sc)
        self.assertEqual(sc["middleware"]["middleware_event_count"], 0)
        mock_governor.assert_called_once()
        self.assertEqual(mock_governor.call_args.args[0], "status")

    def test_finish_interaction_finishes_run_clears_state_and_records_memory(self):
        self._set_active_state()
        memory_payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"memory": {"id": "mem_123"}},
        }
        with (
            patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()) as mock_governor,
            patch.object(nexus_server, "_call_mnemo", return_value=memory_payload) as mock_mnemo,
        ):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done"}}
            )
        self.assertFalse(result["isError"], result)
        state = nexus_server._load_nexus_state()
        self.assertIsNone(state["active_run_id"])
        self.assertEqual(state["middleware_event_count"], 0)
        mock_governor.assert_called_once()
        self.assertEqual(mock_governor.call_args.args[0], "finish_run")
        mock_mnemo.assert_called_once()
        self.assertEqual(mock_mnemo.call_args.args[0], "record")
        params = mock_mnemo.call_args.args[1]
        self.assertEqual(params["kind"], "interaction_log")
        self.assertEqual(params["source_run_id"], "run_123")
        self.assertEqual(params["role"], "coordinator")
        self.assertIn("[success] Task", params["summary"])
        self.assertIn("done", params["summary"])
        self.assertTrue(result["structuredContent"]["auto_memory"]["recorded"])

    def test_finish_interaction_requires_active_run(self):
        result = nexus_server.nexus_gateway({"action": "nexus.finish_interaction", "params": {"status": "success"}})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "no_active_interaction")

    def test_finish_interaction_record_memory_false_skips_mnemo_write(self):
        self._set_active_state()
        with (
            patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()) as mock_governor,
            patch.object(nexus_server, "_call_mnemo") as mock_mnemo,
        ):
            result = nexus_server.nexus_gateway(
                {
                    "action": "nexus.finish_interaction",
                    "params": {"status": "success", "result": "done", "record_memory": False},
                }
            )
        self.assertFalse(result["isError"], result)
        mock_governor.assert_called_once()
        mock_mnemo.assert_not_called()
        self.assertFalse(result["structuredContent"]["auto_memory"]["attempted"])
        self.assertFalse(result["structuredContent"]["auto_memory"]["recorded"])

    def test_finish_interaction_mnemo_failure_returns_warning_not_error(self):
        self._set_active_state()
        with (
            patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()),
            patch.object(nexus_server, "_call_mnemo", side_effect=RuntimeError("mnemo unavailable")),
        ):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done"}}
            )
        self.assertFalse(result["isError"], result)
        sc = result["structuredContent"]
        self.assertFalse(sc["auto_memory"]["recorded"])
        self.assertIn("nexus_warnings", sc)
        self.assertIn("auto_memory_record failed", sc["nexus_warnings"][0])
        state = nexus_server._load_nexus_state()
        self.assertIsNone(state["active_run_id"])

    def test_finish_interaction_mnemo_error_payload_returns_warning_not_error(self):
        self._set_active_state()
        mnemo_error = {
            "content": [{"type": "text", "text": "Error: bad memory"}],
            "isError": True,
            "structuredContent": {"message": "bad memory"},
        }
        with (
            patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()),
            patch.object(nexus_server, "_call_mnemo", return_value=mnemo_error),
        ):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done"}}
            )
        self.assertFalse(result["isError"], result)
        sc = result["structuredContent"]
        self.assertFalse(sc["auto_memory"]["recorded"])
        self.assertIn("bad memory", sc["nexus_warnings"][0])

    def test_finish_interaction_respects_nexus_auto_memory_env_default(self):
        self._set_active_state()
        with (
            patch.dict(os.environ, {"NEXUS_AUTO_MEMORY": "0"}),
            patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()),
            patch.object(nexus_server, "_call_mnemo") as mock_mnemo,
        ):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done"}}
            )
        self.assertFalse(result["isError"], result)
        mock_mnemo.assert_not_called()
        self.assertFalse(result["structuredContent"]["auto_memory"]["enabled"])


class MiddlewareAutoRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / "state" / "nexus"
        self.env = patch.dict(
            os.environ,
            {
                "NEXUS_WORKSPACE_ROOT": str(self.root),
                "NEXUS_STATE_DIR": str(self.state_dir),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        nexus_server._MODULE_CACHE.clear()
        nexus_server._save_nexus_state(
            {
                "active_run_id": "run_123",
                "task": "Task",
                "profile": "small_patch",
                "metadata": {},
                "started_at": "2026-05-17T10:00:00Z",
                "last_action_at": "2026-05-17T10:00:00Z",
                "middleware_event_count": 0,
            }
        )

    def _ok(self, structured: dict | None = None):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": structured or {},
        }
        return payload

    def test_thrift_file_window_auto_records_event(self):
        with (
            patch.object(nexus_server, "_call_thrift", return_value=self._ok({"lines": [{"n": 1, "text": "x"}]})),
            patch.object(nexus_server, "_call_governor", return_value=self._ok()) as mock_governor,
        ):
            result = nexus_server.nexus_gateway(
                {
                    "action": "thrift.file_window",
                    "params": {"path": "inbox/iban.php", "start_line": 1, "end_line": 20},
                }
            )
        self.assertFalse(result["isError"], result)
        self.assertEqual(mock_governor.call_count, 1)
        self.assertEqual(mock_governor.call_args.args[0], "record_tool_call")
        payload = mock_governor.call_args.args[1]
        self.assertEqual(payload["tool"], "thrift.file_window")
        self.assertIn("inbox/iban.php", payload["target"])
        state = nexus_server._load_nexus_state()
        self.assertEqual(state["middleware_event_count"], 1)

    def test_mnemo_search_auto_records_event(self):
        with (
            patch.object(nexus_server, "_call_mnemo", return_value=self._ok({"matches": []})),
            patch.object(nexus_server, "_call_governor", return_value=self._ok()) as mock_governor,
        ):
            result = nexus_server.nexus_gateway(
                {"action": "mnemo.search", "params": {"query": "current task summary", "limit": 8}}
            )
        self.assertFalse(result["isError"], result)
        payload = mock_governor.call_args.args[1]
        self.assertEqual(payload["tool"], "mnemo.search")
        self.assertIn("current task summary", payload["target"])

    def test_mnemo_record_auto_records_event(self):
        with (
            patch.object(nexus_server, "_call_mnemo", return_value=self._ok({"memory": {"id": "mem_1"}})),
            patch.object(nexus_server, "_call_governor", return_value=self._ok()) as mock_governor,
        ):
            result = nexus_server.nexus_gateway(
                {"action": "mnemo.record", "params": {"kind": "interaction_log", "text": "hello"}}
            )
        self.assertFalse(result["isError"], result)
        payload = mock_governor.call_args.args[1]
        self.assertEqual(payload["tool"], "mnemo.record")
        self.assertIn("interaction_log", payload["target"])

    def test_router_match_workflow_auto_records_event(self):
        with (
            patch.object(
                nexus_server,
                "_call_router",
                return_value=self._ok({"routeType": "WORKFLOW", "taskClass": "documentation_update"}),
            ),
            patch.object(nexus_server, "_call_governor", return_value=self._ok()) as mock_governor,
        ):
            result = nexus_server.nexus_gateway(
                {
                    "action": "router.match_workflow",
                    "params": {
                        "name": "workflow.docs-sync",
                        "params": {"task_summary": "Update docs for onboarding"},
                    },
                }
            )
        self.assertFalse(result["isError"], result)
        payload = mock_governor.call_args.args[1]
        self.assertEqual(payload["tool"], "router.match_workflow")

    def test_no_recursion_for_governor_record_tool_call(self):
        with patch.object(nexus_server, "_call_governor", return_value=self._ok()) as mock_governor:
            result = nexus_server.nexus_gateway(
                {"action": "governor.record_tool_call", "params": {"tool": "x", "target": "y", "success": True}}
            )
        self.assertFalse(result["isError"], result)
        self.assertEqual(mock_governor.call_count, 1, "governor.record_tool_call must not self-record")
        self.assertEqual(mock_governor.call_args.args[0], "record_tool_call")

    def test_auto_record_failure_does_not_break_main_action(self):
        with (
            patch.object(nexus_server, "_call_mnemo", return_value=self._ok({"matches": []})),
            patch.object(nexus_server, "_call_governor", side_effect=RuntimeError("governor unavailable")),
        ):
            result = nexus_server.nexus_gateway({"action": "mnemo.search", "params": {"query": "x"}})
        self.assertFalse(result["isError"], result)
        sc = result.get("structuredContent", {})
        self.assertIn("nexus_warnings", sc)
        self.assertGreaterEqual(len(sc["nexus_warnings"]), 1)
        state = nexus_server._load_nexus_state()
        self.assertEqual(state["middleware_event_count"], 0)


class ToolSchemaTests(unittest.TestCase):
    def test_single_tool_named_nexus(self):
        self.assertEqual(len(nexus_server.TOOLS), 1)
        self.assertEqual(nexus_server.TOOLS[0]["name"], "nexus")

    def test_schema_has_required_action(self):
        schema = nexus_server.TOOLS[0]["inputSchema"]
        self.assertIn("action", schema.get("required", []))

    def test_schema_no_forbidden_keys(self):
        forbidden = {
            "minimum",
            "maximum",
            "default",
            "minItems",
            "maxItems",
            "minLength",
            "maxLength",
            "pattern",
            "anyOf",
            "oneOf",
            "allOf",
            "not",
            "const",
            "format",
            "examples",
            "nullable",
            "$ref",
        }
        schema_str = json.dumps(nexus_server.TOOLS[0]["inputSchema"])
        for key in forbidden:
            self.assertNotIn(f'"{key}":', schema_str)

    def test_action_enum_matches_nexus_actions(self):
        schema = nexus_server.TOOLS[0]["inputSchema"]
        enum_values = schema["properties"]["action"]["enum"]
        self.assertEqual(sorted(enum_values), sorted(nexus_server.NEXUS_ACTIONS))


class MCPServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp = cls._tmpdir.name
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["NEXUS_WORKSPACE_ROOT"] = tmp
        env["NEXUS_STATE_DIR"] = str(Path(tmp) / "state" / "nexus")
        cls._proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        assert cls._proc.stdin is not None
        assert cls._proc.stdout is not None
        cls._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, separators=(",", ":")) + "\n")
        cls._proc.stdin.flush()
        cls._init_response = json.loads(cls._proc.stdout.readline())
        cls._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, separators=(",", ":")) + "\n")
        cls._proc.stdin.flush()
        cls._tools_response = json.loads(cls._proc.stdout.readline())

    @classmethod
    def tearDownClass(cls):
        try:
            assert cls._proc.stdin is not None
            cls._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"}, separators=(",", ":")) + "\n")
            cls._proc.stdin.flush()
        except Exception:
            pass
        for pipe in (cls._proc.stdin, cls._proc.stdout, cls._proc.stderr):
            if pipe and not pipe.closed:
                try:
                    pipe.close()
                except Exception:
                    pass
        try:
            cls._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls._proc.terminate()
            cls._proc.wait(timeout=5)
        cls._tmpdir.cleanup()

    def test_initialize_server_name(self):
        self.assertEqual(self._init_response["result"]["serverInfo"]["name"], "nexus")

    def test_initialize_server_version(self):
        self.assertEqual(self._init_response["result"]["serverInfo"]["version"], "0.2.2")

    def test_tools_list_single_nexus_tool(self):
        tools = self._tools_response["result"]["tools"]
        self.assertEqual({item["name"] for item in tools}, {"nexus"})

    def test_tools_list_schema_valid(self):
        tools = self._tools_response["result"]["tools"]
        schema = tools[0]["inputSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("action", schema["required"])


if __name__ == "__main__":
    unittest.main()
