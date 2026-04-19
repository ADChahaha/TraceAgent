# AGENT RULES

This file is written for AI agents working in this repository.
Treat every `MUST` / `MUST NOT` rule as a hard constraint.

## 0. Scope

- Applies to the entire repository and all services/subpackages under it.
- If a deeper directory has a more specific agent/collaboration doc, follow the deeper doc first.
- The rule "read the nearest `docs/DESIGN.md` before development" always remains in force.

## 1. Mandatory Workflow

For any non-trivial task, follow this order:

1. Identify the target service and target directory.
2. Read the nearest applicable `docs/DESIGN.md`.
3. Decide what tests define the target behavior.
4. Run TDD in order: `red -> green -> refactor`.
5. After implementation, evaluate whether `docs/DESIGN.md` must be updated.
6. After implementation, evaluate whether `DEVLOG.md` must be updated.
7. Do not declare the task complete until all required code, tests, and docs are synchronized.

## 2. MUST

- MUST identify the target service and change scope before editing code.
- MUST read the nearest applicable `docs/DESIGN.md` before editing code, tests, or structural docs.
- MUST continue reading deeper `docs/DESIGN.md` files when the change goes deeper into subdirectories.
- MUST use TDD for all behavior-changing work: `red -> green -> refactor`.
- MUST verify in `red` that the failing test fails for the intended behavior, not environment noise.
- MUST verify in `green` that related tests pass with the minimum implementation needed.
- MUST verify after `refactor` that behavior is unchanged and tests still pass.
- MUST keep generated or updated documentation concise and focused on key points; record the essentials rather than exhaustively describing every item unless the user explicitly asks for full detail.
- MUST update the corresponding `docs/DESIGN.md` if the change affects module boundaries, processing flow, directory structure, responsibility split, key design decisions, or cross-module dependencies.
- MUST evaluate whether the corresponding `DEVLOG.md` should be updated if the change affects behavior, implementation logic, interfaces, tests, processing flow, important problems, tradeoffs, or next steps.
- MUST ask the user for approval before editing any `DEVLOG.md`.
- MUST place test-facing documentation for changes under `agent/` inside `agent/tests/<target>/docs/` when such documentation is needed.
- MUST keep `agent/` test documentation separate from development docs such as `docs/DESIGN.md` and `DEVLOG.md`.
- MUST write `agent/` test documentation as one concise doc file per test source file when such documentation is requested or needed.
- MUST name `agent/` test documentation files so they map clearly to the corresponding test file, for example `test_schemas.py -> docs/test_schemas.md`.
- MUST make `agent/` test documentation easy to scan and understand at a glance.
- MUST include a brief explanation for each documented test function, so a reader can understand what it verifies without reading the test code first.
- MUST treat tests, `docs/DESIGN.md`, and `DEVLOG.md` as part of task completion when required by the change.

## 3. MUST NOT

- MUST NOT edit code before reading the applicable `docs/DESIGN.md`.
- MUST NOT propose or start implementation before understanding the design doc context.
- MUST NOT skip TDD for behavior changes.
- MUST NOT write the implementation first and add tests later.
- MUST NOT enter `green` before a meaningful failing test exists, except for docs-only, comment-only, or pure rename tasks with no behavior change.
- MUST NOT declare a task complete if doc-sync evaluation was skipped.
- MUST NOT skip tests or docs because of a "single-file change" preference.
- MUST NOT edit `DEVLOG.md` without explicit user approval.
- MUST NOT turn routine documentation into exhaustive per-item narration unless the user asks for that level of detail.
- MUST NOT write `agent/` test documentation into development doc directories such as `agent/<module>/docs/`.
- MUST NOT combine multiple unrelated `agent/` test files into a single shared test-doc file when one-file-per-test-file documentation is expected.
- MUST NOT use a generic `README.md` in place of a file-matched test doc when the intent is to document a specific test file.
- MUST NOT treat "implementation finished" as "task finished".

## 4. TDD Rules

Use TDD unless the task is one of these exceptions:

- docs-only change
- comment-only change
- pure rename with no behavior change

For TDD tasks:

- `red`: add or change tests first; confirm they fail for the target behavior.
- `green`: make the minimum change required to pass.
- `refactor`: improve structure without changing behavior; keep tests passing.

If the task involves real documents, real samples, or real input formats, add at least one validation test or doc test based on a real sample when practical.

## 5. Design Doc Rules

`docs/DESIGN.md` is the first entry point for understanding structure and boundaries.
It explains high-level design, not detailed implementation.

When choosing which design doc to read:

1. Prefer the target directory's own `docs/DESIGN.md`.
2. If missing, walk upward to the nearest parent that has one.
3. If the change reaches a deeper subdirectory, also read the deeper nearest design doc for that area.

Examples:

- Change in `agent/`: read `agent/docs/DESIGN.md`
- Change in `agent/ocr_processor/`: read `agent/docs/DESIGN.md`, then `agent/ocr_processor/docs/DESIGN.md`
- Change in `backend/`: read `backend/docs/DESIGN.md` if present
- Change in `frontend/`: read `frontend/docs/DESIGN.md` if present

## 6. File Change Rule

Default rule:

- Change one file only.

Exception:

- If the task inherently requires multiple files, explain the scope and risk to the user first and get approval.
- Files required for the same task's minimal test coverage do count as valid required files.
- Required sync updates to `docs/DESIGN.md` and `DEVLOG.md` do not count against the one-file preference.

Do not use the one-file preference as a reason to skip necessary tests or docs.

## 7. DEVLOG Rules

Before editing `DEVLOG.md`, ask the user and state:

- which `DEVLOG.md` you want to update
- what you plan to record
- what format you will use

If approved, keep `DEVLOG.md` concise.

Required format:

- maintain a top-level "last updated" field
- write the newest time block immediately below `last updated`, for example `## 2026-04-17 21:30:00`
- prioritize these items:
  - completed work
  - current progress
  - encountered problems
  - next step

## 8. Done Criteria

Do not report completion until all applicable items below are true:

- target service identified
- target directory identified
- applicable `docs/DESIGN.md` read
- TDD `red` completed, or a valid exception applies
- TDD `green` completed, or a valid exception applies
- TDD `refactor` completed, or a valid exception applies
- design doc sync evaluated
- devlog sync evaluated
- user approval obtained before any `DEVLOG.md` edit
- all required code, tests, and docs are synchronized

## 9. Short Reminder For Agents

Read design first.
Test first.
Implementation second.
Doc sync before completion.
No unauthorized `DEVLOG.md` edits.
