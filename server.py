#!/usr/bin/env python3
"""Nexus MCP: single-gateway facade over Mnemo, Thrift, Agent Governor, and Agent Router.

Transport: newline-delimited JSON-RPC on stdin/stdout.

Namespaced actions use '<namespace>.<subaction>'.
Nexus is the single visible MCP tool and delegates into backend gateways.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2025-06-18", "2025-03-26", "2024-11-05"}
SERVER_NAME = "nexus"
SERVER_TITLE = "Nexus MCP Gateway"
SERVER_VERSION = "0.3.1"
GATEWAY_TOOL_NAME = "nexus"

PACKAGE_ROOT = Path(__file__).resolve().parent

_SHOULD_EXIT = False

_FINISH_STATUS_CANONICAL = {"success", "failed", "stopped", "abandoned"}
_FINISH_STATUS_LEGACY_ALIASES = {
    "failure": "failed",
    "blocked": "stopped",
}
_AUTO_RECORD_NAMESPACES = {"thrift", "mnemo", "router"}
_AUTO_RECORD_SKIP_ACTIONS = {
    "thrift.cost_report",
    "thrift.economy_salience_check",
    "mnemo.doctor",
    "mnemo.salience_check",
    "router.doctor",
}
_LAST_THRIFT_MIRROR_HASH: str | None = None


# ---------------------------------------------------------------------------
# Namespace and action catalogue
# ---------------------------------------------------------------------------

_NAMESPACE_ACTIONS: dict[str, list[str]] = {
    "nexus": sorted(
        [
            "doctor",
            "finish_interaction",
            "help",
            "list_actions",
            "list_namespaces",
            "reset_interaction",
            "start_interaction",
            "status",
        ]
    ),
    "router": sorted(
        [
            "classify",
            "doctor",
            "explain",
            "get_workflow",
            "list_models",
            "list_specialists",
            "list_workflows",
            "log_decision",
            "log_outcome",
            "match_workflow",
            "recent_decisions",
            "reload_registries",
            "route",
            "suggest_workflow",
            "validate_decision",
            "validate_registries",
            "validate_workflow_params",
        ]
    ),
    "governor": sorted(
        [
            "check_budget",
            "doctor",
            "finish_run",
            "get_event",
            "get_run",
            "list_profiles",
            "maintenance",
            "patch_check",
            "recent_events",
            "recent_runs",
            "record_event",
            "record_test",
            "record_tool_call",
            "reset_run",
            "search_events",
            "search_runs",
            "start_run",
            "stats",
            "status",
            "sync_thrift",
            "version",
        ]
    ),
    "thrift": sorted(
        [
            "classify_task",
            "compress_log",
            "cost_report",
            "count_tokens",
            "economy_salience_check",
            "file_window",
            "find_files",
            "grep_text",
            "plan_context",
            "rank_files",
            "workspace_info",
        ]
    ),
    "mnemo": sorted(
        [
            "alias_hint",
            "backfill_signatures",
            "compact_context",
            "consolidate_full",
            "delete",
            "doctor",
            "export",
            "get",
            "get_event",
            "inspect",
            "link",
            "lookup_symbol",
            "maintenance",
            "memory_events",
            "memory_group_discover",
            "memory_group_preview",
            "pack_landing_list",
            "pack_export",
            "pack_import",
            "pack_inspect",
            "pack_list_imports",
            "pack_preview",
            "pack_promote",
            "pack_promote_preview",
            "pack_redaction_preview",
            "pack_review_import",
            "recent",
            "recent_events",
            "record",
            "recall",
            "salience_check",
            "search",
            "search_events",
            "signer_add",
            "signer_disable",
            "signer_enable",
            "signer_list",
            "topic_add",
            "topic_list",
            "topic_remove",
            "update",
        ]
    ),
}

NEXUS_ACTIONS: list[str] = sorted(
    f"{ns}.{action}"
    for ns, actions in _NAMESPACE_ACTIONS.items()
    for action in actions
)


def _public_action_enum() -> list[str]:
    """Single source for the public Nexus MCP action enum."""
    return list(NEXUS_ACTIONS)


def _build_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": GATEWAY_TOOL_NAME,
            "title": SERVER_TITLE,
            "description": (
                "Nexus MCP: single gateway over Mnemo, Thrift, Agent Governor, and Agent Router. "
                "Use action in 'namespace.subaction' format with optional params. "
                "Use nexus.start_interaction / nexus.status / nexus.finish_interaction for active-run middleware recording."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": _public_action_enum(),
                        "description": (
                            "Required action in 'namespace.subaction' format. "
                            "nexus.start_interaction starts governor run + middleware state; "
                            "nexus.status reports active interaction; "
                            "nexus.finish_interaction finishes active run."
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": (
                            "Optional action parameters. Pass the same params expected by the "
                            "underlying namespace action."
                        ),
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    ]


# ---------------------------------------------------------------------------
# Component server path resolution
# ---------------------------------------------------------------------------


def _workspace_root() -> Path:
    env = os.environ.get("NEXUS_WORKSPACE_ROOT", "").strip()
    if env:
        return Path(env)
    return Path.cwd()


def _state_dir() -> Path:
    env = os.environ.get("NEXUS_STATE_DIR", "").strip()
    if env:
        return Path(env)
    return _workspace_root() / "state" / "nexus"


def _state_file() -> Path:
    return _state_dir() / "nexus_state.json"


def _mcp_sibling_dir() -> Path:
    """Parent of nexus/ — contains router/, mnemo/, thrift/, agent-governor/."""
    return PACKAGE_ROOT.parent


def _component_path(env_var: str, default_relative: str) -> Path:
    env = os.environ.get(env_var, "").strip()
    if env:
        return Path(env)
    return _mcp_sibling_dir() / default_relative


def _router_server_path() -> Path:
    return _component_path("NEXUS_ROUTER_SERVER", "router/server.py")


def _mnemo_server_path() -> Path:
    return _component_path("NEXUS_MNEMO_SERVER", "mnemo/server.py")


def _thrift_server_path() -> Path:
    return _component_path("NEXUS_THRIFT_SERVER", "thrift/server.py")


def _governor_server_path() -> Path:
    return _component_path(
        "NEXUS_GOVERNOR_SERVER",
        "agent-governor/src/agent_governor/mcp_server.py",
    )


# ---------------------------------------------------------------------------
# In-process module loading via importlib
# ---------------------------------------------------------------------------

_MODULE_CACHE: dict[str, Any] = {}


def _load_module(cache_key: str, server_path: Path) -> Any:
    """Load a server module via importlib, caching on cache_key."""
    if cache_key in _MODULE_CACHE:
        return _MODULE_CACHE[cache_key]

    server_dir = str(server_path.parent.resolve())
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)

    spec = importlib.util.spec_from_file_location(cache_key, str(server_path))
    if spec is None or spec.loader is None:
        raise ImportError("Cannot create module spec for: {0}".format(server_path))

    mod = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(cache_key, None)
        raise

    _MODULE_CACHE[cache_key] = mod
    return mod


# ---------------------------------------------------------------------------
# Component adapters
# ---------------------------------------------------------------------------


def _call_router(action: str, params: dict[str, Any]) -> dict[str, Any]:
    mod = _load_module("nexus_component_router", _router_server_path())
    return mod.router_gateway({"action": action, "params": params})  # type: ignore[return-value]


def _call_mnemo(action: str, params: dict[str, Any]) -> dict[str, Any]:
    mod = _load_module("nexus_component_mnemo", _mnemo_server_path())
    return mod.mnemo_gateway({"action": action, "params": params})  # type: ignore[return-value]


def _call_thrift(action: str, params: dict[str, Any]) -> dict[str, Any]:
    global _LAST_THRIFT_MIRROR_HASH
    mod = _load_module("nexus_component_thrift", _thrift_server_path())
    _LAST_THRIFT_MIRROR_HASH = None

    # Mirror telemetry manually because Nexus calls Thrift via thrift_gateway(...)
    # directly and bypasses Thrift's JSON-RPC tools/call dispatcher path.
    # Without this, calls routed through Nexus may never be appended to
    # state/thrift/thrift.sqlite economy telemetry.
    resolved_action, resolved_params, result = mod.thrift_gateway({"action": action, "params": params})
    try:
        # Forward active Nexus run id only into mirrored telemetry args so Thrift's
        # event correlation can tie this call to the current interaction run.
        # Do not inject run_id into the original call params passed to Thrift.
        active_run_id = ""
        try:
            active_run_id = str(_load_nexus_state().get("active_run_id") or "").strip()
        except Exception:
            active_run_id = ""

        # Mirror args must be isolated from resolved/original params to avoid
        # mutating request data just for telemetry enrichment.
        if isinstance(resolved_params, dict):
            mirror_args = dict(resolved_params)
        else:
            mirror_args = {}
        if active_run_id and not str(mirror_args.get("run_id", "") or "").strip():
            mirror_args["run_id"] = active_run_id

        est_tokens, details = mod.tool_log_metadata(resolved_action, mirror_args, result)
        mirrored = mod.append_economy_log(resolved_action, mirror_args, est_tokens, details)
        if isinstance(mirrored, dict):
            content_hash = str(mirrored.get("content_hash", "")).strip()
            _LAST_THRIFT_MIRROR_HASH = content_hash or None
    except Exception as exc:
        _LAST_THRIFT_MIRROR_HASH = None
        # Telemetry mirror failures must never break tool behavior; return the
        # original Thrift result and emit only a compact warning to stderr.
        print(
            "[nexus] thrift telemetry mirror failed for action={0}: {1}".format(resolved_action, exc),
            file=sys.stderr,
        )
        sys.stderr.flush()
    return result  # type: ignore[return-value]


def _call_governor(action: str, params: dict[str, Any]) -> dict[str, Any]:
    mod = _load_module("nexus_component_governor", _governor_server_path())
    return mod.handle_tool_call("governor", {"action": action, "params": params})  # type: ignore[return-value]


def _router_unknown_action(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if not bool(result.get("isError")):
        return False
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and str(structured.get("error", "")) == "unknown_action":
        return True
    text = ""
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            text = str(first.get("text", ""))
    return "Unknown router action" in text


def _delegate_router(subaction: str, params: dict[str, Any]) -> dict[str, Any]:
    if subaction == "match_workflow":
        direct = _call_router(subaction, params)
        if not _router_unknown_action(direct):
            return direct
        routed_params = dict(params)
        task = str(routed_params.get("task", "")).strip()
        if not task:
            wf_name = (
                str(routed_params.get("workflow", "")).strip()
                or str(routed_params.get("name", "")).strip()
                or str(routed_params.get("workflow_id", "")).strip()
                or str(routed_params.get("id", "")).strip()
                or str(routed_params.get("query", "")).strip()
            )
            routed_params["task"] = "Match workflow {0}".format(wf_name or "for current task")
        routed = _call_router("suggest_workflow", routed_params)
        if isinstance(routed, dict):
            structured = routed.get("structuredContent")
            if isinstance(structured, dict):
                structured.setdefault("nexus_alias", "router.match_workflow -> router.suggest_workflow")
        return routed

    if subaction == "get_workflow":
        direct = _call_router(subaction, params)
        if not _router_unknown_action(direct):
            return direct
        listed = _call_router("list_workflows", {})
        if not isinstance(listed, dict) or bool(listed.get("isError")):
            return listed
        structured = listed.get("structuredContent")
        if not isinstance(structured, dict):
            return listed
        workflows = structured.get("workflows")
        if not isinstance(workflows, list):
            return listed
        token = (
            str(params.get("workflow", "")).strip()
            or str(params.get("name", "")).strip()
            or str(params.get("workflow_id", "")).strip()
            or str(params.get("id", "")).strip()
        )
        if not token:
            return _text_result(
                "Returned workflow list (no specific id/name requested).",
                {"workflows": workflows, "count": len(workflows), "nexus_alias": "router.get_workflow -> router.list_workflows"},
            )
        token_lower = token.lower()
        matched = []
        for item in workflows:
            if not isinstance(item, dict):
                continue
            candidates = [
                str(item.get("id", "")).strip(),
                str(item.get("name", "")).strip(),
                str(item.get("workflow", "")).strip(),
                str(item.get("workflow_id", "")).strip(),
            ]
            if any(candidate and token_lower == candidate.lower() for candidate in candidates):
                matched.append(item)
        if not matched:
            return _error_result(
                "workflow_not_found",
                "No workflow matched '{0}'.".format(token),
                {"query": token, "count": 0, "nexus_alias": "router.get_workflow -> router.list_workflows"},
            )
        return _text_result(
            "Found {0} workflow(s) matching '{1}'.".format(len(matched), token),
            {"query": token, "workflows": matched, "count": len(matched), "nexus_alias": "router.get_workflow -> router.list_workflows"},
        )

    return _call_router(subaction, params)


# ---------------------------------------------------------------------------
# Nexus state
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_nexus_state() -> dict[str, Any]:
    return {
        "active_run_id": None,
        "task": None,
        "profile": None,
        "metadata": {},
        "started_at": None,
        "last_action_at": None,
        "middleware_event_count": 0,
    }


def _normalize_state(raw: Any) -> dict[str, Any]:
    def _opt_text(value: Any) -> str | None:
        if value is None:
            return None
        text = value.strip() if isinstance(value, str) else str(value).strip()
        if not text:
            return None
        if text.lower() == "none":
            return None
        return text

    state = _empty_nexus_state()
    if not isinstance(raw, dict):
        return state
    state["active_run_id"] = _opt_text(raw.get("active_run_id"))
    state["task"] = _opt_text(raw.get("task"))
    state["profile"] = _opt_text(raw.get("profile"))
    metadata = raw.get("metadata")
    state["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
    state["started_at"] = _opt_text(raw.get("started_at"))
    state["last_action_at"] = _opt_text(raw.get("last_action_at"))
    try:
        count = int(raw.get("middleware_event_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    state["middleware_event_count"] = max(0, count)
    return state


def _load_nexus_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return _empty_nexus_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_nexus_state()
    return _normalize_state(raw)


def _save_nexus_state(state: dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_state(state)
    tmp_path = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    tmp_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)


def _clear_active_interaction(state: dict[str, Any]) -> dict[str, Any]:
    state = _normalize_state(state)
    state["active_run_id"] = None
    state["task"] = None
    state["profile"] = None
    state["metadata"] = {}
    state["started_at"] = None
    state["last_action_at"] = None
    state["middleware_event_count"] = 0
    return state


def _interaction_is_active(state: dict[str, Any]) -> bool:
    value = state.get("active_run_id")
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


def _text_result(text: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }
    if structured is not None:
        result["structuredContent"] = structured
    return result


def _error_result(
    error: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    structured: dict[str, Any] = {"error": error, "message": message}
    if details:
        structured.update(details)
    return {
        "content": [{"type": "text", "text": "Error: {0}".format(message)}],
        "isError": True,
        "structuredContent": structured,
    }


def _structured_content(result: dict[str, Any]) -> dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    return {}


def _result_error_text(result: dict[str, Any]) -> str:
    structured = _structured_content(result)
    message = str(structured.get("message", "")).strip()
    if message:
        return message
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            text = str(first.get("text", "")).strip()
            if text:
                return text
    return "unknown error"


def _append_nexus_warning(result: dict[str, Any], warning: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        return result
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        structured = {}
        result["structuredContent"] = structured
    warnings = structured.get("nexus_warnings")
    if isinstance(warnings, list):
        out = [str(item) for item in warnings]
    else:
        out = []
    out.append(str(warning))
    structured["nexus_warnings"] = out
    return result


def _json_compact(value: Any, max_chars: int = 900) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception:
        text = str(value)
    if len(text) <= max_chars:
        return text
    return "{0}...(truncated)".format(text[: max(0, max_chars - 14)])


# ---------------------------------------------------------------------------
# Middleware: active-run auto-record
# ---------------------------------------------------------------------------


def _extract_target_info(namespace: str, action: str, params: dict[str, Any], result: dict[str, Any]) -> dict[str, str]:
    del result
    target = ""
    path = ""
    query_text = ""
    symbol = ""

    if namespace == "thrift":
        if action == "file_window":
            path = str(params.get("path", "")).strip()
            symbol = str(params.get("symbol", "")).strip()
            start_line = params.get("start_line")
            end_line = params.get("end_line")
            if symbol:
                target = "{0}::{1}".format(path, symbol) if path else symbol
            elif start_line is not None or end_line is not None:
                target = "{0}:{1}-{2}".format(path, start_line or "", end_line or "")
            else:
                target = path
        elif action == "grep_text":
            query_text = str(params.get("query", "")).strip()
            globs = params.get("include_globs")
            if isinstance(globs, list) and globs:
                target = "{0} in {1}".format(query_text, ",".join(str(item) for item in globs))
            else:
                target = query_text
        elif action == "find_files":
            query_text = str(params.get("pattern", "")).strip() or str(params.get("query", "")).strip()
            target = query_text
        elif action == "rank_files":
            query_text = str(params.get("task", "")).strip()
            target = query_text

    elif namespace == "mnemo":
        if action == "search":
            query_text = str(params.get("query", "")).strip()
            target = query_text
        elif action == "recall":
            query_text = str(params.get("query", "")).strip() or str(params.get("task", "")).strip()
            mode = str(params.get("mode", "")).strip()
            target = "mode={0} {1}".format(mode or "auto", query_text).strip()
        elif action == "record":
            kind = str(params.get("kind", "")).strip()
            summary = str(params.get("summary", "")).strip() or str(params.get("text", "")).strip()
            if summary:
                summary = summary[:160]
            target = "{0}: {1}".format(kind or "note", summary) if summary else (kind or "record")

    elif namespace == "router":
        if action in {"match_workflow", "get_workflow"}:
            target = (
                str(params.get("workflow", "")).strip()
                or str(params.get("name", "")).strip()
                or str(params.get("workflow_id", "")).strip()
                or str(params.get("id", "")).strip()
            )
            if not target:
                target = str(params.get("task", "")).strip() or str(params.get("query", "")).strip()
        elif action == "route":
            query_text = str(params.get("task", "")).strip()
            target = query_text

    if not target:
        target = (
            str(params.get("path", "")).strip()
            or str(params.get("target", "")).strip()
            or str(params.get("query", "")).strip()
            or str(params.get("task", "")).strip()
        )

    return {
        "target": target,
        "path": path,
        "query_text": query_text,
        "symbol": symbol,
    }


def _result_summary(namespace: str, action: str, result: dict[str, Any]) -> str:
    if bool(result.get("isError")):
        return "error: {0}".format(_result_error_text(result))
    structured = _structured_content(result)
    if namespace == "mnemo" and action == "search":
        matches = structured.get("matches")
        if isinstance(matches, list):
            return "mnemo.search matched {0} item(s)".format(len(matches))
    if namespace == "mnemo" and action == "record":
        memory = structured.get("memory")
        if isinstance(memory, dict):
            return "mnemo.record stored {0}".format(str(memory.get("id", "")).strip() or "memory")
    if namespace == "router" and action in {"route", "match_workflow"}:
        route_type = str(structured.get("routeType", "")).strip()
        task_class = str(structured.get("taskClass", "")).strip()
        if route_type or task_class:
            return "router route={0} class={1}".format(route_type or "n/a", task_class or "n/a")
    if namespace == "thrift" and action == "file_window":
        start_line = structured.get("start_line")
        end_line = structured.get("end_line")
        if start_line is not None and end_line is not None:
            return "thrift.file_window returned lines {0}-{1}".format(start_line, end_line)
    keys = sorted(structured.keys())
    if keys:
        return "ok ({0})".format(",".join(keys[:6]))
    return "ok"


def _extract_est_tokens(result: dict[str, Any]) -> int:
    structured = _structured_content(result)
    for key in ("est_tokens", "token_count", "tokens", "estimated_tokens"):
        raw = structured.get(key)
        try:
            if raw is None:
                continue
            value = int(raw)
            return max(0, value)
        except (TypeError, ValueError):
            continue
    return 0


def _extract_result_size(result: dict[str, Any]) -> int:
    return len(_json_compact(result, max_chars=10000).encode("utf-8"))


def _should_auto_record(full_action: str, namespace: str, state: dict[str, Any]) -> bool:
    if full_action in _AUTO_RECORD_SKIP_ACTIONS:
        return False
    if namespace not in _AUTO_RECORD_NAMESPACES:
        return False
    if not _interaction_is_active(state):
        return False
    return True


def _auto_record_to_governor(
    namespace: str,
    subaction: str,
    params: dict[str, Any],
    result: dict[str, Any],
    duration_ms: int,
    state: dict[str, Any],
) -> str | None:
    global _LAST_THRIFT_MIRROR_HASH
    info = _extract_target_info(namespace, subaction, params, result)
    success = not bool(result.get("isError"))
    params_summary = _json_compact(params, max_chars=480)
    result_summary = _result_summary(namespace, subaction, result)
    error_text = "" if success else _result_error_text(result)
    est_tokens = _extract_est_tokens(result)
    result_size = _extract_result_size(result)
    salience_text = "{0}.{1} {2}".format(namespace, subaction, result_summary)
    detail_payload = {
        "namespace": namespace,
        "action": subaction,
        "tool_name": "{0}.{1}".format(namespace, subaction),
        "event_type": "tool_call",
        "target": info["target"],
        "path": info["path"],
        "symbol": info["symbol"],
        "query_text": info["query_text"],
        "params_summary": params_summary,
        "result_summary": result_summary,
        "success": success,
        "duration_ms": duration_ms,
        "est_tokens": est_tokens,
        "result_size": result_size,
        "error_message": error_text,
        "salience_text": salience_text,
        "include_in_salience": namespace in {"thrift", "mnemo"},
        "run_id": state.get("active_run_id"),
    }
    target = info["target"] or info["path"] or info["query_text"] or "{0}.{1}".format(namespace, subaction)
    record_params = {
        "tool": "{0}.{1}".format(namespace, subaction),
        "target": target,
        "success": success,
        "tokens": est_tokens,
        "detail": _json_compact(detail_payload, max_chars=1200),
        "run_id": state.get("active_run_id"),
    }
    if namespace == "thrift" and _LAST_THRIFT_MIRROR_HASH:
        record_params["input_hash"] = _LAST_THRIFT_MIRROR_HASH
    try:
        governor_result = _call_governor("record_tool_call", record_params)
    except Exception as exc:
        if namespace == "thrift":
            _LAST_THRIFT_MIRROR_HASH = None
        return "Nexus middleware failed to auto-record {0}.{1}: {2}".format(namespace, subaction, exc)
    if not isinstance(governor_result, dict):
        if namespace == "thrift":
            _LAST_THRIFT_MIRROR_HASH = None
        return "Nexus middleware failed to auto-record {0}.{1}: invalid governor response.".format(namespace, subaction)
    if bool(governor_result.get("isError")):
        if namespace == "thrift":
            _LAST_THRIFT_MIRROR_HASH = None
        return "Nexus middleware failed to auto-record {0}.{1}: {2}".format(
            namespace,
            subaction,
            _result_error_text(governor_result),
        )
    state["middleware_event_count"] = int(state.get("middleware_event_count", 0) or 0) + 1
    state["last_action_at"] = _utc_now_iso()
    if namespace == "thrift":
        _LAST_THRIFT_MIRROR_HASH = None
    return None


# ---------------------------------------------------------------------------
# Nexus self-actions
# ---------------------------------------------------------------------------


def _require_string(params: dict[str, Any], field: str) -> str:
    value = params.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Field '{0}' is required and must be a non-empty string.".format(field))
    return value.strip()


def _optional_string(params: dict[str, Any], field: str, default: str = "") -> str:
    value = params.get(field)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError("Field '{0}' must be a string.".format(field))
    return value.strip()


def _handle_list_namespaces(params: dict[str, Any]) -> dict[str, Any]:
    del params
    ns_info = {
        ns: {"actions": actions, "count": len(actions)}
        for ns, actions in _NAMESPACE_ACTIONS.items()
    }
    structured = {
        "namespaces": ns_info,
        "total_namespaces": len(_NAMESPACE_ACTIONS),
        "total_actions": len(NEXUS_ACTIONS),
        "actions": NEXUS_ACTIONS,
    }
    lines = ["Nexus namespaces ({0} total, {1} actions):".format(len(_NAMESPACE_ACTIONS), len(NEXUS_ACTIONS))]
    for ns, actions in _NAMESPACE_ACTIONS.items():
        lines.append("  {0}: {1}".format(ns, ", ".join(actions)))
    return _text_result("\n".join(lines), structured)


def _handle_help(params: dict[str, Any]) -> dict[str, Any]:
    del params
    structured = {
        "version": SERVER_VERSION,
        "examples": [
            {"action": "nexus.doctor", "params": {}},
            {"action": "nexus.start_interaction", "params": {"task": "Update README wording.", "profile": "small_patch"}},
            {
                "action": "router.match_workflow",
                "params": {
                    "name": "workflow.small-refactor",
                    "params": {"task_summary": "Update README wording.", "target_files": ["README.md"]},
                },
            },
            {
                "action": "router.validate_workflow_params",
                "params": {
                    "name": "workflow.small-refactor",
                    "params": {"task_summary": "Update README wording.", "target_files": ["README.md"]},
                },
            },
            {"action": "thrift.file_window", "params": {"path": "inbox/README.md", "start_line": 1, "end_line": 80}},
            {"action": "mnemo.record", "params": {"kind": "interaction_log", "text": "Updated README wording."}},
            {"action": "nexus.finish_interaction", "params": {"status": "success", "result": "Completed README update."}},
        ],
    }
    lines = [
        "Nexus MCP v{0}".format(SERVER_VERSION),
        "Use one gateway tool named 'nexus' with namespaced actions.",
        "Interaction flow: nexus.start_interaction -> backend actions -> nexus.finish_interaction.",
        "Use nexus.status to inspect active interaction and middleware counters.",
    ]
    return _text_result("\n".join(lines), structured)


def _component_status() -> dict[str, Any]:
    components: dict[str, Any] = {}
    for ns, path_fn, cache_key in [
        ("router", _router_server_path, "nexus_component_router"),
        ("mnemo", _mnemo_server_path, "nexus_component_mnemo"),
        ("thrift", _thrift_server_path, "nexus_component_thrift"),
        ("governor", _governor_server_path, "nexus_component_governor"),
    ]:
        server_path = path_fn()
        components[ns] = {
            "server_path": str(server_path),
            "server_exists": server_path.exists(),
            "loaded": cache_key in _MODULE_CACHE,
        }
    return components


def _component_root_snapshot() -> dict[str, dict[str, str | None]]:
    configured_thrift = os.environ.get("THRIFT_WORKSPACE_ROOT", "").strip()
    configured_governor = os.environ.get("AGENT_GOVERNOR_ROOT", "").strip()
    configured_router = os.environ.get("AGENT_ROUTER_WORKSPACE_ROOT", "").strip()
    return {
        "nexus": {
            "configured": os.environ.get("NEXUS_WORKSPACE_ROOT", "").strip() or None,
            "effective": str(_workspace_root().resolve()),
        },
        "thrift": {
            "configured": configured_thrift or None,
            "effective": str(Path(configured_thrift).resolve()) if configured_thrift else str(Path.cwd().resolve()),
        },
        "governor": {
            "configured": configured_governor or None,
            "effective": str(Path(configured_governor).resolve()) if configured_governor else str(Path.cwd().resolve()),
        },
        "router": {
            "configured": configured_router or None,
            "effective": str(Path(configured_router).resolve()) if configured_router else str(Path.cwd().resolve()),
        },
    }


def _root_consistency_warnings(roots: dict[str, dict[str, str | None]]) -> list[str]:
    warnings: list[str] = []
    nexus_configured = roots.get("nexus", {}).get("configured")
    nexus_effective = roots.get("nexus", {}).get("effective")
    if not nexus_effective:
        return warnings
    for name in ("thrift", "governor", "router"):
        entry = roots.get(name, {})
        configured = entry.get("configured")
        effective = entry.get("effective")
        if nexus_configured and not configured:
            warnings.append("{0} workspace root is unset while NEXUS_WORKSPACE_ROOT is set.".format(name))
        if effective and effective != nexus_effective:
            warnings.append("{0} workspace root mismatch: {1}".format(name, effective))
    return warnings


def _duplicate_top_level_module_names() -> list[str]:
    names: list[str] = []
    ignored = {"__init__.py", "server.py", "mcp_server.py", "smoke_test.py", "test_server.py", "salience_loader.py"}
    for path_fn in (_router_server_path, _mnemo_server_path, _thrift_server_path, _governor_server_path):
        directory = path_fn().resolve().parent
        if not directory.exists():
            continue
        for file_path in directory.glob("*.py"):
            if file_path.name in ignored:
                continue
            names.append(file_path.name)
    counts = Counter(names)
    return sorted(name for name, count in counts.items() if count > 1)


def _handle_status(params: dict[str, Any]) -> dict[str, Any]:
    del params
    components = _component_status()
    workspace = _workspace_root()
    missing = [ns for ns, info in components.items() if not info["server_exists"]]
    state = _load_nexus_state()
    roots = _component_root_snapshot()
    warnings = [f"Missing server file for: {ns}" for ns in missing]
    warnings.extend(_root_consistency_warnings(roots))
    duplicate_module_names = _duplicate_top_level_module_names()
    if duplicate_module_names:
        warnings.append("Duplicate top-level module names detected: {0}".format(", ".join(duplicate_module_names)))
    governor_status: dict[str, Any] | None = None

    if _interaction_is_active(state):
        try:
            governor_result = _call_governor("status", {"run_id": state.get("active_run_id"), "record_check": False})
            if isinstance(governor_result, dict) and not bool(governor_result.get("isError")):
                governor_status = _structured_content(governor_result)
            else:
                warnings.append("Governor status call failed while checking active interaction.")
        except Exception as exc:
            warnings.append("Governor status call failed while checking active interaction: {0}".format(exc))

    active = None
    if _interaction_is_active(state):
        active = {
            "active_run_id": state.get("active_run_id"),
            "task": state.get("task"),
            "profile": state.get("profile"),
            "metadata": state.get("metadata", {}),
            "started_at": state.get("started_at"),
            "last_action_at": state.get("last_action_at"),
            "middleware_event_count": int(state.get("middleware_event_count", 0) or 0),
        }

    structured = {
        "version": SERVER_VERSION,
        "workspace_root": str(workspace),
        "state_dir": str(_state_dir()),
        "state_file": str(_state_file()),
        "package_path": str(PACKAGE_ROOT),
        "namespaces": list(_NAMESPACE_ACTIONS.keys()),
        "total_actions": len(NEXUS_ACTIONS),
        "components": components,
        "roots": roots,
        "active_interaction": active,
        "middleware": {
            "active": _interaction_is_active(state),
            "middleware_event_count": int(state.get("middleware_event_count", 0) or 0),
            "last_action_at": state.get("last_action_at"),
        },
        "duplicate_module_names": duplicate_module_names,
        "governor_status": governor_status,
        "warnings": warnings,
    }

    lines = ["Nexus MCP v{0}".format(SERVER_VERSION)]
    lines.append("Workspace: {0}".format(workspace))
    lines.append("Namespaces: {0}".format(", ".join(_NAMESPACE_ACTIONS.keys())))
    lines.append("Total actions: {0}".format(len(NEXUS_ACTIONS)))
    if active:
        lines.append("Active run: {0} ({1})".format(active["active_run_id"], active.get("profile") or ""))
        lines.append("Middleware recorded events: {0}".format(active.get("middleware_event_count", 0)))
    else:
        lines.append("Active run: none")
    if missing:
        for ns in missing:
            lines.append("WARNING: server file missing for namespace '{0}'".format(ns))
    else:
        lines.append("All component server files found.")

    return _text_result("\n".join(lines), structured)


def _handle_start_interaction(params: dict[str, Any]) -> dict[str, Any]:
    state = _load_nexus_state()
    if _interaction_is_active(state):
        return _error_result(
            "active_interaction_exists",
            "An interaction is already active. Finish it first.",
            {
                "active_run_id": state.get("active_run_id"),
                "task": state.get("task"),
                "profile": state.get("profile"),
            },
        )
    try:
        task = _require_string(params, "task")
        profile = _optional_string(params, "profile", default="general_work") or "general_work"
    except ValueError as exc:
        return _error_result("invalid_arguments", str(exc))
    metadata = params.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        return _error_result("invalid_arguments", "Field 'metadata' must be an object when provided.")

    try:
        governor_result = _call_governor("start_run", {"task": task, "profile": profile})
    except Exception as exc:
        return _error_result("component_error", "Governor start_run failed: {0}".format(exc))

    if not isinstance(governor_result, dict):
        return _error_result("component_error", "Governor start_run returned invalid response.")
    if bool(governor_result.get("isError")):
        return governor_result

    governor_payload = _structured_content(governor_result)
    run_id = str(governor_payload.get("run_id", "")).strip()
    if not run_id:
        return _error_result("component_error", "Governor start_run did not return a run_id.")
    started_at = (
        str((governor_payload.get("run") or {}).get("started_at", "")).strip()
        if isinstance(governor_payload.get("run"), dict)
        else ""
    ) or _utc_now_iso()

    new_state = _empty_nexus_state()
    new_state["active_run_id"] = run_id
    new_state["task"] = task
    new_state["profile"] = profile
    new_state["metadata"] = dict(metadata)
    new_state["started_at"] = started_at
    new_state["last_action_at"] = started_at
    new_state["middleware_event_count"] = 0
    _save_nexus_state(new_state)

    payload = {
        "run_id": run_id,
        "task": task,
        "profile": profile,
        "metadata": dict(metadata),
        "started_at": started_at,
        "middleware_event_count": 0,
        "governor": governor_payload,
    }
    return _text_result(
        "Started interaction run {0} ({1}).".format(run_id, profile),
        payload,
    )


def _parse_bool_param(params: dict[str, Any], field: str, default: bool) -> bool:
    value = params.get(field)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "y", "on"}:
            return True
        if token in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError("Field '{0}' must be a boolean.".format(field))


def _auto_memory_default_enabled() -> bool:
    token = os.environ.get("NEXUS_AUTO_MEMORY", "1").strip().lower()
    return token not in {"0", "false", "no", "n", "off"}


def _normalize_finish_status_token(raw_status: str) -> str | None:
    token = str(raw_status or "").strip().lower()
    if token in _FINISH_STATUS_CANONICAL:
        return token
    return _FINISH_STATUS_LEGACY_ALIASES.get(token)


def _build_interaction_summary(status: str, task: str, result: str, event_count: int) -> str:
    head = "[{0}] {1}".format(status, task).strip()
    if not task:
        head = "[{0}] interaction".format(status)
    tail = " — {0}".format(result) if result else ""
    return "{0}{1} ({2} events)".format(head, tail, event_count)[:1000]


def _handle_finish_interaction(params: dict[str, Any]) -> dict[str, Any]:
    state = _load_nexus_state()
    if not _interaction_is_active(state):
        return _error_result("no_active_interaction", "No active interaction to finish.")

    try:
        raw_status = _require_string(params, "status")
        record_memory = _parse_bool_param(params, "record_memory", _auto_memory_default_enabled())
    except ValueError as exc:
        return _error_result("invalid_arguments", str(exc))
    normalized_status = _normalize_finish_status_token(raw_status)
    if normalized_status is None:
        return _error_result(
            "invalid_arguments",
            "Field 'status' must be one of: {0}. Legacy aliases accepted: failure->failed, blocked->stopped.".format(
                ", ".join(sorted(_FINISH_STATUS_CANONICAL))
            ),
        )
    status = normalized_status
    result_summary = _optional_string(params, "result", default="")

    task = str(state.get("task") or "")
    profile = str(state.get("profile") or "")
    started_at = str(state.get("started_at") or "")
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    event_count = int(state.get("middleware_event_count", 0) or 0)
    agent_id = str(metadata.get("agent_id", "")).strip() if isinstance(metadata, dict) else ""

    finish_params: dict[str, Any] = {"status": status, "run_id": state.get("active_run_id")}
    if result_summary:
        finish_params["final_summary"] = result_summary
    nexus_warnings: list[str] = []
    auto_memory: dict[str, Any] = {"attempted": False, "recorded": False, "enabled": record_memory}
    try:
        governor_result = _call_governor("finish_run", finish_params)
    except Exception as exc:
        return _error_result("component_error", "Governor finish_run failed: {0}".format(exc))

    if not isinstance(governor_result, dict):
        return _error_result("component_error", "Governor finish_run returned invalid response.")
    if bool(governor_result.get("isError")):
        structured = _structured_content(governor_result)
        code = str(structured.get("error", "")).strip()
        if code in {"no_current_run", "run_not_found", "run_not_active"}:
            cleared = _clear_active_interaction(state)
            _save_nexus_state(cleared)
            nexus_warnings.append("governor run was already closed ({0}); nexus interaction state cleared".format(code))
            payload = {
                "finished": True,
                "status": status,
                "run_id": state.get("active_run_id"),
                "governor": structured,
                "auto_memory": auto_memory,
                "nexus_warnings": nexus_warnings,
            }
            return _text_result(
                "Finished interaction run {0} with status '{1}'.".format(payload["run_id"], status),
                payload,
            )
        return governor_result

    governor_payload = _structured_content(governor_result)
    run_id = str(governor_payload.get("run_id") or state.get("active_run_id") or "").strip()

    if record_memory and run_id:
        memory_params: dict[str, Any] = {
            "kind": "interaction_log",
            "summary": _build_interaction_summary(status, task, result_summary, event_count),
            "role": "coordinator",
            "source_run_id": run_id,
            "metadata": {
                "profile": profile,
                "status": status,
                "started_at": started_at,
                "event_count": event_count,
                "result": result_summary,
            },
        }
        if agent_id:
            memory_params["agent_id"] = agent_id
        try:
            auto_memory["attempted"] = True
            mnemo_result = _call_mnemo("record", memory_params)
            auto_memory["mnemo"] = _structured_content(mnemo_result)
            if bool(mnemo_result.get("isError")):
                nexus_warnings.append("auto_memory_record failed: {0}".format(_result_error_text(mnemo_result)))
            else:
                auto_memory["recorded"] = True
        except Exception as exc:
            nexus_warnings.append("auto_memory_record failed: {0}: {1}".format(type(exc).__name__, exc))

    decision_id = str(metadata.get("decision_id", "")).strip() if isinstance(metadata, dict) else ""
    if decision_id:
        try:
            selection_rank = int(metadata.get("selection_rank", 1) or 1)
        except (TypeError, ValueError):
            selection_rank = 1
        outcome = "followed" if selection_rank == 1 else "overridden"
        outcome_params: dict[str, Any] = {"decisionId": decision_id, "outcome": outcome}
        if metadata.get("selected_model_id") not in (None, ""):
            outcome_params["selectedModelId"] = metadata.get("selected_model_id")
        if metadata.get("selection_rank") not in (None, ""):
            outcome_params["selectionRank"] = metadata.get("selection_rank")
        if metadata.get("agent_used") not in (None, ""):
            outcome_params["agentUsed"] = metadata.get("agent_used")
        try:
            router_result = _call_router("log_outcome", outcome_params)
            if bool(router_result.get("isError")):
                nexus_warnings.append("router.log_outcome failed: {0}".format(_result_error_text(router_result)))
        except Exception as exc:
            nexus_warnings.append("router.log_outcome failed: {0}".format(exc))

    cleared = _clear_active_interaction(state)
    _save_nexus_state(cleared)
    payload = {
        "finished": True,
        "status": status,
        "run_id": run_id or governor_payload.get("run_id"),
        "governor": governor_payload,
        "auto_memory": auto_memory,
    }
    if nexus_warnings:
        payload["nexus_warnings"] = nexus_warnings
    return _text_result(
        "Finished interaction run {0} with status '{1}'.".format(payload["run_id"], status),
        payload,
    )


def _handle_reset_interaction(params: dict[str, Any]) -> dict[str, Any]:
    try:
        confirm = _parse_bool_param(params, "confirm", False)
        abandon_run = _parse_bool_param(params, "abandon_run", False)
    except ValueError as exc:
        return _error_result("invalid_arguments", str(exc))
    if not confirm:
        return _error_result("confirmation_required", "reset_interaction requires confirm=true.")
    state = _load_nexus_state()
    payload: dict[str, Any] = {"reset": True, "active_run_id": None}
    if abandon_run and _interaction_is_active(state):
        try:
            governor_result = _call_governor("reset_run", {"yes": True})
        except Exception as exc:
            return _error_result("component_error", "Governor reset_run failed: {0}".format(exc))
        if not isinstance(governor_result, dict):
            return _error_result("component_error", "Governor reset_run returned invalid response.")
        if bool(governor_result.get("isError")):
            return governor_result
        payload["governor"] = _structured_content(governor_result)
    _save_nexus_state(_clear_active_interaction(state))
    return _text_result("Nexus interaction state reset.", payload)


_NEXUS_SELF_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "doctor": _handle_status,
    "status": _handle_status,
    "list_actions": _handle_list_namespaces,
    "list_namespaces": _handle_list_namespaces,
    "help": _handle_help,
    "start_interaction": _handle_start_interaction,
    "finish_interaction": _handle_finish_interaction,
    "reset_interaction": _handle_reset_interaction,
}


# ---------------------------------------------------------------------------
# Namespace delegate map
# ---------------------------------------------------------------------------

_NAMESPACE_DELEGATES: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "router": lambda action, params: _delegate_router(action, params),
    "governor": lambda action, params: _call_governor(action, params),
    "thrift": lambda action, params: _call_thrift(action, params),
    "mnemo": lambda action, params: _call_mnemo(action, params),
}


# ---------------------------------------------------------------------------
# Gateway dispatch
# ---------------------------------------------------------------------------


def nexus_gateway(args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch the single public Nexus MCP tool to a component action."""
    if not isinstance(args, dict):
        return _error_result(
            "invalid_args",
            "Nexus gateway arguments must be an object.",
            {"available_actions": NEXUS_ACTIONS},
        )

    action = str(args.get("action", "")).strip() or None
    params = args.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error_result(
            "invalid_params",
            "Nexus gateway params must be an object when provided.",
            {"available_actions": NEXUS_ACTIONS},
        )

    if not action:
        return _error_result(
            "missing_action",
            "Nexus gateway requires an 'action' field in 'namespace.subaction' format "
            "(e.g. 'router.doctor', 'mnemo.record', 'thrift.grep_text').",
            {"available_actions": NEXUS_ACTIONS},
        )

    if "." not in action:
        return _error_result(
            "invalid_action_format",
            "Action '{0}' must be in 'namespace.subaction' format. Known namespaces: {1}.".format(
                action, ", ".join(_NAMESPACE_ACTIONS)
            ),
            {"available_actions": NEXUS_ACTIONS},
        )

    namespace, subaction = action.split(".", 1)

    if namespace == "nexus":
        handler = _NEXUS_SELF_HANDLERS.get(subaction)
        if handler is None:
            return _error_result(
                "unknown_action",
                "Unknown nexus action: nexus.{0}. Available: {1}.".format(
                    subaction, ", ".join(sorted(_NEXUS_SELF_HANDLERS))
                ),
                {"available_actions": NEXUS_ACTIONS},
            )
        return handler(params)

    delegate = _NAMESPACE_DELEGATES.get(namespace)
    if delegate is None:
        return _error_result(
            "unknown_namespace",
            "Unknown namespace '{0}'. Known namespaces: {1}.".format(
                namespace, ", ".join(_NAMESPACE_ACTIONS)
            ),
            {"available_actions": NEXUS_ACTIONS},
        )

    started = time.perf_counter()
    try:
        result = delegate(subaction, params)
    except Exception as exc:
        return _error_result(
            "component_error",
            "{0}.{1} raised {2}: {3}".format(namespace, subaction, type(exc).__name__, exc),
            {"namespace": namespace, "subaction": subaction},
        )
    duration_ms = max(0, int((time.perf_counter() - started) * 1000.0))
    if not isinstance(result, dict):
        return _error_result(
            "component_error",
            "{0}.{1} returned an invalid response object.".format(namespace, subaction),
            {"namespace": namespace, "subaction": subaction},
        )

    state = _load_nexus_state()
    mutated_state = False
    if _should_auto_record(action, namespace, state):
        warning = _auto_record_to_governor(
            namespace=namespace,
            subaction=subaction,
            params=params,
            result=result,
            duration_ms=duration_ms,
            state=state,
        )
        if warning:
            result = _append_nexus_warning(result, warning)
        mutated_state = _interaction_is_active(state)
    elif _interaction_is_active(state):
        state["last_action_at"] = _utc_now_iso()
        mutated_state = True

    if namespace == "governor" and not bool(result.get("isError")) and _interaction_is_active(state):
        structured = _structured_content(result)
        affected_run_id = ""
        if subaction == "finish_run":
            affected_run_id = str(structured.get("run_id") or "").strip()
        elif subaction == "reset_run":
            affected_run_id = str(structured.get("active_run") or "").strip()
        if affected_run_id and affected_run_id == str(state.get("active_run_id") or ""):
            state = _clear_active_interaction(state)
            result = _append_nexus_warning(result, "interaction state cleared: run finished/reset via direct governor call")
            mutated_state = True

    if mutated_state:
        _save_nexus_state(state)
    return result


