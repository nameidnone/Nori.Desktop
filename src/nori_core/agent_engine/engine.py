"""Agent Engine - Core LLM conversation loop executor.

This module executes the complete dialogue loop in the backend:
- Read configuration and secrets
- Assemble personality/memory/skills/emotion/tools prompts
- Streaming LLM calls
- Protocol parsing
- Multi-round Tool Calling
- Replica distribution and final persistence

Corresponds to the migration of frontend services/agent/engine.ts responsibilities.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from http.client import HTTPConnection
from typing import Any, Callable, Final, Protocol, TypeVar
from collections.abc import Awaitable

from ..agent.protocol import (
    AgentRunState,
    ProtocolMessage,
    ProtocolToolCall,
    ToolApprovalRequest,
)
from ..chat.chat_service import ChatService
from ..chat.motion_markers import extract as motion_extract
from ..configuration.config_store import ConfigStore
from ..emotion.emotion_manager import EmotionManager
from ..memory.store import MemoryService
from ..tools.registry import ToolRegistry
from ..skills.service import SkillService

__all__ = [
    "AgentUsage",
    "AgentCallbacks",
    "AgentEngine",
    "AgentToolRoundsExceededException",
]


# =============================================================================
# Data Records
# =============================================================================


@dataclass(frozen=True)
class AgentUsage:
    """LLM usage and cache hit metrics."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int
    cache_hit_rate: float
    duration_ms: int
    model: str | None


# =============================================================================
# Callbacks
# =============================================================================


@dataclass
class AgentCallbacks:
    """Agent engine callback collection."""

    on_state: Callable[[AgentRunState], None] | None = None
    """Running state change."""

    on_text_chunk: Callable[[str], None] | None = None
    """Streaming text increment (visible text after protocol parsing)."""

    on_text_correction: Callable[[str], None] | None = None
    """Replacement text when complete protocol parsing finds incremental projection inconsistency."""

    on_tool_executing: Callable[[str, Any | None], None] | None = None
    """Tool execution started."""

    on_tool_executed: Callable[[str, Any | None, str | None], None] | None = None
    """Tool execution completed."""

    on_usage: Callable[[AgentUsage], None] | None = None
    """LLM usage metrics."""

    request_approval: Callable[[ToolApprovalRequest], Awaitable[bool]] | None = None
    """Per-call tool authorization; confirm/dangerous tools must be approved by user before execution."""

    on_complete: Callable[[ProtocolMessage], None] | None = None
    """Final reply output (after multi-round tool calls)."""


# =============================================================================
# Exceptions
# =============================================================================


class AgentToolRoundsExceededException(Exception):
    """Raised when tool iteration limit is exceeded."""

    def __init__(self, max_iterations: int) -> None:
        super().__init__(f"Agent tool rounds exceeded maximum iterations ({max_iterations})")
        self.max_iterations = max_iterations


# =============================================================================
# Supporting Classes (Stubs - to be implemented in separate files)
# =============================================================================


class AgentSessionCoordinator:
    """Coordinates agent session lifecycle and cancellation."""

    def start(self, session_id: str, parent_token: asyncio.CancelledError | None = None) -> AgentSessionLease:
        """Start a new session lease."""
        return AgentSessionLease(session_id, parent_token)


@dataclass
class AgentSessionLease:
    """Session lease with cancellation token."""

    session_id: str
    parent_token: asyncio.CancelledError | None
    cancellation_token: asyncio.CancelledError | None = field(init=False)

    def __post_init__(self) -> None:
        self.cancellation_token = self.parent_token

    def __enter__(self) -> AgentSessionLease:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class AgentTraceSink:
    """Trace sink for agent operations."""

    @staticmethod
    def noop() -> AgentTraceSink:
        """Return a no-op trace sink."""
        return AgentTraceSink()

    def write(
        self,
        session_id: str,
        operation: str,
        duration_ms: int,
        iteration: int | None,
        tool_name: str | None,
        status: str,
        failure_category: str | None = None,
        usage: Any | None = None,
    ) -> None:
        """Write a trace entry (no-op implementation)."""
        pass


