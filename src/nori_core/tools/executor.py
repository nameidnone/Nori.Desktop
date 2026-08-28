"""Tool executor for running tools with proper error handling and context."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .registry import ITool, ToolPermissionLevel, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionContext:
    """Runtime context for tool execution.
    
    Attributes:
        user_id: ID of the user invoking the tool
        session_id: Current chat session ID
        approval_granted: Set of tool names that have been approved
        config: Configuration dictionary
        services: Dictionary of available services
        cancellation_token: asyncio.Event for cancellation
    """
    
    user_id: str
    session_id: str
    approval_granted: Set[str] = field(default_factory=set)
    config: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    cancellation_token: Optional[asyncio.Event] = None
    
    def has_approval(self, tool_name: str) -> bool:
        """Check if a tool has been approved for execution."""
        return tool_name in self.approval_granted
    
    def grant_approval(self, tool_name: str) -> None:
        """Grant approval for a tool."""
        self.approval_granted.add(tool_name)
    
    @property
    def is_cancelled(self) -> bool:
        """Check if the operation has been cancelled."""
        if self.cancellation_token is None:
            return False
        return self.cancellation_token.is_set()


@dataclass
class ToolExecutionResult:
    """Result of a tool execution.
    
    Attributes:
        success: Whether the execution was successful
        result: The result value (if successful)
        error: Error message (if failed)
        error_type: Type of error that occurred
        execution_time_ms: Time taken to execute in milliseconds
        tool_name: Name of the tool that was executed
        requires_approval: Whether this tool requires user approval
        approval_pending: Whether approval is currently pending
    """
    
    success: bool
    result: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time_ms: float = 0.0
    tool_name: str = ""
    requires_approval: bool = False
    approval_pending: bool = False
    
    @classmethod
    def success_result(cls, result: Any, tool_name: str, execution_time_ms: float) -> "ToolExecutionResult":
        """Create a successful result."""
        return cls(
            success=True,
            result=result,
            tool_name=tool_name,
            execution_time_ms=execution_time_ms,
        )
    
    @classmethod
    def failure_result(
        cls,
        error: str,
        tool_name: str,
        error_type: str = "Error",
        execution_time_ms: float = 0.0
    ) -> "ToolExecutionResult":
        """Create a failed result."""
        return cls(
            success=False,
            error=error,
            error_type=error_type,
            tool_name=tool_name,
            execution_time_ms=execution_time_ms,
        )
    
    @classmethod
    def approval_pending_result(cls, tool_name: str) -> "ToolExecutionResult":
        """Create an approval-pending result."""
        return cls(
            success=False,
            tool_name=tool_name,
            requires_approval=True,
            approval_pending=True,
            error="User approval required",
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "error_type": self.error_type,
            "execution_time_ms": self.execution_time_ms,
            "tool_name": self.tool_name,
            "requires_approval": self.requires_approval,
            "approval_pending": self.approval_pending,
        }


class ToolExecutor:
    """Executes tools with proper validation, error handling, and permission checks.
    
    Responsibilities:
    - Validate tool parameters before execution
    - Check permission levels and handle approval flow
    - Execute tools with timeout protection
    - Capture and wrap exceptions
    - Track execution metrics
    
    Usage:
        executor = ToolExecutor(registry)
        
        context = ToolExecutionContext(user_id="user123", session_id="session456")
        result = await executor.execute("tool_name", context, param1=value1)
        
        if result.success:
            print(f"Result: {result.result}")
        else:
            print(f"Error: {result.error}")
    """
    
    def __init__(self, registry: ToolRegistry):
        """Initialize the executor with a tool registry.
        
        Args:
            registry: The ToolRegistry containing available tools
        """
        self._registry = registry
        self._rate_limit_tracker: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()
    
    async def execute(
        self,
        tool_name: str,
        context: ToolExecutionContext,
        **kwargs: Any
    ) -> ToolExecutionResult:
        """Execute a tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            context: Execution context
            **kwargs: Parameters to pass to the tool
            
        Returns:
            ToolExecutionResult with success/failure status
        """
        start_time = time.time()
        
        # Get the tool
        tool = self._registry.get(tool_name)
        
        if tool is None:
            return ToolExecutionResult.failure_result(
                f"Tool '{tool_name}' not found",
                tool_name,
                "NotFoundError",
            )
        
        # Check for cancellation
        if context.is_cancelled:
            return ToolExecutionResult.failure_result(
                "Operation cancelled",
                tool_name,
                "CancelledError",
            )
        
        # Check permission level
        permission_level = tool.metadata.permission_level
        
        if permission_level != ToolPermissionLevel.NONE:
            if not context.has_approval(tool_name):
                # Return approval pending
                logger.info(f"Tool '{tool_name}' requires {permission_level.value} approval")
                return ToolExecutionResult.approval_pending_result(tool_name)
        
        # Check rate limit
        rate_limit = tool.metadata.rate_limit
        if rate_limit > 0:
            if not await self._check_rate_limit(tool_name, rate_limit):
                return ToolExecutionResult.failure_result(
                    f"Rate limit exceeded for tool '{tool_name}'",
                    tool_name,
                    "RateLimitExceeded",
                )
        
        # Validate parameters
        validation_error = self._validate_parameters(tool, kwargs)
        if validation_error:
            return ToolExecutionResult.failure_result(
                validation_error,
                tool_name,
                "ValidationError",
            )
        
        # Execute with timeout
        timeout = tool.metadata.timeout_seconds
        
        try:
            if timeout > 0:
                result = await asyncio.wait_for(
                    tool.execute_async(**kwargs),
                    timeout=timeout
                )
            else:
                result = await tool.execute_async(**kwargs)
            
            execution_time = (time.time() - start_time) * 1000
            
            logger.debug(
                f"Tool '{tool_name}' executed successfully in {execution_time:.2f}ms"
            )
            
            return ToolExecutionResult.success_result(result, tool_name, execution_time)
        
        except asyncio.TimeoutError:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Tool '{tool_name}' timed out after {timeout}s")
            
            return ToolExecutionResult.failure_result(
                f"Tool execution timed out after {timeout} seconds",
                tool_name,
                "TimeoutError",
                execution_time,
            )
        
        except asyncio.CancelledError:
            execution_time = (time.time() - start_time) * 1000
            logger.info(f"Tool '{tool_name}' was cancelled")
            
            return ToolExecutionResult.failure_result(
                "Tool execution was cancelled",
                tool_name,
                "CancelledError",
                execution_time,
            )
        
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Tool '{tool_name}' failed: {e}", exc_info=True)
            
            return ToolExecutionResult.failure_result(
                str(e),
                tool_name,
                type(e).__name__,
                execution_time,
            )
    
    def _validate_parameters(self, tool: ITool, kwargs: Dict[str, Any]) -> Optional[str]:
        """Validate tool parameters against metadata.
        
        Args:
            tool: The tool instance
            kwargs: Provided parameters
            
        Returns:
            Error message if validation fails, None if valid
        """
        metadata = tool.metadata
        
        # Check required parameters
        missing = []
        for param in metadata.required_parameters:
            if param.name not in kwargs or kwargs.get(param.name) is None:
                if param.default is None:
                    missing.append(param.name)
        
        if missing:
            return f"Missing required parameters: {', '.join(missing)}"
        
        # Check for unknown parameters
        valid_names = set(metadata.parameter_names)
        unknown = set(kwargs.keys()) - valid_names
        
        if unknown:
            return f"Unknown parameters: {', '.join(unknown)}"
        
        # Check choices for parameters with constraints
        for param in metadata.parameters:
            if param.choices and param.name in kwargs:
                value = kwargs[param.name]
                if value not in param.choices:
                    return (
                        f"Invalid value '{value}' for parameter '{param.name}'. "
                        f"Valid choices: {param.choices}"
                    )
        
        return None
    
    async def _check_rate_limit(self, tool_name: str, rate_limit: int) -> bool:
        """Check if the tool call is within rate limits.
        
        Uses a sliding window approach to track calls per minute.
        
        Args:
            tool_name: Name of the tool
            rate_limit: Maximum calls per minute
            
        Returns:
            True if within limit, False if exceeded
        """
        async with self._lock:
            now = time.time()
            window_start = now - 60.0  # 1 minute window
            
            # Initialize or get tracker for this tool
            if tool_name not in self._rate_limit_tracker:
                self._rate_limit_tracker[tool_name] = []
            
            # Remove old entries outside the window
            timestamps = self._rate_limit_tracker[tool_name]
            timestamps[:] = [ts for ts in timestamps if ts > window_start]
            
            # Check if we're at the limit
            if len(timestamps) >= rate_limit:
                return False
            
            # Add current call
            timestamps.append(now)
            return True
    
    async def request_approval(
        self,
        tool_name: str,
        context: ToolExecutionContext,
        reason: Optional[str] = None
    ) -> bool:
        """Request user approval for a tool execution.
        
        This is typically called by higher-level code when an approval-pending
        result is received.
        
        Args:
            tool_name: Name of the tool requiring approval
            context: Execution context (will be updated with approval)
            reason: Optional reason for the approval request
            
        Returns:
            True if approval was granted, False otherwise
            
        Note:
            This is a stub - real implementation would show UI dialog
        """
        tool = self._registry.get(tool_name)
        
        if tool is None:
            return False
        
        permission_level = tool.metadata.permission_level
        
        logger.info(
            f"Approval requested for '{tool_name}' ({permission_level.value})"
            + (f": {reason}" if reason else "")
        )
        
        # In a real implementation, this would:
        # 1. Show a dialog to the user
        # 2. Wait for user response
        # 3. Update context.approval_granted if approved
        
        # For now, auto-approve NOTIFY level
        if permission_level == ToolPermissionLevel.NOTIFY:
            context.grant_approval(tool_name)
            return True
        
        return False
    
    def get_tool_schemas_with_permissions(
        self,
        max_permission: ToolPermissionLevel = ToolPermissionLevel.CONFIRM
    ) -> List[Dict[str, Any]]:
        """Get tool schemas filtered by maximum permission level.
        
        Args:
            max_permission: Maximum permission level to include
            
        Returns:
            List of tool schemas
        """
        return self._registry.get_tool_schemas(max_permission)
