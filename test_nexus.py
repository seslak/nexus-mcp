#!/usr/bin/env python3
"""Unit tests for Nexus MCP gateway behavior."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server as nexus_server


MNEMO_TOPIC_ACTIONS = [
    "mnemo.topic_add",
    "mnemo.topic_remove",
    "mnemo.topic_list",
]

MNEMO_MEMORY_PACK_ACTIONS = [
    "mnemo.pack_landing_list",
    "mnemo.pack_preview",
    "mnemo.pack_redaction_preview",
    "mnemo.pack_export",
    "mnemo.pack_inspect",
    "mnemo.pack_import",
    "mnemo.pack_list_imports",
    "mnemo.pack_review_import",
    "mnemo.pack_promote_preview",
    "mnemo.pack_promote",
]

MNEMO_MEMORY_GROUP_ACTIONS = [
    "mnemo.memory_group_discover",
    "mnemo.memory_group_preview",
]

MNEMO_SIGNER_ACTIONS = [
    "mnemo.signer_add",
    "mnemo.signer_list",
    "mnemo.signer_disable",
    "mnemo.signer_enable",
]


def _load_mnemo_gateway_actions_for_drift_test() -> set[str]:
    candidate_paths = [
        nexus_server._mnemo_server_path(),
        ROOT.parent / "mnemo" / "server.py",
        ROOT.parent / "pub_mnemo" / "server.py",
    ]
    target_path = next((path for path in candidate_paths if Path(path).exists()), None)
    if target_path is None:
        raise unittest.SkipTest("Mnemo server.py not found for drift test.")
    target = Path(target_path).resolve()
    module_dir = str(target.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("nexus_mnemo_drift_probe", str(target))
    if spec is None or spec.loader is None:
        raise unittest.SkipTest(f"Unable to load Mnemo module for drift test: {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    gateway_actions = getattr(module, "GATEWAY_ACTIONS", {})
    if not isinstance(gateway_actions, dict):
        raise unittest.SkipTest("Mnemo GATEWAY_ACTIONS is unavailable for drift test.")
    return {str(item).strip() for item in gateway_actions.keys() if str(item).strip()}


def _load_governor_gateway_actions_for_drift_test() -> set[str]:
    candidate_paths = [
        nexus_server._governor_server_path(),
        ROOT.parent / "agent-governor" / "src" / "agent_governor" / "mcp_server.py",
        ROOT.parent / "pub_agent-governor" / "src" / "agent_governor" / "mcp_server.py",
    ]
    target_path = next((path for path in candidate_paths if Path(path).exists()), None)
    if target_path is None:
        raise unittest.SkipTest("Governor mcp_server.py not found for drift test.")
    target = Path(target_path).resolve()
    module_dir = str(target.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("nexus_governor_drift_probe", str(target))
    if spec is None or spec.loader is None:
        raise unittest.SkipTest(f"Unable to load Governor module for drift test: {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handlers = getattr(module, "ACTION_HANDLERS", {})
    if not isinstance(handlers, dict):
        raise unittest.SkipTest("Governor ACTION_HANDLERS unavailable for drift test.")
    return {str(item).strip() for item in handlers.keys() if str(item).strip()}


def _load_router_gateway_actions_for_drift_test() -> set[str]:
    candidate_paths = [
        nexus_server._router_server_path(),
        ROOT.parent / "agent-router" / "server.py",
        ROOT.parent / "pub_agent-router" / "server.py",
    ]
    target_path = next((path for path in candidate_paths if Path(path).exists()), None)
    if target_path is None:
        raise unittest.SkipTest("Router server.py not found for drift test.")
    target = Path(target_path).resolve()
    module_dir = str(target.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("nexus_router_drift_probe", str(target))
    if spec is None or spec.loader is None:
        raise unittest.SkipTest(f"Unable to load Router module for drift test: {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actions = getattr(module, "GATEWAY_ACTIONS", {})
    if not isinstance(actions, dict):
        raise unittest.SkipTest("Router GATEWAY_ACTIONS unavailable for drift test.")
    return {str(item).strip() for item in actions.keys() if str(item).strip()}


def _load_thrift_gateway_actions_for_drift_test() -> set[str]:
    candidate_paths = [
        nexus_server._thrift_server_path(),
        ROOT.parent / "thrift" / "server.py",
        ROOT.parent / "pub_thrift" / "server.py",
    ]
    target_path = next((path for path in candidate_paths if Path(path).exists()), None)
    if target_path is None:
        raise unittest.SkipTest("Thrift server.py not found for drift test.")
    target = Path(target_path).resolve()
    module_dir = str(target.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("nexus_thrift_drift_probe", str(target))
    if spec is None or spec.loader is None:
        raise unittest.SkipTest(f"Unable to load Thrift module for drift test: {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actions = getattr(module, "THRIFT_ACTIONS", ())
    if not isinstance(actions, (tuple, list)):
        raise unittest.SkipTest("Thrift THRIFT_ACTIONS unavailable for drift test.")
    return {str(item).strip() for item in actions if str(item).strip()}


class NexusActionsTests(unittest.TestCase):
    def test_mcp_schema_enum_contains_mnemo_memory_group_actions(self):
        schema_enum = set(nexus_server.TOOLS[0]["inputSchema"]["properties"]["action"]["enum"])
        self.assertIn("mnemo.memory_group_discover", schema_enum)
        self.assertIn("mnemo.memory_group_preview", schema_enum)

    def test_mcp_schema_enum_matches_nexus_actions(self):
        schema_enum = set(nexus_server.TOOLS[0]["inputSchema"]["properties"]["action"]["enum"])
        listed = nexus_server.nexus_gateway({"action": "nexus.list_actions", "params": {}})
        self.assertFalse(listed["isError"], listed)
        listed_actions = set(((listed.get("structuredContent") or {}).get("actions") or []))
        self.assertEqual(schema_enum, set(nexus_server.NEXUS_ACTIONS))
        self.assertEqual(schema_enum, listed_actions)

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

    def test_nexus_exposes_mnemo_memory_pack_actions(self):
        for action in MNEMO_MEMORY_PACK_ACTIONS:
            self.assertIn(action, nexus_server.NEXUS_ACTIONS)

    def test_nexus_exposes_mnemo_memory_group_actions(self):
        for action in MNEMO_MEMORY_GROUP_ACTIONS:
            self.assertIn(action, nexus_server.NEXUS_ACTIONS)

    def test_nexus_exposes_mnemo_signer_actions(self):
        for action in MNEMO_SIGNER_ACTIONS:
            self.assertIn(action, nexus_server.NEXUS_ACTIONS)

    def test_nexus_exposes_mnemo_topic_actions(self):
        for action in MNEMO_TOPIC_ACTIONS:
            self.assertIn(action, nexus_server.NEXUS_ACTIONS)

    def test_nexus_namespace_action_catalogue_no_mnemo_drift(self):
        mnemo_gateway_actions = _load_mnemo_gateway_actions_for_drift_test()
        nexus_mnemo_actions = set(nexus_server._NAMESPACE_ACTIONS["mnemo"])
        missing = sorted(mnemo_gateway_actions - nexus_mnemo_actions)
        stale = sorted(nexus_mnemo_actions - mnemo_gateway_actions)
        self.assertEqual(missing, [], f"Nexus missing mnemo actions: {missing}")
        self.assertEqual(stale, [], f"Nexus has stale mnemo actions: {stale}")

    def test_nexus_namespace_action_catalogue_no_governor_drift(self):
        governor_actions = _load_governor_gateway_actions_for_drift_test()
        self.assertEqual(set(nexus_server._NAMESPACE_ACTIONS["governor"]), governor_actions)

    def test_nexus_namespace_action_catalogue_no_router_drift(self):
        router_actions = _load_router_gateway_actions_for_drift_test()
        self.assertEqual(set(nexus_server._NAMESPACE_ACTIONS["router"]), router_actions)

    def test_nexus_namespace_action_catalogue_no_thrift_drift(self):
        thrift_actions = _load_thrift_gateway_actions_for_drift_test()
        self.assertEqual(set(nexus_server._NAMESPACE_ACTIONS["thrift"]), thrift_actions)

    def test_mnemo_namespace_actions_are_consistent_across_catalog_schema_and_list_actions(self):
        listed = nexus_server.nexus_gateway({"action": "nexus.list_actions", "params": {}})
        self.assertFalse(listed["isError"], listed)
        listed_actions = set(((listed.get("structuredContent") or {}).get("actions") or []))
        schema_enum = set(nexus_server.TOOLS[0]["inputSchema"]["properties"]["action"]["enum"])
        for subaction in nexus_server._NAMESPACE_ACTIONS["mnemo"]:
            fq_action = f"mnemo.{subaction}"
            self.assertIn(fq_action, nexus_server.NEXUS_ACTIONS)
            self.assertIn(fq_action, listed_actions)
            self.assertIn(fq_action, schema_enum)

    def test_memory_pack_actions_present_in_schema_and_list_actions(self):
        listed = nexus_server.nexus_gateway({"action": "nexus.list_actions", "params": {}})
        self.assertFalse(listed["isError"], listed)
        listed_actions = set(((listed.get("structuredContent") or {}).get("actions") or []))
        schema_enum = set(nexus_server.TOOLS[0]["inputSchema"]["properties"]["action"]["enum"])
        for action in MNEMO_MEMORY_PACK_ACTIONS:
            self.assertIn(action, listed_actions)
            self.assertIn(action, schema_enum)

    def test_signer_actions_present_in_schema_and_list_actions(self):
        listed = nexus_server.nexus_gateway({"action": "nexus.list_actions", "params": {}})
        self.assertFalse(listed["isError"], listed)
        listed_actions = set(((listed.get("structuredContent") or {}).get("actions") or []))
        schema_enum = set(nexus_server.TOOLS[0]["inputSchema"]["properties"]["action"]["enum"])
        for action in MNEMO_SIGNER_ACTIONS:
            self.assertIn(action, listed_actions)
            self.assertIn(action, schema_enum)

    def test_topic_actions_present_in_schema_and_list_actions(self):
        listed = nexus_server.nexus_gateway({"action": "nexus.list_actions", "params": {}})
        self.assertFalse(listed["isError"], listed)
        listed_actions = set(((listed.get("structuredContent") or {}).get("actions") or []))
        schema_enum = set(nexus_server.TOOLS[0]["inputSchema"]["properties"]["action"]["enum"])
        for action in MNEMO_TOPIC_ACTIONS:
            self.assertIn(action, listed_actions)
            self.assertIn(action, schema_enum)

    def test_nexus_mnemo_action_drift_guard_includes_memory_group_actions(self):
        mnemo_gateway_actions = _load_mnemo_gateway_actions_for_drift_test()
        self.assertIn("memory_group_discover", mnemo_gateway_actions)
        self.assertIn("memory_group_preview", mnemo_gateway_actions)


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

    def test_nexus_mnemo_pack_preview_dispatches(self):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"action": "pack_preview", "selected_rows": 0},
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=payload) as mock_mnemo:
            result = nexus_server.nexus_gateway({"action": "mnemo.pack_preview", "params": {}})
        self.assertFalse(result["isError"], result)
        mock_mnemo.assert_called_once_with("pack_preview", {})

    def test_nexus_mnemo_pack_landing_list_dispatches(self):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"action": "pack_landing_list", "packs": []},
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=payload) as mock_mnemo:
            result = nexus_server.nexus_gateway({"action": "mnemo.pack_landing_list", "params": {"limit": 10}})
        self.assertFalse(result["isError"], result)
        mock_mnemo.assert_called_once_with("pack_landing_list", {"limit": 10})

    def test_nexus_mnemo_pack_inspect_dispatches_to_mnemo_error(self):
        mnemo_error = {
            "content": [{"type": "text", "text": "Error: pack_path is required"}],
            "isError": True,
            "structuredContent": {"error": "missing_pack_path"},
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=mnemo_error) as mock_mnemo:
            result = nexus_server.nexus_gateway({"action": "mnemo.pack_inspect", "params": {}})
        self.assertTrue(result["isError"], result)
        self.assertEqual((result.get("structuredContent") or {}).get("error"), "missing_pack_path")
        mock_mnemo.assert_called_once_with("pack_inspect", {})

    def test_nexus_mnemo_signer_list_dispatches(self):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"action": "signer_list", "signers": []},
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=payload) as mock_mnemo:
            result = nexus_server.nexus_gateway({"action": "mnemo.signer_list", "params": {}})
        self.assertFalse(result["isError"], result)
        mock_mnemo.assert_called_once_with("signer_list", {})

    def test_nexus_dispatches_mnemo_memory_group_discover(self):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"action": "memory_group_discover", "groups": []},
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=payload) as mock_mnemo:
            result = nexus_server.nexus_gateway({"action": "mnemo.memory_group_discover", "params": {}})
        self.assertFalse(result["isError"], result)
        mock_mnemo.assert_called_once_with("memory_group_discover", {})

    def test_tools_call_accepts_mnemo_memory_group_discover(self):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"action": "memory_group_discover", "groups": []},
        }
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "nexus",
                "arguments": {
                    "action": "mnemo.memory_group_discover",
                    "params": {"limit_groups": 10, "include_samples": True, "sample_per_group": 3},
                },
            },
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=payload) as mock_mnemo:
            with patch.object(nexus_server, "_send") as mock_send:
                nexus_server.handle_request(request)
        mock_mnemo.assert_called_once_with(
            "memory_group_discover",
            {"limit_groups": 10, "include_samples": True, "sample_per_group": 3},
        )
        sent = mock_send.call_args.args[0]
        self.assertEqual(sent["id"], 1)
        self.assertFalse(sent["result"]["isError"], sent)

    def test_tools_call_accepts_mnemo_memory_group_preview_validation_path(self):
        mnemo_error = {
            "content": [{"type": "text", "text": "Error: group_id is required"}],
            "isError": True,
            "structuredContent": {"error": "missing_group_id", "message": "group_id is required"},
        }
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "nexus",
                "arguments": {"action": "mnemo.memory_group_preview", "params": {}},
            },
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=mnemo_error) as mock_mnemo:
            with patch.object(nexus_server, "_send") as mock_send:
                nexus_server.handle_request(request)
        mock_mnemo.assert_called_once_with("memory_group_preview", {})
        sent = mock_send.call_args.args[0]
        self.assertEqual(sent["id"], 2)
        self.assertTrue(sent["result"]["isError"], sent)
        self.assertEqual((sent["result"].get("structuredContent") or {}).get("error"), "missing_group_id")

    def test_all_exposed_mnemo_actions_dispatch_through_namespace_delegate(self):
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"ok": True},
        }
        with patch.object(nexus_server, "_call_mnemo", return_value=payload) as mock_mnemo:
            for subaction in nexus_server._NAMESPACE_ACTIONS["mnemo"]:
                result = nexus_server.nexus_gateway({"action": f"mnemo.{subaction}", "params": {}})
                self.assertFalse(result["isError"], f"dispatch failed for mnemo.{subaction}: {result}")
            called_actions = [call.args[0] for call in mock_mnemo.call_args_list]
        self.assertEqual(sorted(called_actions), sorted(nexus_server._NAMESPACE_ACTIONS["mnemo"]))


class ThriftTelemetryMirrorTests(unittest.TestCase):
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

    def _fake_thrift_module(
        self,
        resolved_action: str,
        resolved_params: dict[str, object],
        result: dict[str, object],
        *,
        append_side_effect: Exception | None = None,
    ):
        mod = type("FakeThriftModule", (), {})()
        mod.thrift_gateway = Mock(return_value=(resolved_action, resolved_params, result))
        mod.tool_log_metadata = Mock(return_value=(42, {"target": "x"}))
        mod.append_economy_log = Mock(side_effect=append_side_effect)
        return mod

    def test_thrift_call_mirrors_telemetry_and_calls_gateway_once(self):
        params = {"path": "inbox/iban.php", "start_line": 1, "end_line": 20}
        resolved_params = dict(params)
        result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        fake_mod = self._fake_thrift_module("file_window", resolved_params, result)

        with patch.object(nexus_server, "_load_module", return_value=fake_mod):
            out = nexus_server._call_thrift("file_window", params)

        self.assertEqual(out, result)
        fake_mod.thrift_gateway.assert_called_once_with({"action": "file_window", "params": params})
        fake_mod.tool_log_metadata.assert_called_once()
        fake_mod.append_economy_log.assert_called_once()

    def test_thrift_call_stashes_mirror_hash(self):
        params = {"path": "inbox/iban.php"}
        result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        fake_mod = self._fake_thrift_module("file_window", dict(params), result)
        fake_mod.append_economy_log = Mock(return_value={"content_hash": "hash-1"})
        with patch.object(nexus_server, "_load_module", return_value=fake_mod):
            nexus_server._call_thrift("file_window", params)
        self.assertEqual(nexus_server._LAST_THRIFT_MIRROR_HASH, "hash-1")

    def test_thrift_call_mirror_failure_clears_hash(self):
        params = {"path": "inbox/iban.php"}
        result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        fake_mod = self._fake_thrift_module("file_window", dict(params), result, append_side_effect=RuntimeError("mirror failed"))
        nexus_server._LAST_THRIFT_MIRROR_HASH = "stale"
        with patch.object(nexus_server, "_load_module", return_value=fake_mod):
            nexus_server._call_thrift("file_window", params)
        self.assertIsNone(nexus_server._LAST_THRIFT_MIRROR_HASH)

    def test_active_run_id_is_injected_for_mirror_only(self):
        nexus_server._save_nexus_state({"active_run_id": "run_123"})
        params = {"query": "needle"}
        params_before = dict(params)
        resolved_params = {"query": "needle"}
        result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        fake_mod = self._fake_thrift_module("search", resolved_params, result)

        with patch.object(nexus_server, "_load_module", return_value=fake_mod):
            out = nexus_server._call_thrift("search", params)

        self.assertEqual(out, result)
        self.assertEqual(params, params_before)
        self.assertNotIn("run_id", resolved_params)
        mirror_args = fake_mod.append_economy_log.call_args.args[1]
        self.assertEqual(mirror_args.get("run_id"), "run_123")
        gateway_payload = fake_mod.thrift_gateway.call_args.args[0]
        self.assertEqual(gateway_payload["params"], params_before)
        self.assertNotIn("run_id", gateway_payload["params"])

    def test_telemetry_failure_does_not_break_response(self):
        params = {"path": "inbox/iban.php"}
        result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        fake_mod = self._fake_thrift_module(
            "file_window",
            dict(params),
            result,
            append_side_effect=RuntimeError("telemetry write failed"),
        )

        with (
            patch.object(nexus_server, "_load_module", return_value=fake_mod),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            out = nexus_server._call_thrift("file_window", params)

        self.assertEqual(out, result)
        self.assertIn("[nexus] thrift telemetry mirror failed for action=file_window:", stderr.getvalue())

    def test_no_active_run_id_still_writes_telemetry_without_run_id(self):
        params = {"path": "inbox/iban.php"}
        resolved_params = dict(params)
        result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        fake_mod = self._fake_thrift_module("file_window", resolved_params, result)

        with patch.object(nexus_server, "_load_module", return_value=fake_mod):
            out = nexus_server._call_thrift("file_window", params)

        self.assertEqual(out, result)
        mirror_args = fake_mod.append_economy_log.call_args.args[1]
        self.assertNotIn("run_id", mirror_args)
        self.assertEqual(mirror_args["path"], "inbox/iban.php")


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

    def _finish_payload(self, status: str = "success"):
        return {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"run_id": "run_123", "status": status},
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

    def _set_active_state_with_metadata(self, metadata: dict[str, object]):
        nexus_server._save_nexus_state(
            {
                "active_run_id": "run_123",
                "task": "Task",
                "profile": "small_patch",
                "metadata": dict(metadata),
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

    def test_save_nexus_state_is_atomic_and_cleans_temp_file(self):
        nexus_server._save_nexus_state({"active_run_id": "run_123", "task": "Task"})
        state_path = self.state_dir / "nexus_state.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["active_run_id"], "run_123")
        self.assertEqual(list(self.state_dir.glob("nexus_state.json.tmp-*")), [])

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
        self.assertEqual(mock_governor.call_args.args[1]["record_check"], False)
        self.assertEqual(mock_governor.call_args.args[1]["run_id"], "run_123")

    def test_status_is_read_only_for_nexus_state_and_governor(self):
        self._set_active_state()
        before = nexus_server._load_nexus_state()
        with patch.object(nexus_server, "_call_governor", return_value=self._status_payload()):
            nexus_server.nexus_gateway({"action": "nexus.status", "params": {}})
        after = nexus_server._load_nexus_state()
        self.assertEqual(after["last_action_at"], before["last_action_at"])
        self.assertEqual(after["middleware_event_count"], before["middleware_event_count"])

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
        self.assertEqual(mock_governor.call_args.args[1]["run_id"], "run_123")
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

    def test_finish_interaction_clears_state_when_governor_already_closed_run(self):
        self._set_active_state()
        governor_error = {
            "content": [{"type": "text", "text": "Error: no current run"}],
            "isError": True,
            "structuredContent": {"error": "no_current_run", "message": "no current run"},
        }
        with patch.object(nexus_server, "_call_governor", return_value=governor_error):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done"}}
            )
        self.assertFalse(result["isError"], result)
        self.assertIsNone(nexus_server._load_nexus_state()["active_run_id"])
        self.assertFalse(result["structuredContent"]["auto_memory"]["attempted"])
        self.assertIn("nexus_warnings", result["structuredContent"])

    def test_finish_interaction_clears_state_when_governor_run_not_active(self):
        self._set_active_state()
        governor_error = {
            "content": [{"type": "text", "text": "Error: run not active"}],
            "isError": True,
            "structuredContent": {"error": "run_not_active", "message": "run not active"},
        }
        with patch.object(nexus_server, "_call_governor", return_value=governor_error):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done"}}
            )
        self.assertFalse(result["isError"], result)
        self.assertTrue(result["structuredContent"]["finished"])
        self.assertIsNone(nexus_server._load_nexus_state()["active_run_id"])
        self.assertIn("run_not_active", result["structuredContent"]["nexus_warnings"][0])

    def test_reset_interaction_requires_confirm(self):
        self._set_active_state()
        result = nexus_server.nexus_gateway({"action": "nexus.reset_interaction", "params": {}})
        self.assertTrue(result["isError"], result)
        self.assertEqual(result["structuredContent"]["error"], "confirmation_required")

    def test_reset_interaction_can_abandon_governor_run(self):
        self._set_active_state()
        with patch.object(
            nexus_server,
            "_call_governor",
            return_value={"content": [{"type": "text", "text": "ok"}], "isError": False, "structuredContent": {"reset": True, "active_run": "run_123"}},
        ) as mock_governor:
            result = nexus_server.nexus_gateway(
                {"action": "nexus.reset_interaction", "params": {"confirm": True, "abandon_run": True}}
            )
        self.assertFalse(result["isError"], result)
        self.assertIsNone(nexus_server._load_nexus_state()["active_run_id"])
        mock_governor.assert_called_once_with("reset_run", {"yes": True})
        self.assertIn("governor", result["structuredContent"])

    def test_direct_governor_finish_clears_matching_interaction_state(self):
        self._set_active_state()
        with patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()) as mock_governor:
            result = nexus_server.nexus_gateway({"action": "governor.finish_run", "params": {"status": "success"}})
        self.assertFalse(result["isError"], result)
        self.assertIsNone(nexus_server._load_nexus_state()["active_run_id"])
        self.assertIn("nexus_warnings", result["structuredContent"])
        mock_governor.assert_called_once()

    def test_direct_governor_finish_other_run_keeps_state(self):
        self._set_active_state()
        payload = {"content": [{"type": "text", "text": "ok"}], "isError": False, "structuredContent": {"run_id": "run_other", "status": "success"}}
        with patch.object(nexus_server, "_call_governor", return_value=payload):
            result = nexus_server.nexus_gateway({"action": "governor.finish_run", "params": {"status": "success", "run_id": "run_other"}})
        self.assertFalse(result["isError"], result)
        self.assertEqual(nexus_server._load_nexus_state()["active_run_id"], "run_123")

    def test_finish_interaction_accepts_canonical_statuses(self):
        for status in sorted(nexus_server._FINISH_STATUS_CANONICAL):
            self._set_active_state()
            with patch.object(nexus_server, "_call_governor", return_value=self._finish_payload(status=status)) as mock_governor:
                result = nexus_server.nexus_gateway(
                    {
                        "action": "nexus.finish_interaction",
                        "params": {"status": status, "result": "done", "record_memory": False},
                    }
                )
            self.assertFalse(result["isError"], result)
            self.assertEqual(result["structuredContent"]["status"], status)
            self.assertEqual(mock_governor.call_args.args[0], "finish_run")
            self.assertEqual(mock_governor.call_args.args[1]["status"], status)

    def test_finish_interaction_legacy_status_synonyms_are_normalized(self):
        legacy_to_canonical = {
            "failure": "failed",
            "blocked": "stopped",
        }
        for legacy, canonical in legacy_to_canonical.items():
            self._set_active_state()
            with patch.object(nexus_server, "_call_governor", return_value=self._finish_payload(status=canonical)) as mock_governor:
                result = nexus_server.nexus_gateway(
                    {
                        "action": "nexus.finish_interaction",
                        "params": {"status": legacy, "result": "done", "record_memory": False},
                    }
                )
            self.assertFalse(result["isError"], result)
            self.assertEqual(result["structuredContent"]["status"], canonical)
            self.assertEqual(mock_governor.call_args.args[1]["status"], canonical)

    def test_finish_interaction_invalid_status_returns_validation_error(self):
        self._set_active_state()
        result = nexus_server.nexus_gateway(
            {
                "action": "nexus.finish_interaction",
                "params": {"status": "not_a_status", "result": "done", "record_memory": False},
            }
        )
        self.assertTrue(result["isError"], result)
        self.assertEqual(result["structuredContent"]["error"], "invalid_arguments")
        message = str((result.get("structuredContent") or {}).get("message", ""))
        self.assertIn("failed", message)
        self.assertIn("stopped", message)

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

    def test_finish_interaction_logs_router_outcome_from_metadata(self):
        self._set_active_state_with_metadata({"decision_id": "dec_1", "selected_model_id": "gpt-5", "selection_rank": 2, "agent_used": "router"})
        with (
            patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()),
            patch.object(nexus_server, "_call_mnemo") as mock_mnemo,
            patch.object(nexus_server, "_call_router", return_value={"content": [{"type": "text", "text": "ok"}], "isError": False, "structuredContent": {"logged": True}}) as mock_router,
        ):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done", "record_memory": False}}
            )
        self.assertFalse(result["isError"], result)
        mock_mnemo.assert_not_called()
        mock_router.assert_called_once_with(
            "log_outcome",
            {"decisionId": "dec_1", "outcome": "overridden", "selectedModelId": "gpt-5", "selectionRank": 2, "agentUsed": "router"},
        )

    def test_finish_interaction_router_outcome_failure_only_warns(self):
        self._set_active_state_with_metadata({"decision_id": "dec_1"})
        router_error = {"content": [{"type": "text", "text": "Error: no log"}], "isError": True, "structuredContent": {"message": "no log"}}
        with (
            patch.object(nexus_server, "_call_governor", return_value=self._finish_payload()),
            patch.object(nexus_server, "_call_mnemo") as mock_mnemo,
            patch.object(nexus_server, "_call_router", return_value=router_error),
        ):
            result = nexus_server.nexus_gateway(
                {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "done", "record_memory": False}}
            )
        self.assertFalse(result["isError"], result)
        mock_mnemo.assert_not_called()
        self.assertIn("router.log_outcome failed", result["structuredContent"]["nexus_warnings"][0])


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
        self.assertEqual(payload["run_id"], "run_123")
        state = nexus_server._load_nexus_state()
        self.assertEqual(state["middleware_event_count"], 1)

    def test_thrift_cost_report_is_not_auto_recorded(self):
        with (
            patch.object(nexus_server, "_call_thrift", return_value=self._ok({"mode": "summary"})),
            patch.object(nexus_server, "_call_governor", return_value=self._ok()) as mock_governor,
        ):
            result = nexus_server.nexus_gateway({"action": "thrift.cost_report", "params": {"mode": "summary"}})
        self.assertFalse(result["isError"], result)
        mock_governor.assert_not_called()
        state = nexus_server._load_nexus_state()
        self.assertEqual(state["middleware_event_count"], 0)

    def test_thrift_auto_record_passes_mirror_hash_and_clears_stash(self):
        nexus_server._LAST_THRIFT_MIRROR_HASH = "hash-123"
        with (
            patch.object(nexus_server, "_call_thrift", return_value=self._ok({"lines": [{"n": 1, "text": "x"}]})),
            patch.object(nexus_server, "_call_governor", return_value=self._ok()) as mock_governor,
        ):
            result = nexus_server.nexus_gateway(
                {"action": "thrift.file_window", "params": {"path": "inbox/iban.php", "start_line": 1, "end_line": 20}}
            )
        self.assertFalse(result["isError"], result)
        payload = mock_governor.call_args.args[1]
        self.assertEqual(payload["input_hash"], "hash-123")
        self.assertIsNone(nexus_server._LAST_THRIFT_MIRROR_HASH)

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

    def test_match_workflow_falls_back_to_suggest_workflow(self):
        unknown = {"content": [{"type": "text", "text": "Error: unknown"}], "isError": True, "structuredContent": {"error": "unknown_action"}}
        suggest = self._ok({"decision": {"routeType": "WORKFLOW"}})
        with patch.object(nexus_server, "_call_router", side_effect=[unknown, suggest]) as mock_router:
            result = nexus_server.nexus_gateway({"action": "router.match_workflow", "params": {"name": "wf.docs"}})
        self.assertFalse(result["isError"], result)
        self.assertEqual(mock_router.call_args_list[1].args[0], "suggest_workflow")
        self.assertEqual(result["structuredContent"]["nexus_alias"], "router.match_workflow -> router.suggest_workflow")

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

    def test_recorded_backend_call_writes_nexus_state_once(self):
        real_save = nexus_server._save_nexus_state
        with (
            patch.object(nexus_server, "_call_mnemo", return_value=self._ok({"matches": []})),
            patch.object(nexus_server, "_call_governor", return_value=self._ok()),
            patch.object(nexus_server, "_save_nexus_state", wraps=real_save) as mock_save,
        ):
            result = nexus_server.nexus_gateway({"action": "mnemo.search", "params": {"query": "x"}})
        self.assertFalse(result["isError"], result)
        self.assertEqual(mock_save.call_count, 1)


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

    def test_nexus_list_actions_and_schema_are_consistent_after_import(self):
        listed = nexus_server.nexus_gateway({"action": "nexus.list_actions", "params": {}})
        self.assertFalse(listed["isError"], listed)
        listed_actions = ((listed.get("structuredContent") or {}).get("actions") or [])
        schema_enum = nexus_server.TOOLS[0]["inputSchema"]["properties"]["action"]["enum"]
        self.assertEqual(listed_actions, nexus_server.NEXUS_ACTIONS)
        self.assertEqual(schema_enum, nexus_server.NEXUS_ACTIONS)


class DoctorAndProtocolTests(unittest.TestCase):
    def test_duplicate_module_name_helper_current_tree_is_empty(self):
        self.assertEqual(nexus_server._duplicate_top_level_module_names(), [])

    def test_duplicate_module_name_helper_detects_synthetic_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a"
            b = root / "b"
            a.mkdir()
            b.mkdir()
            (a / "same.py").write_text("x=1\n", encoding="utf-8")
            (b / "same.py").write_text("x=1\n", encoding="utf-8")
            (a / "only_a.py").write_text("x=1\n", encoding="utf-8")
            (b / "only_b.py").write_text("x=1\n", encoding="utf-8")
            with (
                patch.object(nexus_server, "_router_server_path", return_value=a / "server.py"),
                patch.object(nexus_server, "_mnemo_server_path", return_value=b / "server.py"),
                patch.object(nexus_server, "_thrift_server_path", return_value=root / "missing" / "server.py"),
                patch.object(nexus_server, "_governor_server_path", return_value=root / "missing2" / "mcp_server.py"),
            ):
                self.assertEqual(nexus_server._duplicate_top_level_module_names(), ["same.py"])

    def test_status_reports_root_mismatch_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "other"
            other.mkdir()
            with patch.dict(
                os.environ,
                {
                    "NEXUS_WORKSPACE_ROOT": tmp,
                    "NEXUS_STATE_DIR": str(Path(tmp) / "state" / "nexus"),
                    "THRIFT_WORKSPACE_ROOT": str(other),
                },
            ):
                result = nexus_server.nexus_gateway({"action": "nexus.status", "params": {}})
        self.assertFalse(result["isError"], result)
        warnings = result["structuredContent"]["warnings"]
        self.assertTrue(any("thrift workspace root mismatch" in warning for warning in warnings))

    def test_initialize_unknown_protocol_version_falls_back(self):
        with patch.object(nexus_server, "_send") as mock_send:
            nexus_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1900-01-01"}})
        self.assertEqual(mock_send.call_args.args[0]["result"]["protocolVersion"], nexus_server.PROTOCOL_VERSION)

    def test_ping_returns_empty_result(self):
        with patch.object(nexus_server, "_send") as mock_send:
            nexus_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        self.assertEqual(mock_send.call_args.args[0]["result"], {})

    def test_result_summary_uses_file_window_start_end_lines(self):
        summary = nexus_server._result_summary(
            "thrift",
            "file_window",
            {"isError": False, "structuredContent": {"start_line": 5, "end_line": 12, "content": "x"}},
        )
        self.assertEqual(summary, "thrift.file_window returned lines 5-12")

    def test_component_loading_and_gateway_calls_are_stdout_pure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root = root / "state"
            env = {
                "NEXUS_WORKSPACE_ROOT": str(root),
                "NEXUS_STATE_DIR": str(state_root / "nexus"),
                "NEXUS_ROUTER_SERVER": str((ROOT.parent / "agent-router" / "server.py").resolve()),
                "NEXUS_MNEMO_SERVER": str((ROOT.parent / "mnemo" / "server.py").resolve()),
                "NEXUS_THRIFT_SERVER": str((ROOT.parent / "thrift" / "server.py").resolve()),
                "NEXUS_GOVERNOR_SERVER": str((ROOT.parent / "agent-governor" / "src" / "agent_governor" / "mcp_server.py").resolve()),
                "AGENT_GOVERNOR_ROOT": str(root),
                "AGENT_GOVERNOR_STATE_DIR": str(state_root / "governor"),
                "AGENT_ROUTER_WORKSPACE_ROOT": str(root),
                "AGENT_ROUTER_STATE_DIR": str(state_root / "router"),
                "THRIFT_WORKSPACE_ROOT": str(root),
                "THRIFT_STATE_DIR": str(state_root / "thrift"),
                "MNEMO_WORKSPACE_ROOT": str(root),
            }
            buffer = io.StringIO()
            nexus_server._MODULE_CACHE.clear()
            with patch.dict(os.environ, env, clear=False), patch.object(sys, "stdout", buffer):
                calls = [
                    {"action": "governor.doctor", "params": {}},
                    {"action": "router.doctor", "params": {}},
                    {"action": "mnemo.doctor", "params": {}},
                    {"action": "thrift.classify_task", "params": {"text": "rename a variable"}},
                ]
                for payload in calls:
                    result = nexus_server.nexus_gateway(payload)
                    self.assertFalse(result["isError"], (payload["action"], result))
            self.assertEqual(buffer.getvalue(), "")
            nexus_server._MODULE_CACHE.clear()


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
        self.assertEqual(self._init_response["result"]["serverInfo"]["version"], "0.3.1")

    def test_tools_list_single_nexus_tool(self):
        tools = self._tools_response["result"]["tools"]
        self.assertEqual({item["name"] for item in tools}, {"nexus"})

    def test_tools_list_schema_valid(self):
        tools = self._tools_response["result"]["tools"]
        schema = tools[0]["inputSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("action", schema["required"])

    def test_tools_list_schema_contains_mnemo_memory_group_actions(self):
        tools = self._tools_response["result"]["tools"]
        schema_enum = set(tools[0]["inputSchema"]["properties"]["action"]["enum"])
        self.assertIn("mnemo.memory_group_discover", schema_enum)
        self.assertIn("mnemo.memory_group_preview", schema_enum)


if __name__ == "__main__":
    unittest.main()
