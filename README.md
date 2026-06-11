![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Status](https://img.shields.io/badge/status-experimental-orange)
![MCP](https://img.shields.io/badge/MCP-gateway-purple)

# Nexus MCP v0.3.1

Single-gateway MCP facade over local **Mnemo**, **Thrift**, **Agent Governor**, and **Agent Router**.

Nexus exposes exactly one MCP tool: `nexus`.

## Active interaction flow

Use Nexus-native lifecycle actions so Chief does not manually call `governor.record_tool_call` after each backend call:

1. `nexus.start_interaction`
2. backend actions (`thrift.*`, `mnemo.*`, `router.*`)
3. `nexus.finish_interaction`

While an interaction is active, Nexus middleware auto-records backend tool calls into Governor. Nexus also mirrors Thrift economy telemetry for Nexus-routed Thrift calls and captures the mirrored `content_hash` so later `governor.sync_thrift` imports can skip Nexus-mirrored duplicates. On `nexus.finish_interaction`, Nexus auto-records one Mnemo `interaction_log` for the completed run unless `record_memory=false` is passed or `NEXUS_AUTO_MEMORY=0` is set.

`nexus.finish_interaction` now self-heals stale Governor `run_not_active` responses by synchronizing the Nexus active-run state. Backend diagnostic/probe actions that should not count as progress are skipped by auto-recording.

## Actions

All actions use `namespace.subaction`.

| Namespace | Actions |
|---|---|
| `nexus` | `doctor`, `finish_interaction`, `help`, `list_actions`, `list_namespaces`, `reset_interaction`, `start_interaction`, `status` |
| `router` | `classify`, `doctor`, `explain`, `get_workflow`, `list_models`, `list_specialists`, `list_workflows`, `log_decision`, `log_outcome`, `match_workflow`, `recent_decisions`, `reload_registries`, `route`, `suggest_workflow`, `validate_decision`, `validate_registries`, `validate_workflow_params` |
| `governor` | `check_budget`, `doctor`, `finish_run`, `get_event`, `get_run`, `list_profiles`, `maintenance`, `patch_check`, `recent_events`, `recent_runs`, `record_event`, `record_test`, `record_tool_call`, `reset_run`, `search_events`, `search_runs`, `start_run`, `stats`, `status`, `sync_thrift`, `version` |
| `thrift` | `classify_task`, `compress_log`, `cost_report`, `count_tokens`, `economy_salience_check`, `file_window`, `find_files`, `grep_text`, `plan_context`, `rank_files`, `workspace_info` |
| `mnemo` | `alias_hint`, `backfill_signatures`, `compact_context`, `consolidate_full`, `delete`, `doctor`, `export`, `get`, `get_event`, `inspect`, `link`, `lookup_symbol`, `maintenance`, `memory_events`, `memory_group_discover`, `memory_group_preview`, `pack_export`, `pack_import`, `pack_inspect`, `pack_landing_list`, `pack_list_imports`, `pack_preview`, `pack_promote`, `pack_promote_preview`, `pack_redaction_preview`, `pack_review_import`, `recall`, `recent`, `recent_events`, `record`, `salience_check`, `search`, `search_events`, `signer_add`, `signer_disable`, `signer_enable`, `signer_list`, `topic_add`, `topic_list`, `topic_remove`, `update` |

`nexus.list_namespaces` is kept as a compatibility alias for action discovery.

## Usage

```json
{"action":"nexus.start_interaction","params":{"task":"Update inbox/iban.php to reject BA and GB prefixes.","profile":"small_patch","metadata":{}}}
{"action":"thrift.file_window","params":{"path":"inbox/iban.php","start_line":1,"end_line":120}}
{"action":"mnemo.search","params":{"query":"IBAN validation","limit":8}}
{"action":"mnemo.pack_preview","params":{"topics":["iban-validation"],"limit":20}}
{"action":"mnemo.pack_export","params":{"pack_name":"iban_knowledge","topics":["iban-validation"],"allow_unsigned":true}}
{"action":"mnemo.pack_landing_list","params":{"limit":10}}
{"action":"mnemo.pack_import","params":{"pack_path":"C:/tmp/iban_knowledge.mem","allow_unsigned_quarantine":true}}
{"action":"mnemo.pack_review_import","params":{"pack_id":"pack_...","include_samples":true}}
{"action":"mnemo.pack_promote","params":{"pack_id":"pack_...","row_ids":["ctx_001"],"confirm_promote":true}}
{"action":"mnemo.memory_group_discover","params":{"query":"memory packs","limit_groups":10}}
{"action":"mnemo.memory_group_preview","params":{"group_id":"topic:mnemo-memory-packs","scope":"core_plus_related"}}
{"action":"nexus.status","params":{}}
{"action":"nexus.finish_interaction","params":{"status":"success","result":"Implemented BA/GB prefix reject logic."}}
```

`nexus.status` is read-only. It passes `record_check=false` through to Governor, so repeated status polling does not mutate Governor decision state or trigger no-progress escalation.

### `nexus.finish_interaction` status values

Canonical status values are:

- `success`
- `failed`
- `stopped`
- `abandoned`

For backward compatibility, Nexus also accepts:

- `failure` (normalized to `failed`)
- `blocked` (normalized to `stopped`)

## Prompt workflows

Nexus includes VS Code/Copilot prompt workflows for Mnemo Memory Packs under `.github/prompts/`:

- `mnemo.memory-pack-export.prompt.md`
- `mnemo.memory-pack-import.prompt.md`
- `mnemo.memory-pack-promote.prompt.md`

These prompts are release artifacts for guided Memory Pack export, import, and promotion through Nexus-routed Mnemo actions.

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

If `AGENT_SUITE_SESSION_ID` is set and `THRIFT_SESSION_ID` is unset, Nexus bridges the suite id into Thrift at startup so all components share the same session stamp.

## State

Nexus persists interaction state under `state/nexus/nexus_state.json` (or `NEXUS_STATE_DIR`):

- `active_run_id`
- `task`
- `profile`
- `started_at`
- `last_action_at`
- `middleware_event_count`

State writes are atomic and should not leave temporary save files after successful saves.

## Protocol compatibility

Nexus supports protocol negotiation for these MCP protocol versions:

- `2025-06-18`
- `2025-03-26`
- `2024-11-05`

The server also supports JSON-RPC `ping`.

## Notes

- Nexus auto-record middleware never blocks the primary backend action. If auto-record fails, Nexus returns the original result plus `nexus_warnings`.
- `nexus.reset_interaction` requires `confirm=true`. Use `abandon_run=true` to also call Governor `reset_run`.
- If the orchestrator stores routing metadata in `start_interaction.metadata` with `decision_id`, Nexus logs a Router outcome on finish. `selection_rank > 1` is treated as `overridden`; otherwise `followed`.
- Telemetry integrity: Nexus captures Thrift's mirrored `content_hash`, forwards it as Governor `record_tool_call.input_hash`, and later `governor.sync_thrift` skips those duplicates instead of double-counting them.
- `nexus.finish_interaction` records a compact Mnemo `interaction_log` by default. Use `record_memory=false` for smoke tests or throwaway probes.
- Nexus diagnostics include root-consistency and duplicate-module-name checks.
- Nexus remains a gateway/adaptor. It does not replace host edit/execute tooling.
- After changing the Nexus MCP action schema/enum, schema-aware clients such as VS Code/Copilot may need an MCP server restart or window reload to refresh cached tool schemas.
