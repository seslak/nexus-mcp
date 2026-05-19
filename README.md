![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Status](https://img.shields.io/badge/status-experimental-orange)
![MCP](https://img.shields.io/badge/MCP-gateway-purple)

# Nexus MCP v0.2.2

Single-gateway MCP facade over local **Mnemo**, **Thrift**, **Agent Governor**, and **Agent Router**.

Nexus exposes exactly one MCP tool: `nexus`.

## Active interaction flow

Use Nexus-native lifecycle actions so Chief does not manually call `governor.record_tool_call` after each backend call:

1. `nexus.start_interaction`
2. backend actions (`thrift.*`, `mnemo.*`, `router.*`)
3. `nexus.finish_interaction`

While an interaction is active, Nexus middleware auto-records backend tool calls into Governor. On `nexus.finish_interaction`, Nexus also auto-records one Mnemo `interaction_log` for the completed run unless `record_memory=false` is passed or `NEXUS_AUTO_MEMORY=0` is set.

## Actions

All actions use `namespace.subaction`.

| Namespace | Actions |
|---|---|
| `nexus` | `doctor`, `status`, `list_actions`, `help`, `start_interaction`, `finish_interaction` (`list_namespaces` alias kept) |
| `router` | `doctor`, `route`, `classify`, `validate_decision`, `list_workflows`, `list_specialists`, `list_models`, `log_decision`, `explain`, `match_workflow`, `get_workflow`, `validate_workflow_params` |
| `governor` | `doctor`, `version`, `list_profiles`, `start_run`, `record_event`, `record_tool_call`, `record_test`, `patch_check`, `check_budget`, `status`, `finish_run`, `reset_run`, `recent_runs`, `get_run`, `search_runs`, `recent_events`, `search_events`, `get_event`, `maintenance` |
| `thrift` | `workspace_info`, `find_files`, `grep_text`, `rank_files`, `file_window`, `compress_log`, `count_tokens`, `classify_task`, `cost_report`, `economy_salience_check` |
| `mnemo` | `record`, `search`, `recall`, `get`, `recent`, `update`, `delete`, `link`, `export`, `inspect`, `maintenance`, `compact_context`, `lookup_symbol`, `salience_check`, `backfill_signatures`, `consolidate_full`, `recent_events`, `search_events`, `get_event`, `memory_events` |

## Usage

```json
{"action":"nexus.start_interaction","params":{"task":"Update inbox/iban.php to reject BA and GB prefixes.","profile":"small_patch","metadata":{}}}
{"action":"thrift.file_window","params":{"path":"inbox/iban.php","start_line":1,"end_line":120}}
{"action":"mnemo.search","params":{"query":"IBAN validation","limit":8}}
{"action":"nexus.status","params":{}}
{"action":"nexus.finish_interaction","params":{"status":"success","result":"Implemented BA/GB prefix reject logic."}}
```

## Install / local run

For local development from a clone:

```bash
python -m pip install -e .
python server.py
```

`smoke_test.py` is an integration smoke test. It expects the backend MCP server paths to be available either through the `NEXUS_*_SERVER` environment variables or through the usual sibling `agentic/tools/mcp/...` layout.

## Environment variables

Set in the Nexus server process env (usually `agentic/.vscode/mcp.json`):

- `NEXUS_WORKSPACE_ROOT`
- `NEXUS_STATE_DIR` (default: `<workspace>/state/nexus`)
- `NEXUS_ROUTER_SERVER`
- `NEXUS_MNEMO_SERVER`
- `NEXUS_THRIFT_SERVER`
- `NEXUS_GOVERNOR_SERVER`
- `NEXUS_AUTO_MEMORY` (default: `1`; set to `0` to disable automatic Mnemo `interaction_log` recording on finish)

Component env vars are still read directly by those component servers when Nexus imports and calls them.

## State

Nexus persists interaction state under `state/nexus/nexus_state.json` (or `NEXUS_STATE_DIR`):

- `active_run_id`
- `task`
- `profile`
- `started_at`
- `last_action_at`
- `middleware_event_count`

## Notes

- Nexus auto-record middleware never blocks the primary backend action. If auto-record fails, Nexus returns the original result plus `nexus_warnings`.
- `nexus.finish_interaction` records a compact Mnemo `interaction_log` by default. Use `record_memory=false` for smoke tests or throwaway probes.
- Nexus remains a gateway/adaptor. It does not replace host edit/execute tooling.
