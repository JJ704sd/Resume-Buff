# Agent Architecture Audit Findings

## Notes

- Started from user request on 2026-06-27.
- Shell defaulted to `D:\Trae_develop_code`; all project commands must explicitly `Set-Location -LiteralPath 'D:\简历帮'`.

## Current Implementation Evidence

- Backend Agent registry exists in `backend/core/agent_tools.py`: `AGENT_TOOLS` includes `parse_jd`, `match_score`, `evaluate_bullet_jd_match`, `retrieve_evidence`, and `rewrite_highlights`.
- Workflow orchestration exists in `backend/core/agent_workflow.py`: deterministic `build_task_graph`, JSONL trace emission, optional evidence retrieval, and `enable_agent_workflow` path from generator.
- Structured trace exists in `backend/core/logger.py`: `JSONL_TRACE_FIELDS` has the expected 11 fields and `log_agent_trace_jsonl` writes append-only JSONL with defensive failure handling.
- Lightweight evidence retrieval exists in `backend/core/evidence.py`: snippets from projects/skills/honors/certs, lexical retrieval, stable sorting, summary truncation, and dict serialization.
- LLM rewriting accepts evidence and preserves old-path behavior when evidence is `None`.
- API request models expose `enable_agent_workflow` after `session_id`; `enable_function_calling` and `session_id` are also passed through.
- Replay script exists at `scripts/replay_agent_trace.py`.
- Phase 4 eval artifacts exist in the working tree: `scripts/evaluate_agent_workflow.py`, `backend/tests/test_agent_eval.py`, and `AI岗位JD库_agent_eval报告.md`.

## Gaps / Mismatches

- `.harness/docs/agent-enhancement-spec.md` is internally inconsistent: the top table still marks Phase 4 as not started, while the lower Phase 4 section says completed.
- The same spec still recommends starting Phase 1 + Phase 2, even though current code/docs indicate Phase 1-4 are already implemented.
- Spec §8.1 mentions `agent_trace: bool = False`, but `PreviewRequest` / `GenerateRequest` currently only expose `enable_agent_workflow`; no request field controls trace emission.
- Spec §8.2 describes `agent_summary`, but workflow preview currently returns `evidence_summary` only; there is no request_id/tools/fallback/latency summary in API responses.
- Frontend TypeScript API and UI do not expose `enable_agent_workflow`, `enable_function_calling`, `session_id`, `agent_summary`, or `evidence_summary`.
- `execute_agent_tool` stores schemas but does not actively validate JSON schema or enforce permission/context gates; it relies on Python `TypeError` and allowlist checks.
- `run_agent_workflow` currently hardcodes `has_external_resume = False`; the R3-G external resume parser exists, but external resume diagnosis is not part of the Agent workflow.
- `evaluate_bullet_jd_match` is still a representative single-step check in workflow, not true per-bullet evaluation.
- Eval report generation currently infers tools from trace files because preview responses do not expose a stable `request_id` / `agent_summary`.

## Working Tree Context

- Existing modified tracked files before this audit: `.harness/docs/ROADMAP.md`, `.harness/docs/agent-enhancement-spec.md`, `.harness/memory/MEMORY.md`, `AGENTS.md`, `README.md`.
- Existing untracked Phase 4 artifacts before this audit: `AI岗位JD库_agent_eval报告.md`, `backend/tests/test_agent_eval.py`, `scripts/evaluate_agent_workflow.py`.
- This audit added `.planning/agent-architecture-audit/` and will add a new R5-B future spec under `.harness/docs/`.
