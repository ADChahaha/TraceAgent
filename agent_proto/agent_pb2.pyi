from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UploadedFile(_message.Message):
    __slots__ = ("filename", "content")
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    filename: str
    content: bytes
    def __init__(self, filename: _Optional[str] = ..., content: _Optional[bytes] = ...) -> None: ...

class PrepareResourcesRequest(_message.Message):
    __slots__ = ("files",)
    FILES_FIELD_NUMBER: _ClassVar[int]
    files: _containers.RepeatedCompositeFieldContainer[UploadedFile]
    def __init__(self, files: _Optional[_Iterable[_Union[UploadedFile, _Mapping]]] = ...) -> None: ...

class Document(_message.Message):
    __slots__ = ("filename", "html")
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    HTML_FIELD_NUMBER: _ClassVar[int]
    filename: str
    html: str
    def __init__(self, filename: _Optional[str] = ..., html: _Optional[str] = ...) -> None: ...

class PrepareResourcesResponse(_message.Message):
    __slots__ = ("resource_path", "documents")
    RESOURCE_PATH_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    resource_path: str
    documents: _containers.RepeatedCompositeFieldContainer[Document]
    def __init__(self, resource_path: _Optional[str] = ..., documents: _Optional[_Iterable[_Union[Document, _Mapping]]] = ...) -> None: ...

class QaMessage(_message.Message):
    __slots__ = ("role", "content", "tool_calls_json", "tool_call_id", "name")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALLS_JSON_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    role: str
    content: str
    tool_calls_json: str
    tool_call_id: str
    name: str
    def __init__(self, role: _Optional[str] = ..., content: _Optional[str] = ..., tool_calls_json: _Optional[str] = ..., tool_call_id: _Optional[str] = ..., name: _Optional[str] = ...) -> None: ...

class RunOptions(_message.Message):
    __slots__ = ("max_tool_calls", "tool_execution_timeout")
    MAX_TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    TOOL_EXECUTION_TIMEOUT_FIELD_NUMBER: _ClassVar[int]
    max_tool_calls: int
    tool_execution_timeout: float
    def __init__(self, max_tool_calls: _Optional[int] = ..., tool_execution_timeout: _Optional[float] = ...) -> None: ...

class ModelConfig(_message.Message):
    __slots__ = ("provider", "base_url", "api_key", "model_name", "api_transport", "temperature", "top_p", "top_k", "reasoning_effort", "max_retries", "request_timeout")
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    API_TRANSPORT_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    TOP_P_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    REASONING_EFFORT_FIELD_NUMBER: _ClassVar[int]
    MAX_RETRIES_FIELD_NUMBER: _ClassVar[int]
    REQUEST_TIMEOUT_FIELD_NUMBER: _ClassVar[int]
    provider: str
    base_url: str
    api_key: str
    model_name: str
    api_transport: str
    temperature: float
    top_p: float
    top_k: int
    reasoning_effort: str
    max_retries: int
    request_timeout: float
    def __init__(self, provider: _Optional[str] = ..., base_url: _Optional[str] = ..., api_key: _Optional[str] = ..., model_name: _Optional[str] = ..., api_transport: _Optional[str] = ..., temperature: _Optional[float] = ..., top_p: _Optional[float] = ..., top_k: _Optional[int] = ..., reasoning_effort: _Optional[str] = ..., max_retries: _Optional[int] = ..., request_timeout: _Optional[float] = ...) -> None: ...