class ToolExecutionTracker:
    """Tracks tool execution to prevent duplicate calls."""

    _executed: set[str] = field(default_factory=set)

    @staticmethod
    def key(call_id: str | None, name: str, arguments: Any | None) -> str:
        """Generate execution key."""
        return f"{call_id or 'none'}:{name}:{json.dumps(arguments, sort_keys=True) if arguments else 'null'}"

    def try_get_completed(self, key: str) -> ToolResult | None:
        """Check if tool execution is already completed."""
        # Simplified - real implementation would store results
        return None

    def try_start(self, key: str) -> bool:
        """Try to start tool execution, returns False if already running."""
        if key in self._executed:
            return False
        self._executed.add(key)
        return True

    def complete(self, key: str, result: ToolResult) -> None:
        """Mark tool execution as completed."""
        pass  # Result already tracked internally

    def has_started(self) -> bool:
        """Check if any tool has started."""
        return len(self._executed) > 0


@dataclass
class ToolResult:
    """Result of tool execution."""

    result: Any | None
    error: str | None = None


# Placeholder types - will be imported from actual modules
LlmProvider = Any
HttpClient = Any
ILlmAdapter = Any
IToolCallingLlmAdapter = Any
ToolContext = Any
RegisteredTool = Any
AiChatSettings = Any
AiSettingsStore = Any
MemoryContext = Any
PromptBuildOptions = Any
ContextBudgetOptions = Any
ContextBudgetResult = Any
ContextBudgeter = Any
ChatMessageInput = Any
StreamingMessageTextProjector = Any
TextChunkCoalescer = Any
LlmUsageInfo = Any
AgentTraceUsage = Any
IPetActions = Any


# =============================================================================
# Agent Engine
# =============================================================================