# ---------------------------------------------------------------------------
# MCP tool definition (Copilot-safe schema)
# ---------------------------------------------------------------------------

TOOLS = _build_tools()


# ---------------------------------------------------------------------------
# MCP JSON-RPC protocol
# ---------------------------------------------------------------------------


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _ok(request_id: Any, result: dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _rpc_error(request_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": "Error: {0}".format(message)}],
        "isError": True,
    }


def handle_request(message: dict[str, Any]) -> None:
    global _SHOULD_EXIT

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if request_id is None:
        return

    if method == "initialize":
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        _ok(
            request_id,
            {
                "protocolVersion": requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "title": SERVER_TITLE,
                    "version": SERVER_VERSION,
                },
                "instructions": (
                    "Use the single nexus gateway tool with action in 'namespace.subaction' format and optional params. "
                    "Use nexus.start_interaction before backend actions and nexus.finish_interaction when done. "
                    "Call nexus.status for active run and middleware counters."
                ),
            },
        )
        return

    if method == "ping":
        _ok(request_id, {})
        return

    if method == "shutdown":
        _ok(request_id, {})
        _SHOULD_EXIT = True
        return

    if method == "tools/list":
        _ok(request_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        if not isinstance(params, dict):
            _rpc_error(request_id, -32602, "Invalid tools/call params")
            return
        name = str(params.get("name", ""))
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            _rpc_error(request_id, -32602, "Tool arguments must be an object")
            return
        if name != GATEWAY_TOOL_NAME:
            _rpc_error(request_id, -32602, "Unknown tool: {0}".format(name))
            return
        try:
            _ok(request_id, nexus_gateway(args))
        except Exception as exc:
            _ok(request_id, _tool_error("{0}: {1}".format(type(exc).__name__, exc)))
        return

    _rpc_error(request_id, -32601, "Method not found: {0}".format(method))


def main() -> int:
    global _SHOULD_EXIT
    _SHOULD_EXIT = False
    if os.environ.get("AGENT_SUITE_SESSION_ID", "").strip() and not os.environ.get("THRIFT_SESSION_ID", "").strip():
        os.environ["THRIFT_SESSION_ID"] = os.environ["AGENT_SUITE_SESSION_ID"].strip()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _rpc_error(None, -32700, "Parse error: {0}".format(exc))
            continue
        if isinstance(message, list):
            for item in message:
                if isinstance(item, dict):
                    handle_request(item)
                if _SHOULD_EXIT:
                    break
        elif isinstance(message, dict):
            handle_request(message)
        else:
            _rpc_error(None, -32600, "Invalid request")
        if _SHOULD_EXIT:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