class ChatCompletionRequest(_message.Message):
    __slots__ = ("completion_id", "resource_path", "messages", "run_options", "model_config", "base_url", "api_key", "openai_api_key", "model", "api_transport", "temperature", "top_p", "top_k", "stream")
    COMPLETION_ID_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_PATH_FIELD_NUMBER: _ClassVar[int]
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    RUN_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    MODEL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    OPENAI_API_KEY_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    API_TRANSPORT_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    TOP_P_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    STREAM_FIELD_NUMBER: _ClassVar[int]
    completion_id: str
    resource_path: str
    messages: _containers.RepeatedCompositeFieldContainer[QaMessage]
    run_options: RunOptions
    model_config: ModelConfig
    base_url: str
    api_key: str
    openai_api_key: str
    model: str
    api_transport: str
    temperature: float
    top_p: float
    top_k: int
    stream: bool
    def __init__(self, completion_id: _Optional[str] = ..., resource_path: _Optional[str] = ..., messages: _Optional[_Iterable[_Union[QaMessage, _Mapping]]] = ..., run_options: _Optional[_Union[RunOptions, _Mapping]] = ..., model_config: _Optional[_Union[ModelConfig, _Mapping]] = ..., base_url: _Optional[str] = ..., api_key: _Optional[str] = ..., openai_api_key: _Optional[str] = ..., model: _Optional[str] = ..., api_transport: _Optional[str] = ..., temperature: _Optional[float] = ..., top_p: _Optional[float] = ..., top_k: _Optional[int] = ..., stream: _Optional[bool] = ...) -> None: ...

class ToolCall(_message.Message):
    __slots__ = ("id", "name", "args_json")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_JSON_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    args_json: str
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., args_json: _Optional[str] = ...) -> None: ...

class CompletionEvent(_message.Message):
    __slots__ = ("type", "seq", "status", "content", "tool", "tool_call_id", "args_json", "result_json", "tool_calls", "tool_call_count", "is_final", "stop_signal", "error", "error_message")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    TOOL_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_ID_FIELD_NUMBER: _ClassVar[int]
    ARGS_JSON_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_COUNT_FIELD_NUMBER: _ClassVar[int]
    IS_FINAL_FIELD_NUMBER: _ClassVar[int]
    STOP_SIGNAL_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    type: str
    seq: int
    status: str
    content: str
    tool: str
    tool_call_id: str
    args_json: str
    result_json: str
    tool_calls: _containers.RepeatedCompositeFieldContainer[ToolCall]
    tool_call_count: int
    is_final: bool
    stop_signal: str
    error: str
    error_message: str
    def __init__(self, type: _Optional[str] = ..., seq: _Optional[int] = ..., status: _Optional[str] = ..., content: _Optional[str] = ..., tool: _Optional[str] = ..., tool_call_id: _Optional[str] = ..., args_json: _Optional[str] = ..., result_json: _Optional[str] = ..., tool_calls: _Optional[_Iterable[_Union[ToolCall, _Mapping]]] = ..., tool_call_count: _Optional[int] = ..., is_final: _Optional[bool] = ..., stop_signal: _Optional[str] = ..., error: _Optional[str] = ..., error_message: _Optional[str] = ...) -> None: ...

class CompletionRequest(_message.Message):
    __slots__ = ("completion_id",)
    COMPLETION_ID_FIELD_NUMBER: _ClassVar[int]
    completion_id: str
    def __init__(self, completion_id: _Optional[str] = ...) -> None: ...

class CompletionResponse(_message.Message):
    __slots__ = ("id", "status")
    ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    id: str
    status: str
    def __init__(self, id: _Optional[str] = ..., status: _Optional[str] = ...) -> None: ...

class CapabilitiesResponse(_message.Message):
    __slots__ = ("supported_file_types", "implemented_file_types", "engine")
    SUPPORTED_FILE_TYPES_FIELD_NUMBER: _ClassVar[int]
    IMPLEMENTED_FILE_TYPES_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    supported_file_types: _containers.RepeatedScalarFieldContainer[str]
    implemented_file_types: _containers.RepeatedScalarFieldContainer[str]
    engine: str
    def __init__(self, supported_file_types: _Optional[_Iterable[str]] = ..., implemented_file_types: _Optional[_Iterable[str]] = ..., engine: _Optional[str] = ...) -> None: ...