class AgentEngine:
    """Agent Engine - Executes complete dialogue loop.

    In the backend, executes the complete dialogue loop:
    - Read configuration and secrets
    - Assemble personality/memory/skills/emotion/tools prompts
    - Streaming LLM calls
    - Protocol parsing
    - Multi-round Tool Calling
    - Replica distribution and final persistence

    Corresponds to the migration of frontend services/agent/engine.ts responsibilities.
    """

    # Single round LLM call timeout (seconds), consistent with ChatService upper limit
    CALL_TIMEOUT_SECONDS: Final[int] = ChatService.TIMEOUT_SECONDS

    _MAX_CONTEXT_ROUNDS: Final[int] = 12
    _DEFAULT_CONTEXT_TOKENS: Final[int] = 12_000
    _DEFAULT_RESERVED_OUTPUT_TOKENS: Final[int] = 2_000

    def __init__(
        self,
        http: HttpClient,
        config: ConfigStore,
        chat: ChatService,
        tools: ToolRegistry,
        skills: SkillService,
        emotion: EmotionManager,
        memory: MemoryService,
        pet: IPetActions | None,
        motion_names: Callable[[], list[str]],
        expression_names: Callable[[], list[str]],
        max_tool_iterations: int = 5,
        session_coordinator: AgentSessionCoordinator | None = None,
        trace: AgentTraceSink | None = None,
        adapter_factory: Callable[[LlmProvider, HttpClient], ILlmAdapter] | None = None,
    ) -> None:
        self._http = http
        self._config = config
        self._chat = chat
        self._tools = tools
        self._skills = skills
        self._emotion = emotion
        self._memory = memory
        self._pet = pet
        self._motion_names = motion_names
        self._expression_names = expression_names

        if max_tool_iterations <= 0:
            raise ValueError("Tool iteration limit must be positive")
        self._max_tool_iterations = max_tool_iterations

        self._session_coordinator = session_coordinator or AgentSessionCoordinator()
        self._trace = trace or AgentTraceSink.noop()
        self._adapter_factory = adapter_factory or self._default_adapter_factory

    @staticmethod
    def _default_adapter_factory(provider: LlmProvider, http: HttpClient) -> ILlmAdapter:
        """Default adapter factory - delegates to LlmClient."""
        # Import here to avoid circular dependency
        from ..chat.llm_client import LlmClient
        return LlmClient.create_adapter(provider, http)

    async def run_async(
        self,
        user_text: str,
        session_id: str,
        callbacks: AgentCallbacks,
        cancellation_token: asyncio.CancelledError | None = None,
    ) -> ProtocolMessage:
        """Execute one agent dialogue loop.

        Returns the final text message; raises OperationCanceledException on session cancellation.

        Args:
            user_text: User input text
            session_id: Session identifier
            callbacks: Callback collection
            cancellation_token: Optional cancellation token

        Returns:
            ProtocolMessage with the final response

        Raises:
            ValueError: If user_text is empty or callbacks is None
            OperationCanceledException: If session is cancelled
            TimeoutError: If LLM call times out
        """
        if not user_text or user_text.strip() == "":
            raise ValueError("Message content cannot be empty")
        if callbacks is None:
            raise ValueError("Callbacks cannot be None")

        session = self._session_coordinator.start(session_id, cancellation_token)
        run_token = session.cancellation_token
        run_clock_start = time.perf_counter()

        self._write_trace(
            session_id=session_id,
            operation="run",
            duration_ms=0,
            iteration=None,
            tool_name=None,
            status="started",
        )

        def set_state(state: AgentRunState) -> None:
            if callbacks.on_state:
                callbacks.on_state(state)

        set_state(AgentRunState.THINKING)

        # 1. Read AI and user custom persona configuration (secrets only flow in backend)
        config_clock_start = time.perf_counter()
        chat_settings = self._read_chat_settings()
        provider = chat_settings["provider"]
        base_url = chat_settings["base_url"]
        api_key = chat_settings["api_key"]
        model = chat_settings["model"]
        user_persona = chat_settings["persona"]

        if not base_url or not api_key or not model:
            self._write_trace(
                session_id=session_id,
                operation="config",
                duration_ms=int((time.perf_counter() - config_clock_start) * 1000),
                iteration=None,
                tool_name=None,
                status="error",
                failure_category="invalid_config",
            )
            raise ValueError("LLM parameters not fully configured (API Base, API Key, or Model missing)")

        provider_kind = self._parse_provider(provider)
        self._write_trace(
            session_id=session_id,
            operation="config",
            duration_ms=int((time.perf_counter() - config_clock_start) * 1000),
            iteration=None,
            tool_name=None,
            status="completed",
        )

        # 2. Assemble static context: recent dialogue / layered memory / emotion / actions / expressions / skills / tools
        context_clock_start = time.perf_counter()
        recent = self._normalize_recent_history(self._chat.get_history(self._MAX_CONTEXT_ROUNDS * 2, 0))

        try:
            memory_context = await self._memory.build_context_async(user_text, recent, run_token)
        except Exception as exception:
            self._write_trace(
                session_id=session_id,
                operation="context",
                duration_ms=int((time.perf_counter() - context_clock_start) * 1000),
                iteration=None,
                tool_name=None,
                status="error",
                failure_category=self._failure_category(exception),
            )
            raise

        current_emotion = self._emotion.current_type
        motions = self._motion_names()
        expressions = self._expression_names()
        available_tool_names = {tool.name for tool in self._tools.list_enabled()}
        skills_prompt = self._skills.build_skills_prompt(available_tool_names)

        # Build prompt options
        personal_memories = list(dict.fromkeys([
            item.get("persona_summary") or item.get("canonical_summary") or item.get("content", "")
            for item in memory_context.personal
        ] + [atom.get("content", "") for atom in memory_context.atoms]))[:6]

        related_knowledge = [
            item.get("content", "")
            for item in memory_context.knowledge
            if item.get("awareness") != "recovered"
        ]

        recovered_knowledge = [
            item.get("content", "")
            for item in memory_context.knowledge
            if item.get("awareness") == "recovered"
        ]

        memory_echoes = [item.get("content", "") for item in memory_context.echoes]

        prompt_options = {
            "user_persona": user_persona,
            "emotion": current_emotion,
            "personal_memories": personal_memories,
            "related_knowledge": related_knowledge,
            "recovered_knowledge": recovered_knowledge,
            "memory_echoes": memory_echoes,
            "available_motions": motions,
            "available_expressions": expressions,
            "skills_prompt": skills_prompt,
            "tools_json": self._tools.build_tools_prompt(),
        }

        budget_options = {
            "max_input_tokens": self._read_config_int("agent_context_tokens", self._DEFAULT_CONTEXT_TOKENS, 512, 128_000),
            "reserved_output_tokens": self._read_config_int(
                "agent_reserved_output_tokens", self._DEFAULT_RESERVED_OUTPUT_TOKENS, 128, 64_000
            ),
        }

        initial_budget = self._build_context_budget(prompt_options, recent + [("user", user_text)], user_text, budget_options)
        system_prompt = initial_budget["system_prompt"]

        self._write_trace(
            session_id=session_id,
            operation="context",
            duration_ms=int((time.perf_counter() - context_clock_start) * 1000),
            iteration=None,
            tool_name=None,
            status="completed",
        )

        # 3. Prepare working history: recent N messages + current input (sliding window truncation)
        working = [(msg["role"], msg["content"]) for msg in initial_budget["messages"]]
        execution_tracker = ToolExecutionTracker()
        final_message = ProtocolMessage(text="", emotion=None, expression=None, action=None)
        current_iteration = -1

        try:
            adapter = self._adapter_factory(provider_kind, self._http)

            async def execute_tool_async(
                name: str,
                arguments: Any | None,
                token: asyncio.CancelledError | None,
                call_id: str | None = None,
            ) -> ToolResult:
                nonlocal current_iteration
                if run_token:
                    # Check cancellation
                    pass

                execution_key = ToolExecutionTracker.key(call_id, name, arguments)
                previous = execution_tracker.try_get_completed(execution_key)
                if previous is not None:
                    self._write_trace(
                        session_id=session_id,
                        operation="tool",
                        duration_ms=0,
                        iteration=current_iteration,
                        tool_name=name,
                        status="blocked",
                        failure_category="duplicate",
                    )
                    return ToolResult(result=None, error=f"Tool call {name} already executed, prevented duplicate side effects")

                if not execution_tracker.try_start(execution_key):
                    self._write_trace(
                        session_id=session_id,
                        operation="tool",
                        duration_ms=0,
                        iteration=current_iteration,
                        tool_name=name,
                        status="blocked",
                        failure_category="duplicate",
                    )
                    return ToolResult(result=None, error=f"Tool call {name} already executing")

                tool_clock_start = time.perf_counter()
                self._write_trace(
                    session_id=session_id,
                    operation="tool",
                    duration_ms=0,
                    iteration=current_iteration,
                    tool_name=name,
                    status="started",
                )

                try:
                    if callbacks.on_tool_executing:
                        callbacks.on_tool_executing(name, arguments)

                    tool_context = ToolContext(
                        session_id=session_id,
                        cancellation_token=token,
                        approve=callbacks.request_approval,
                    )

                    result = await self._tools.execute_async(name, arguments, tool_context)
                    execution_tracker.complete(execution_key, result)

                    if callbacks.on_tool_executed:
                        callbacks.on_tool_executed(name, result.result, result.error)

                    self._write_trace(
                        session_id=session_id,
                        operation="tool",
                        duration_ms=int((time.perf_counter() - tool_clock_start) * 1000),
                        iteration=current_iteration,
                        tool_name=name,
                        status="completed" if result.error is None else "error",
                        failure_category=None if result.error is None else "tool_error",
                    )
                    return result
                except Exception as exception:
                    self._write_trace(
                        session_id=session_id,
                        operation="tool",
                        duration_ms=int((time.perf_counter() - tool_clock_start) * 1000),
                        iteration=current_iteration,
                        tool_name=name,
                        status="error",
                        failure_category=self._failure_category(exception),
                    )
                    raise

            for iteration in range(self._max_tool_iterations):
                current_iteration = iteration
                if run_token:
                    # Check cancellation
                    pass

                round_budget = self._build_context_budget(prompt_options, working, user_text, budget_options)
                request_messages = round_budget["messages"]

                projector = StreamingMessageTextProjector()
                coalescer = TextChunkCoalescer()
                raw_response_text = ""
                emitted_text = False

                def emit_text(text: str) -> None:
                    nonlocal emitted_text
                    if not text:
                        return
                    emitted_text = True
                    if callbacks.on_text_chunk:
                        callbacks.on_text_chunk(text)

                # Create timeout
                timeout_seconds = self.CALL_TIMEOUT_SECONDS

                set_state(AgentRunState.STREAMING)

                def on_chunk(chunk: str) -> None:
                    nonlocal raw_response_text
                    raw_response_text += chunk
                    projection = projector.push(chunk)
                    if projection.is_correction and callbacks.on_text_correction:
                        callbacks.on_text_correction(projection.full_text)
                    batch = coalescer.push(projection.delta)
                    if batch:
                        emit_text(batch)

                trace_usage = None

                def on_usage(usage: LlmUsageInfo) -> None:
                    nonlocal trace_usage
                    trace_usage = {
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                        "cached_tokens": usage.cached_tokens,
                        "cache_hit_rate": usage.cache_hit_rate,
                        "model": usage.model,
                    }
                    if callbacks.on_usage:
                        callbacks.on_usage(
                            AgentUsage(
                                prompt_tokens=usage.prompt_tokens,
                                completion_tokens=usage.completion_tokens,
                                total_tokens=usage.total_tokens,
                                cached_tokens=usage.cached_tokens,
                                cache_hit_rate=usage.cache_hit_rate,
                                duration_ms=usage.duration_ms,
                                model=usage.model,
                            )
                        )

                enabled_tools = self._tools.list_enabled()
                llm_clock_start = time.perf_counter()
                raw = ""

                try:
                    # Check if adapter supports tool calling
                    if hasattr(adapter, "stream_with_tools_async"):
                        try:
                            raw = await adapter.stream_with_tools_async(
                                base_url=base_url.rstrip("/"),
                                api_key=api_key,
                                model=model,
                                system_prompt=system_prompt,
                                messages=request_messages,
                                tools=enabled_tools,
                                execute_tool=execute_tool_async,
                                on_chunk=on_chunk,
                                on_usage=on_usage,
                                cancellation_token=run_token,
                            )
                        except Exception as e:
                            if type(e).__name__ == "ToolsUnsupportedException" and not execution_tracker.has_started():
                                # Fallback to non-tool streaming
                                raw_response_text = ""
                                projector.reset()
                                coalescer.reset()
                                raw = await adapter.stream_async(
                                    base_url=base_url.rstrip("/"),
                                    api_key=api_key,
                                    model=model,
                                    system_prompt=system_prompt,
                                    messages=request_messages,
                                    on_chunk=on_chunk,
                                    on_usage=on_usage,
                                    cancellation_token=run_token,
                                )
                    else:
                        raw = await adapter.stream_async(
                            base_url=base_url.rstrip("/"),
                            api_key=api_key,
                            model=model,
                            system_prompt=system_prompt,
                            messages=request_messages,
                            on_chunk=on_chunk,
                            on_usage=on_usage,
                            cancellation_token=run_token,
                        )
                except Exception as exception:
                    self._write_trace(
                        session_id=session_id,
                        operation="llm",
                        duration_ms=int((time.perf_counter() - llm_clock_start) * 1000),
                        iteration=iteration,
                        tool_name=None,
                        status="error",
                        failure_category=self._failure_category(exception),
                        usage=trace_usage,
                    )
                    raise

                self._write_trace(
                    session_id=session_id,
                    operation="llm",
                    duration_ms=int((time.perf_counter() - llm_clock_start) * 1000),
                    iteration=iteration,
                    tool_name=None,
                    status="completed",
                    failure_category=None,
                    usage=trace_usage,
                )

                # Flush remaining text
                final_batch = await coalescer.flush_async(run_token)
                if final_batch:
                    emit_text(final_batch)

                if run_token:
                    # Check cancellation
                    pass

                set_state(AgentRunState.STREAMING)

                # Extract motion markers and trigger pet playback, then do complete protocol parsing
                response_text = raw if raw else raw_response_text
                stripped, marker_motions = motion_extract(response_text)

                for motion in marker_motions:
                    try:
                        if self._pet:
                            self._pet.play_motion_by_name(motion)
                    except Exception:
                        # Ignore if pet not loaded
                        pass

                # Parse complete protocol
                items = self._parse_protocol_items(stripped)
                correction = projector.complete(items)

                if correction.is_correction and callbacks.on_text_correction:
                    callbacks.on_text_correction(correction.full_text)
                else:
                    correction_batch = await coalescer.flush_async(run_token)
                    if correction_batch and callbacks.on_text_correction:
                        callbacks.on_text_correction(correction_batch)

                has_tool_call = False

                for item in items:
                    if isinstance(item, dict) and item.get("type") == "tool_call":
                        # Tool call
                        has_tool_call = True
                        set_state(AgentRunState.TOOL_EXECUTING)

                        call = ProtocolToolCall(
                            id=item.get("id", ""),
                            name=item.get("name", ""),
                            arguments=item.get("arguments"),
                        )

                        result = await execute_tool_async(call.name, call.arguments, run_token, call.id)

                        working.append(("assistant", self._serialize_tool_call(call)))
                        working.append((
                            "user",
                            f"【系统工具执行反馈 - {call.name}】:\n" + json.dumps({
                                "id": call.id,
                                "name": call.name,
                                "result": result.result,
                                "error": result.error,
                            }, ensure_ascii=False)
                        ))

                        set_state(AgentRunState.THINKING)
                    elif isinstance(item, dict) and item.get("type") == "message":
                        # Protocol message
                        if not has_tool_call:
                            final_message = ProtocolMessage(
                                text=item.get("text", ""),
                                emotion=item.get("emotion"),
                                expression=item.get("expression"),
                                action=item.get("action"),
                            )
                            self._dispatch_effects(final_message, callbacks)

                # If no new tool call triggered this round, we have the final reply
                if not has_tool_call:
                    break

                if iteration == self._max_tool_iterations - 1:
                    raise AgentToolRoundsExceededException(self._max_tool_iterations)

            if not final_message.text:
                raise ValueError("Agent did not produce a final response")

            set_state(AgentRunState.IDLE)

            # Persist: only save the final round of user-visible dialogue (plain text, no protocol JSON)
            self._chat.save_message("user", user_text)
            self._chat.save_message("assistant", final_message.text)

            if callbacks.on_complete:
                callbacks.on_complete(final_message)

            self._write_trace(
                session_id=session_id,
                operation="run",
                duration_ms=int((time.perf_counter() - run_clock_start) * 1000),
                iteration=None,
                tool_name=None,
                status="completed",
            )

            return final_message

        except asyncio.CancelledError:
            if not cancellation_token:
                # Non-user cancellation (timeout): convert to readable error
                self._write_trace(
                    session_id=session_id,
                    operation="run",
                    duration_ms=int((time.perf_counter() - run_clock_start) * 1000),
                    iteration=None,
                    tool_name=None,
                    status="error",
                    failure_category="timeout",
                )
                raise TimeoutError(f"Response timeout ({self.CALL_TIMEOUT_SECONDS}s), please try again later")
            else:
                set_state(AgentRunState.IDLE)
                self._write_trace(
                    session_id=session_id,
                    operation="run",
                    duration_ms=int((time.perf_counter() - run_clock_start) * 1000),
                    iteration=None,
                    tool_name=None,
                    status="cancelled",
                    failure_category="cancelled",
                )
                raise
        except Exception as exception:
            set_state(AgentRunState.ERROR)
            self._write_trace(
                session_id=session_id,
                operation="run",
                duration_ms=int((time.perf_counter() - run_clock_start) * 1000),
                iteration=None,
                tool_name=None,
                status="error",
                failure_category=self._failure_category(exception),
            )
            raise

    def _read_chat_settings(self) -> dict[str, str]:
        """Read chat settings from config store."""
        # Stub implementation - real implementation reads from AiSettingsStore
        return {
            "provider": "openai",
            "base_url": "",
            "api_key": "",
            "model": "",
            "persona": "",
        }

    def _parse_provider(self, provider: str) -> LlmProvider:
        """Parse provider string to enum."""
        # Stub implementation
        return provider

    def _normalize_recent_history(self, history: list[Any]) -> list[tuple[str, str]]:
        """Normalize recent history to role/content tuples."""
        # Stub implementation
        return [(msg.get("role", ""), msg.get("content", "")) for msg in history]

    def _read_config_int(self, key: str, default: int, min_val: int, max_val: int) -> int:
        """Read integer config value with bounds checking."""
        # Stub implementation - real implementation reads from config store
        return default

    def _build_context_budget(
        self,
        prompt_options: dict[str, Any],
        messages: list[tuple[str, str]],
        user_text: str,
        budget_options: dict[str, int],
    ) -> ContextBudgetResult:
        """Build context budget."""
        # Stub implementation - real implementation uses ContextBudgeter
        return {
            "system_prompt": "",
            "messages": [{"role": role, "content": content} for role, content in messages],
        }

    def _failure_category(self, exception: Exception) -> str:
        """Categorize failure for tracing."""
        exc_name = type(exception).__name__
        if "timeout" in exc_name.lower() or isinstance(exception, TimeoutError):
            return "timeout"
        if "cancelled" in exc_name.lower() or isinstance(exception, asyncio.CancelledError):
            return "cancelled"
        if "connection" in exc_name.lower() or "network" in exc_name.lower():
            return "network"
        if "auth" in exc_name.lower() or "permission" in exc_name.lower():
            return "auth"
        return "unknown"

    def _write_trace(
        self,
        session_id: str,
        operation: str,
        duration_ms: int,
        iteration: int | None,
        tool_name: str | None,
        status: str,
        failure_category: str | None = None,
        usage: Any | None = None,
    ) -> None:
        """Write trace entry."""
        self._trace.write(
            session_id=session_id,
            operation=operation,
            duration_ms=duration_ms,
            iteration=iteration,
            tool_name=tool_name,
            status=status,
            failure_category=failure_category,
            usage=usage,
        )

    def _dispatch_effects(self, message: ProtocolMessage, callbacks: AgentCallbacks) -> None:
        """Dispatch message附加的情绪、表情、动作副作用."""
        # Stub implementation - real implementation updates emotion/expression/action
        pass

    def _serialize_tool_call(self, call: ProtocolToolCall) -> str:
        """Serialize tool call for history."""
        return json.dumps({
            "id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }, ensure_ascii=False)

    def _parse_protocol_items(self, text: str) -> list[dict[str, Any]]:
        """Parse protocol items from text."""
        # Stub implementation - real implementation uses StreamingJsonParser
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            return [data]
        except json.JSONDecodeError:
            return [{"type": "message", "text": text}]
