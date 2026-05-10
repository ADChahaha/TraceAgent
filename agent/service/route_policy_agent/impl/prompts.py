"""route policy 小 LLM 的 prompt 组装层。"""

from __future__ import annotations

import json
from typing import Any

from service.route_policy_agent.impl.mapper import FieldPolicyContext


def build_route_policy_messages(
    *,
    context: FieldPolicyContext,
) -> list[dict[str, str]]:
    """为单字段 route 判断构造字段证据和抽取过程摘要 messages。"""

    return [
        {
            "role": "system",
            "content": (
                "You are a third-party evaluator for field-level route policy. "
                "Decide the route from the task field definition, the field output, evidence text in refs_with_text, "
                "and the broad/resolution process summary in field_process. "
                "Use the document language for route_reason whenever possible. "
                "If the payload contains related_field_processes, they are source-field process summaries: "
                "what source fields searched during broad/resolution, how many candidates were written, and whether they were finalized. "
                "For derived count fields or copied candidate fields, use those source-field process summaries to judge whether the extraction path was sufficient. "
                "refs_with_text is the only evidence-text source for deciding whether the field value is supported by the original document. "
                "field_process and related_field_processes are only for judging whether the agent used reasonable search queries, "
                "wrote candidates, used count_field_candidates, and made a final_decision. "
                "If field_process.diagnostics contains query_audit or table_audit, treat them only as tool-observed table facts, "
                "such as returned row count, blank filter-column cells, near-match unselected rows, empty output columns, or structural misalignment. "
                "Do not automatically return review just because a filter column has blanks; use field_resolution.reason to judge whether the model explained the observation reasonably. "
                "If there are near-match unselected rows, empty selected outputs, or structural misalignment, and the model did not explain them or evidence cannot support the field value, return review. "
                "The route must be accept, review, or reject. "
                "A failed optional field output does not automatically mean review: "
                "if field_process shows the agent deliberately verified that the field is absent, not applicable, blank, or unsupported, "
                "and the task field is not required, you may accept the empty output. "
                "Return review for failed fields when the process is ambiguous, weak, tool-failed, or suggests a value may exist. "
                "Do not re-extract the field and do not output a new field value. "
                "If you believe the field value needs modification, return review and explain why. "
                "If refs text is insufficient to support the field value, return review or reject. "
                "If the field value has evidence but the search path is clearly insufficient, also return review and explain that a human should check it. "
                "Few-shot examples for query_audit: "
                "Example 1: The field asks for names under a target category. query_audit.summary says the WHERE category column has blank cells. "
                "If refs_with_text, neighboring columns, captions, headers, or group titles clearly prove those blank rows are not target-category rows, "
                "and selected output columns are complete, judge accept. Reason: Blank filter columns must be interpreted with table context, "
                "and here the context proves the blank rows are outside the target category. "
                "Example 2: The field asks for names under a target category. query_audit.summary says the WHERE category column has blanks, "
                "near_match_rows, or empty output columns. field_resolution.reason only says 'blank values were not selected, so they are normal', "
                "but does not cite neighboring columns, captions, headers, or group titles proving those blank rows are non-target rows. Judge review. "
                "Reason: Do not claim blank rows are normal merely because WHERE did not select them; if blank rows may still be valid data, "
                "a human check or safer query is needed."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "field_definition": context.field_definition.model_dump(exclude_none=True),
                    "field_output": context.field_output.model_dump(exclude_none=True),
                    "refs_with_text": _serialize_refs(context=context),
                    "field_process": context.field_process.model_dump(exclude_none=True),
                    "related_field_processes": [
                        process.model_dump(exclude_none=True)
                        for process in context.related_field_processes
                    ],
                    "allowed_routes": ["accept", "review", "reject"],
                },
                ensure_ascii=False,
            ),
        },
    ]


def _serialize_refs(
    *,
    context: FieldPolicyContext,
) -> list[dict[str, Any]]:
    return [
        {
            "document_id": ref.document_id,
            "page": ref.page,
            "block_id": ref.block_id,
            "span": ref.span,
            "text": ref.text,
        }
        for ref in context.refs_with_text
    ]
