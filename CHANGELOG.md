# Nexus MCP Changelog

## 0.2.4 (2026-06-01)

- Fixed Mnemo namespace action-catalogue drift in Nexus.
  - Exposed the full current Mnemo public gateway action surface through Nexus discovery/schema/dispatch.
  - Added Topics action exposure: `mnemo.topic_add`, `mnemo.topic_remove`, `mnemo.topic_list`.
  - Added Memory Packs action exposure: `mnemo.pack_preview`, `mnemo.pack_redaction_preview`, `mnemo.pack_export`, `mnemo.pack_inspect`, `mnemo.pack_import`, `mnemo.pack_list_imports`, `mnemo.pack_review_import`, `mnemo.pack_promote_preview`, `mnemo.pack_promote`.
  - Added signer action exposure: `mnemo.signer_add`, `mnemo.signer_list`, `mnemo.signer_disable`, `mnemo.signer_enable`.
- Added schema/list_actions/dispatcher consistency tests for Mnemo namespace actions, including pack/signer/topic coverage and a drift guard against Mnemo `GATEWAY_ACTIONS`.
- Added dispatch smoke tests proving that `mnemo.pack_preview`, `mnemo.pack_inspect`, and signer actions reach Mnemo instead of failing at Nexus enum/action validation.
- Audited and cleaned `nexus.finish_interaction` status values.
  - Canonical statuses: `success`, `failed`, `stopped`, `abandoned`.
  - Legacy aliases remain accepted and normalized: `failure` → `failed`, `blocked` → `stopped`.
- Performed a deep action-drift scan across Nexus/Mnemo/Router/Governor/Thrift integration surfaces.
  - Blocking drift found: stale Mnemo action exposure in Nexus.
  - Blocking drift fixed in this release.
  - Future optional hardening: derive Nexus namespace catalogues dynamically from component action registries with static fallback.


## 0.2.3 (2026-05-24)

- Mirrored Thrift economy telemetry for Nexus-routed Thrift calls that bypass Thrift's JSON-RPC dispatcher.
- Preserved active Nexus run correlation by adding `active_run_id` only to the telemetry mirror arguments, not to the original Thrift call params.
- Added failure-safe stderr warnings for Thrift telemetry mirror failures.
- Added focused tests for telemetry mirroring, run-id injection, no double invocation, and failure-safe behavior.

## 0.2.2 (2026-05-19)

- Added automatic Mnemo `interaction_log` recording from `nexus.finish_interaction`.
- Added `record_memory=false` opt-out and `NEXUS_AUTO_MEMORY=0` environment default override.
- Made finish-time memory recording failure-safe with `nexus_warnings` instead of failed interaction finishes.
- Updated tests for default memory recording, opt-out, and Mnemo failure handling.
- Cleaned standalone package metadata for first GitHub distribution.

## 0.2.1 (2026-05-17)

- Added `router.validate_workflow_params` to the explicit Nexus action catalogue and schema enum.
- Updated Nexus help/examples and docs for registry-first Router workflow calls.
- Kept single-tool MCP surface (`nexus`) and compatibility routing behavior.

## 0.2.0 (2026-05-17)

- Added Nexus-native interaction lifecycle actions:
  - `nexus.start_interaction`
  - `nexus.status` (active run + middleware counters + governor status passthrough)
  - `nexus.finish_interaction`
- Added persisted Nexus interaction state under `state/nexus` (`NEXUS_STATE_DIR` supported).
- Added middleware auto-recording to Governor for active runs:
  - auto-records `thrift.*`, `mnemo.*`, and `router.*` calls as `governor.record_tool_call`.
  - captures compact detail payloads including namespace/action, target hints, query/path hints, params summary, result summary, success, duration, token estimate, and result size.
  - failure-safe behavior: main backend action still succeeds, warnings added under `nexus_warnings`.
- Added router compatibility aliases in Nexus:
  - `router.match_workflow`
  - `router.get_workflow`
  (with fallback behavior when backend router does not expose those actions directly).
- Expanded Nexus action catalogue to include newer Governor and Mnemo query/event actions.

## 0.1.0 (2026-05-16)

Initial release.

- Single `nexus` MCP gateway wrapping Mnemo, Thrift, Agent Governor, and Agent Router.
- Namespaced actions: `nexus.*`, `router.*`, `governor.*`, `thrift.*`, `mnemo.*`.
- In-process component delegation via `importlib.util.spec_from_file_location`.
- Lazy module loading with per-namespace cache.
- `nexus.status` — diagnostics: component server paths, existence, load state.
- `nexus.list_namespaces` — full action catalogue across all namespaces.
- Copilot-safe schema with `enum` listing all 46 namespaced actions.
- Smoke test and unit test suite.
