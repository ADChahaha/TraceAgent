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
- MUST identify the exact file or files explicitly specified by the user before making any edit.
- MUST only modify the specific file or files explicitly requested by the user, unless the user explicitly approves additional file changes or the extra files are strictly required for minimal test coverage or required documentation synchronization.
- MUST read the nearest applicable `docs/DESIGN.md` before editing code, tests, or structural docs.
- MUST continue reading deeper `docs/DESIGN.md` files when the change goes deeper into subdirectories.
- MUST use TDD for all behavior-changing work: `red -> green -> refactor`.
- MUST verify in `red` that the failing test fails for the intended behavior, not environment noise.
- MUST verify in `green` that related tests pass with the minimum implementation needed.
- MUST verify after `refactor` that behavior is unchanged and tests still pass.
- MUST keep generated or updated documentation concise and focused on key points; record the essentials rather than exhaustively describing every item unless the user explicitly asks for full detail.
- MUST put the basic implementation idea or working principle near the beginning of the corresponding documentation when documenting a module, component, or test file, so readers can understand how it works before reading the detailed cases.
- MUST update the corresponding `docs/DESIGN.md` if the change affects module boundaries, processing flow, directory structure, responsibility split, key design decisions, or cross-module dependencies.
- MUST evaluate whether the corresponding `DEVLOG.md` should be updated if the change affects behavior, implementation logic, interfaces, tests, processing flow, important problems, tradeoffs, or next steps.
- MUST ask the user for approval before editing any `DEVLOG.md`.
- MUST place test-facing documentation for changes under the corresponding `tests/docs/` directory when tests are added or changed.
- MUST keep test documentation separate from development docs such as `docs/DESIGN.md` and `DEVLOG.md`.
- MUST write test documentation as one concise doc file per test source file whenever tests are added or changed.
- MUST name test documentation files so they map clearly to the corresponding test file, for example `test_schemas.py -> docs/test_schemas.md`.
- MUST make `agent/` test documentation easy to scan and understand at a glance.
- MUST include a brief explanation for each documented test function, so a reader can understand what it verifies without reading the test code first.
- MUST create or update the corresponding test doc immediately after writing or changing a test file.
- MUST treat tests, `docs/DESIGN.md`, and `DEVLOG.md` as part of task completion when required by the change.

## 3. MUST NOT

- MUST NOT edit code before reading the applicable `docs/DESIGN.md`.
- MUST NOT propose or start implementation before understanding the design doc context.
- MUST NOT modify files beyond those explicitly specified by the user unless the user has explicitly approved the expanded scope or the extra files are strictly required for minimal test coverage or required doc synchronization.
- MUST NOT skip TDD for behavior changes.
- MUST NOT write the implementation first and add tests later.
- MUST NOT enter `green` before a meaningful failing test exists, except for docs-only, comment-only, or pure rename tasks with no behavior change.
- MUST NOT declare a task complete if doc-sync evaluation was skipped.
- MUST NOT skip tests or docs because of a "single-file change" preference.
- MUST NOT edit `DEVLOG.md` without explicit user approval.
- MUST NOT turn routine documentation into exhaustive per-item narration unless the user asks for that level of detail.
- MUST NOT write documentation that jumps straight into test cases or field lists without first explaining the basic implementation idea when that idea is needed to understand the module or test target.
- MUST NOT write test documentation into development doc directories such as `docs/` or module design-doc directories.
- MUST NOT combine multiple unrelated test files into a single shared test-doc file when one-file-per-test-file documentation is expected.
- MUST NOT use a generic `README.md` in place of a file-matched test doc when the intent is to document a specific test file.
- MUST NOT finish test work without adding or updating the corresponding documentation file under the matching `tests/docs/` directory.
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

- Change only the file or files explicitly specified by the user.

Exception:

- If the task inherently requires multiple files, explain the scope and risk to the user first and get approval.
- Files required for the same task's minimal test coverage do count as valid required files.
- Required sync updates to `docs/DESIGN.md` and `DEVLOG.md` do not count against the one-file preference.
- Required test documentation files corresponding to changed test files do not count against the user-specified-file preference.

Do not use the user-specified-file preference as a reason to skip necessary tests or docs.

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
- user-specified target file or files identified
- applicable `docs/DESIGN.md` read
- TDD `red` completed, or a valid exception applies
- TDD `green` completed, or a valid exception applies
- TDD `refactor` completed, or a valid exception applies
- for every added or changed test file, the corresponding doc under the matching `tests/docs/` location has been added or updated
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
