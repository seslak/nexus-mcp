#!/usr/bin/env python3
"""End-to-end smoke test for Nexus MCP gateway + active interaction middleware."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server.py"

_AGENTIC_ROOT = ROOT.parent / "agentic"
if not _AGENTIC_ROOT.exists():
    _AGENTIC_ROOT = ROOT.parents[2]


def _component_server(name: str, default_rel: str) -> str:
    env_key = f"NEXUS_{name.upper()}_SERVER"
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        return env_val
    return str(_AGENTIC_ROOT / "tools" / "mcp" / default_rel)


def rpc(proc: subprocess.Popen[str], request: dict) -> dict:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("nexus server closed stdout unexpectedly")
    return json.loads(line)


def call_nexus(proc: subprocess.Popen[str], req_id: int, action: str, params: dict | None = None) -> dict:
    return rpc(
        proc,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": "nexus",
                "arguments": {"action": action, "params": params or {}},
            },
        },
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        workspace_file = tmp_path / "inbox" / "iban.php"
        workspace_file.parent.mkdir(parents=True, exist_ok=True)
        workspace_file.write_text("<?php\nfunction validateIban($iban) { return true; }\n", encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["NEXUS_WORKSPACE_ROOT"] = tmp
        env["NEXUS_STATE_DIR"] = str(tmp_path / "state" / "nexus")
        env["NEXUS_ROUTER_SERVER"] = _component_server("router", "router/server.py")
        env["NEXUS_MNEMO_SERVER"] = _component_server("mnemo", "mnemo/server.py")
        env["NEXUS_THRIFT_SERVER"] = _component_server("thrift", "thrift/server.py")
        env["NEXUS_GOVERNOR_SERVER"] = _component_server(
            "governor", "agent-governor/src/agent_governor/mcp_server.py"
        )
        env["AGENT_ROUTER_STATE_DIR"] = str(tmp_path / "state" / "router")
        env["AGENT_ROUTER_WORKSPACE_ROOT"] = tmp
        env["MNEMO_STORE"] = "sqlite"
        env["MNEMO_SQLITE_FILE"] = str(tmp_path / "state" / "mnemo" / "mnemo.sqlite")
        env["MNEMO_FILE"] = str(tmp_path / "state" / "mnemo" / "memory.json")
        env["MNEMO_WORKSPACE_ROOT"] = tmp
        env["THRIFT_STORE"] = "sqlite"
        env["THRIFT_STATE_DIR"] = str(tmp_path / "state" / "thrift")
        env["THRIFT_SQLITE_FILE"] = str(tmp_path / "state" / "thrift" / "thrift.sqlite")
        env["THRIFT_WORKSPACE_ROOT"] = tmp
        env["THRIFT_ALLOW_EXTERNAL_ROOTS"] = "0"
        env["AGENT_GOVERNOR_ROOT"] = tmp
        env["AGENT_GOVERNOR_STATE_DIR"] = str(tmp_path / "state" / "governor")

        proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            init = rpc(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "nexus-smoke-test", "version": "1"},
                    },
                },
            )
            tools_resp = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            started = call_nexus(
                proc,
                3,
                "nexus.start_interaction",
                {
                    "task": "Update inbox/iban.php to reject BA and GB prefixes.",
                    "profile": "small_patch",
                    "metadata": {"source": "smoke"},
                },
            )
            thrift_call = call_nexus(
                proc,
                4,
                "thrift.file_window",
                {"path": str(workspace_file), "start_line": 1, "end_line": 20},
            )
            mnemo_search = call_nexus(proc, 5, "mnemo.search", {"query": "IBAN validation", "limit": 5})
            mnemo_record = call_nexus(
                proc,
                6,
                "mnemo.record",
                {"kind": "interaction_log", "text": "Validated IBAN logic for BA/GB prefixes."},
            )
            router_match = call_nexus(
                proc,
                7,
                "router.match_workflow",
                {
                    "name": "workflow.small-refactor",
                    "params": {
                        "task_summary": "Update inbox/iban.php to reject BA and GB prefixes.",
                        "target_files": ["inbox/iban.php"],
                        "runtime_available": False,
                    },
                },
            )
            router_validate = call_nexus(
                proc,
                8,
                "router.validate_workflow_params",
                {
                    "name": "workflow.small-refactor",
                    "params": {
                        "task_summary": "Update inbox/iban.php to reject BA and GB prefixes.",
                        "target_files": ["inbox/iban.php"],
                        "runtime_available": False,
                    },
                },
            )
            status_active = call_nexus(proc, 9, "nexus.status")
            gov_recent_events = call_nexus(proc, 10, "governor.recent_events", {"limit": 50})
            list_actions = call_nexus(proc, 11, "nexus.list_actions")
            memory_group_discover = call_nexus(
                proc,
                12,
                "mnemo.memory_group_discover",
                {"limit_groups": 10, "include_samples": True, "sample_per_group": 3},
            )
            pack_landing_list = call_nexus(proc, 13, "mnemo.pack_landing_list", {"limit": 10})
            finished = call_nexus(
                proc,
                14,
                "nexus.finish_interaction",
                {"status": "success", "result": "Completed BA/GB prefix rejection."},
            )
            status_after = call_nexus(proc, 15, "nexus.status")
            shutdown = rpc(proc, {"jsonrpc": "2.0", "id": 16, "method": "shutdown"})
        finally:
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe and not pipe.closed:
                    try:
                        pipe.close()
                    except OSError:
                        pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=5)

    assert init["result"]["serverInfo"]["name"] == "nexus"
    assert init["result"]["serverInfo"]["version"] == "0.3.1"
    assert {tool["name"] for tool in tools_resp["result"]["tools"]} == {"nexus"}
    schema_enum = set(tools_resp["result"]["tools"][0]["inputSchema"]["properties"]["action"]["enum"])
    assert "mnemo.memory_group_discover" in schema_enum
    assert "mnemo.memory_group_preview" in schema_enum
    assert "mnemo.pack_landing_list" in schema_enum

    assert list_actions["result"]["isError"] is False, list_actions
    listed_actions = set((list_actions["result"].get("structuredContent") or {}).get("actions", []))
    assert "mnemo.memory_group_discover" in listed_actions
    assert "mnemo.memory_group_preview" in listed_actions
    assert "mnemo.pack_landing_list" in listed_actions
    assert schema_enum == listed_actions, {"schema_only": sorted(schema_enum - listed_actions), "listed_only": sorted(listed_actions - schema_enum)}

    assert memory_group_discover["result"]["isError"] is False, memory_group_discover
    mg_sc = memory_group_discover["result"].get("structuredContent") or {}
    assert str(mg_sc.get("action", "")) == "memory_group_discover"
    assert pack_landing_list["result"]["isError"] is False, pack_landing_list
    pl_sc = pack_landing_list["result"].get("structuredContent") or {}
    assert str(pl_sc.get("action", "")) == "pack_landing_list"

    assert started["result"]["isError"] is False, started
    started_sc = started["result"]["structuredContent"]
    assert started_sc["run_id"], started_sc

    assert thrift_call["result"]["isError"] is False, thrift_call
    assert mnemo_search["result"]["isError"] is False, mnemo_search
    assert mnemo_record["result"]["isError"] is False, mnemo_record
    assert router_match["result"]["isError"] is False, router_match
    assert router_validate["result"]["isError"] is False, router_validate

    status_sc = status_active["result"]["structuredContent"]
    assert status_sc["active_interaction"] is not None, status_sc
    assert status_sc["active_interaction"]["active_run_id"] == started_sc["run_id"], status_sc

    recent_sc = gov_recent_events["result"]["structuredContent"]
    assert gov_recent_events["result"]["isError"] is False, gov_recent_events
    events = recent_sc.get("events", [])
    assert isinstance(events, list) and events, recent_sc
    tools = {str(item.get("tool_name", "")) for item in events if isinstance(item, dict)}
    expected_any = {"thrift.file_window", "mnemo.search", "mnemo.record", "router.match_workflow"}
    assert tools.intersection(expected_any), {"tools": sorted(tools), "events_count": len(events)}

    assert finished["result"]["isError"] is False, finished
    status_after_sc = status_after["result"]["structuredContent"]
    assert status_after_sc["active_interaction"] is None, status_after_sc

    assert shutdown["result"] == {}
    print("OK: nexus smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
