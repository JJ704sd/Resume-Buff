# GitHub Architecture Audit Findings

## Evidence Log

- GitHub remote is `https://github.com/JJ704sd/Resume-Buff.git`.
- GitHub default branch is `main`; `git ls-remote --symref ... HEAD` returned commit `09a2704dd7f54170d83be35e788c945dcae4ed6c`.
- Local `HEAD` and `origin/main` both resolve to `09a2704dd7f54170d83be35e788c945dcae4ed6c`, so the local checkout matches the GitHub default branch snapshot.
- Local dirty state before docs: only this audit planning directory was untracked.
- Key docs inspected: `README.md`, `AGENTS.md`, `.harness/docs/architecture.md`, `.harness/docs/agent-enhancement-spec.md`, `.harness/docs/round5-b-agent-capability-spec.md`, `.harness/docs/ROADMAP.md`.
- Key implementation inspected: `backend/core/agent_tools.py`, `backend/core/tool_schema.py`, `backend/core/agent_workflow.py`, `backend/core/logger.py`, `backend/core/generator.py`, `backend/api/resume.py`, `backend/core/jd_parser.py`, `frontend/src/api/index.ts`, `frontend/src/App.vue`.
- Verification: `cd backend && D:\python3.11\python.exe -m pytest tests/ -q` -> `487 passed, 1 warning in 54.93s`.

## Implementation Matrix

- High-level Vue SPA -> FastAPI -> backend data/output/logs architecture matches `.harness/docs/architecture.md`.
- R5-A Agent workflow, tool registry, JSONL trace, replay script, evidence retrieval, and eval script are implemented.
- R5-B Phase 2A is implemented in code and tests, even though `.harness/docs/round5-b-agent-capability-spec.md` still describes Phase 2A as the recommended next step from a 441-test baseline.
- Backend API exposes `enable_agent_workflow`, `enable_function_calling`, `session_id`, and `enable_external_resume`, but does not expose `external_resume_text` on preview/generate.
- Frontend API and UI do not expose Agent workflow controls, `agent_summary`, `evidence_summary`, or `external_resume_perspective` in preview.
- External resume support exists for `/api/resume/parse-external` and `/api/jd/match`, but Agent workflow still treats external resume as a `tool=None` placeholder.
- Eval script still infers tools from the last JSONL trace request id prefix instead of using `preview["agent_summary"]["request_id"]`.

## Decisions

- Keep this pass documentation-only unless the audit exposes a blocking metadata issue in the future spec itself.
- Put the user-facing audit report and next spec under `.harness/docs/`, because existing architecture and round design docs live there.
- Create a new `round5-c-agent-capability-spec.md` instead of overwriting `round5-b-agent-capability-spec.md`; Phase 2A is already implemented, so the future entry point should start after that baseline.
