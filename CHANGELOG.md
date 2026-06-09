# Nexus MCP Changelog

## 0.2.7 (2026-06-05)

- Exposed new Mnemo read-only import-UX action through Nexus:
  - `mnemo.pack_landing_list`
- Updated public action catalogue, MCP schema enum, list-actions output, dispatch tests, and smoke coverage for the new Mnemo action.
- No Nexus feature redesign beyond Mnemo action exposure.
- No schema changes.

## 0.2.6 (2026-06-05)

- Fixed Nexus MCP schema/action-enum drift hardening for Mnemo memory-group actions:
  - `mnemo.memory_group_discover`
  - `mnemo.memory_group_preview`
- Made the public MCP tool schema enum derive from the same public action source used by dispatch and `nexus.list_actions`.
- Added schema/list-actions/dispatch regression tests that fail if public action exposure drifts again.
- Extended smoke coverage to verify:
  - `nexus.list_actions` includes Mnemo memory-group actions
  - MCP `tools/list` schema enum includes the same actions
  - `tools/call` accepts `mnemo.memory_group_discover`
- Added operator note that schema-aware clients may require MCP server restart or window reload after Nexus schema changes.
- No Mnemo runtime changes.
- No schema changes.

## 0.2.5 (2026-06-04)

### Added

- Exposed new Mnemo runtime group-selection actions through Nexus:
  - `mnemo.memory_group_discover`
  - `mnemo.memory_group_preview`

### Changed

- Bumped Nexus to `0.2.5`.
- Updated namespace catalogue, schema enum, list-actions output, and dispatch regression tests to stay in sync with Mnemo `GATEWAY_ACTIONS`.

## 0.2.4 (2026-05-31)

- Fixed Mnemo namespace action-catalogue drift in Nexus:
  - exposed full current Mnemo public gateway action surface through Nexus discovery/schema/dispatch.
  - added Topics action exposure:
    - `mnemo.topic_add`, `mnemo.topic_remove`, `mnemo.topic_list`
  - added Memory Packs action exposure:
    - `mnemo.pack_preview`, `mnemo.pack_redaction_preview`, `mnemo.pack_export`,
      `mnemo.pack_inspect`, `mnemo.pack_import`, `mnemo.pack_list_imports`,
      `mnemo.pack_review_import`, `mnemo.pack_promote_preview`, `mnemo.pack_promote`
  - added signer action exposure:
    - `mnemo.signer_add`, `mnemo.signer_list`, `mnemo.signer_disable`, `mnemo.signer_enable`
- Added schema/list_actions/dispatcher consistency tests for Mnemo namespace actions, including pack/signer/topic coverage and drift guard against Mnemo `GATEWAY_ACTIONS`.
- Added dispatch smoke tests proving:
  - `mnemo.pack_preview` dispatch reaches Mnemo (no Nexus enum/unknown-action rejection),
  - `mnemo.pack_inspect` reaches Mnemo-level validation errors when params are missing,
  - signer actions dispatch through Nexus.
- finish_interaction status enum cleanup:
  - canonical statuses now align with Governor run states:
    - `success`, `failed`, `stopped`, `abandoned`
  - legacy compatibility aliases accepted and normalized:
    - `failure` -> `failed`
    - `blocked` -> `stopped`
- Deep drift audit result:
  - blocking drift found and fixed for Mnemo namespace action exposure.
  - no further blocking dispatcher/schema drift found in Nexus for router/governor/thrift namespace exposure.

## 0.2.2 (2026-05-19)

- Added automatic Mnemo `interaction_log` recording from `nexus.finish_interaction`.
- Added `record_memory=false` opt-out and `NEXUS_AUTO_MEMORY=0` environment default override.
- Made finish-time memory recording failure-safe with `nexus_warnings` instead of failed interaction finishes.
- Updated tests for default memory recording, opt-out, and Mnemo failure handling.

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
