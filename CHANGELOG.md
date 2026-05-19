# Nexus MCP Changelog

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
