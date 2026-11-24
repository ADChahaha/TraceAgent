"""面向前端与外部调用方的错误脱敏与分类映射。

原始异常与技术详情一律留在服务端日志，对外只返回清晰、具体、可操作的英文提示，
不暴露 gRPC 状态细节、本机地址/端口、依赖包名、SQLite 报错或堆栈。
"""

from __future__ import annotations

from backend.services.errors import (
    AgentServiceError,
    BackendServiceError,
    ConflictError,
    DocumentServiceError,
    NotFoundError,
    ValidationError,
)

_VALIDATION_MESSAGES = {
    "content 不能为空": "Please enter a question before sending.",
    "未知的 run_options 字段": "One or more request options are invalid.",
    "工具超时必须为有限正数": "One or more request options are invalid.",
    "files 不能为空": "Select at least one PDF or DOCX file to upload.",
    "文件名不能为空且不能包含路径分隔符": "One of the selected filenames is invalid.",
    "同一批上传文件名重复": "Duplicate filenames cannot be uploaded in the same batch.",
    "只支持 PDF/DOCX 文件": "Only PDF and DOCX files are supported.",
    "文件内容不能为空": "Empty files cannot be uploaded.",
    "会话文件数超过限制": "This workspace has reached the maximum number of files.",
    "会话资源总量超过限制": "This upload exceeds the workspace size limit.",
    "只能删除原始文件": "Only uploaded source files can be removed.",
    "只能下载原始文件": "Only uploaded source files can be downloaded.",
    "无效的文档路径": "The requested document path is invalid.",
    "未知的文件字段": "Invalid upload request format.",
}

_NOT_FOUND_MESSAGES = {
    "会话不存在": "This workspace could not be found.",
    "轮次不存在": "This response turn could not be found.",
    "资源不存在": "This source file is no longer available.",
    "文件不存在": "This source file is no longer available.",
    "会话没有文档归档": "No processed documents are available in this workspace yet.",
    "段落不存在": "The referenced passage could not be found in this workspace.",
    "文档不存在": "The requested document could not be found in this workspace.",
}

_CONFLICT_MESSAGES = {
    "会话已有活跃轮次": "A response is already in progress. Wait for it to finish or stop it first.",
    "该轮次不是当前活跃轮次": "This response is no longer active.",
    "会话正在初始化": "This workspace is still loading. Please try again in a moment.",
    "会话正在关闭": "This workspace is resetting. Please try again in a moment.",
}

_BACKEND_MESSAGES = {
    "恢复期间订阅溢出，请重新连接": "Live updates fell behind. Reconnect to resume this workspace.",
    "会话快照超过恢复预算": "This workspace history is too large to load.",
    "会话管理器已关闭": "This workspace session was reset. Please refresh and try again.",
    "会话命令队列繁忙": "This workspace is busy right now. Please try again in a moment.",
    "会话存储异常，请恢复服务后重试": "We couldn't save your workspace changes right now. Please try again.",
}


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def format_document_error(raw: str) -> str:
    lowered = raw.lower()
    if _contains_any(lowered, ("unavailable", "connection refused", "failed to connect", "connect error")):
        return "Document processing is temporarily unavailable. Please try again in a moment."
    if _contains_any(lowered, ("deadline_exceeded", "timed out", "timeout")):
        return "Document processing timed out. Try a smaller file or retry."
    if _contains_any(lowered, ("invalid_argument", "unsupported", "corrupt", "invalid pdf", "invalid docx")):
        return "This document could not be read. Check that the file is a valid PDF or DOCX and try again."
    if _contains_any(lowered, ("not_found", "no such key", "no such bucket")):
        return "The requested document content is no longer available."
    if _contains_any(lowered, ("resource_exhausted", "too large", "quota", "rate limit")):
        return "Document processing is busy right now. Please wait a moment and try again."
    return "We couldn't process this document right now. Please try again."


def format_agent_error(raw: str) -> str:
    lowered = raw.lower()
    if _contains_any(lowered, ("unavailable", "connection refused", "failed to connect", "connect error")):
        return "The assistant service is temporarily unavailable. Please try again in a moment."
    if _contains_any(lowered, ("deadline_exceeded", "timed out", "timeout")):
        return "The request timed out before an answer was ready. Please try again."
    if _contains_any(lowered, ("resource_exhausted", "rate limit", "too many requests", "429", "overloaded")):
        return "The assistant is busy right now. Please wait a moment and try again."
    if _contains_any(lowered, ("unauthorized", "authentication", "invalid api key", "api key", "401", "403")):
        return "The model service rejected authentication. Check the server configuration and try again."
    if _contains_any(lowered, ("context length", "maximum context", "too many tokens", "context_length_exceeded")):
        return "This conversation exceeded the model's context limit. Start a new workspace or shorten your question."
    if _contains_any(lowered, ("未返回终态", "stream", "broken pipe", "disconnected", "remoteprotocolerror", "connection reset")):
        return "The response stream was interrupted before completion. Please try again."
    if _contains_any(lowered, ("invalid_argument",)):
        return "This request could not be processed. Check your input and try again."
    return "Unable to generate a response right now. Please try again."


def format_http_error(exc: BackendServiceError) -> str:
    """将后端服务异常映射为不暴露内部实现的用户态 HTTP detail。"""
    raw = str(exc).strip()
    if isinstance(exc, DocumentServiceError):
        return format_document_error(raw)
    if isinstance(exc, AgentServiceError):
        return format_agent_error(raw)
    if isinstance(exc, ValidationError):
        return _VALIDATION_MESSAGES.get(raw, "The request is invalid. Please check your input and try again.")
    if isinstance(exc, NotFoundError):
        return _NOT_FOUND_MESSAGES.get(raw, "The requested resource could not be found.")
    if isinstance(exc, ConflictError):
        return _CONFLICT_MESSAGES.get(raw, "This workspace is busy right now. Please try again in a moment.")
    return _BACKEND_MESSAGES.get(raw, "Something went wrong while handling your request. Please try again.")


def format_turn_error(exc_or_message: BaseException | str | None) -> str:
    """将轮次执行失败原因转换为用户态英文提示，避免把内部异常写入对外状态。"""
    if isinstance(exc_or_message, AgentServiceError):
        return format_agent_error(str(exc_or_message))
    if isinstance(exc_or_message, DocumentServiceError):
        return format_document_error(str(exc_or_message))
    if isinstance(exc_or_message, BackendServiceError):
        return format_http_error(exc_or_message)
    raw = str(exc_or_message or "").strip()
    return format_agent_error(raw)
