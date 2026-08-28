"""Tool registry and metadata definitions for the Nori tools framework."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar, Union

# Type alias for async tool function
ToolFunc = Callable[..., Coroutine[Any, Any, Any]]


class ToolPermissionLevel(Enum):
    """Permission levels for tool execution requiring user approval."""
    
    NONE = "none"  # No approval needed
    NOTIFY = "notify"  # Just notify user
    CONFIRM = "confirm"  # Require explicit confirmation
    RESTRICTED = "restricted"  # High-risk, requires admin approval


class ToolCategory(Enum):
    """Categories of tools for organization."""
    
    FILE_OPERATIONS = "file_operations"
    WEB_TOOLS = "web_tools"
    SYSTEM_TOOLS = "system_tools"
    MEDIA_TOOLS = "media_tools"
    COMMUNICATION = "communication"
    CUSTOM = "custom"


@dataclass
class ToolParameter:
    """Definition of a single parameter for a tool.
    
    Attributes:
        name: Parameter name
        description: Human-readable description
        param_type: Python type hint (as string or type object)
        required: Whether this parameter is mandatory
        default: Default value if not required
        choices: Optional list of valid choices
    """
    
    name: str
    description: str
    param_type: Union[str, type] = "str"
    required: bool = True
    default: Any = None
    choices: Optional[List[Any]] = None
    
    def to_schema(self) -> Dict[str, Any]:
        """Convert to JSON Schema format for LLM tool calling."""
        schema: Dict[str, Any] = {
            "type": "string",  # Simplified - real impl would map types properly
            "description": self.description,
        }
        
        if self.choices:
            schema["enum"] = [str(c) for c in self.choices]
            
        return schema


@dataclass
class ToolMetadata:
    """Metadata describing a tool's capabilities and requirements.
    
    Attributes:
        name: Unique identifier for the tool
        display_name: Human-readable name
        description: Detailed description of what the tool does
        category: Tool category for organization
        permission_level: Required permission level for execution
        parameters: List of parameter definitions
        returns: Description of return value
        examples: List of example usage strings
        timeout_seconds: Maximum execution time (0 for no limit)
        rate_limit: Maximum calls per minute (0 for no limit)
    """
    
    name: str
    display_name: str
    description: str
    category: ToolCategory
    permission_level: ToolPermissionLevel = ToolPermissionLevel.NONE
    parameters: List[ToolParameter] = field(default_factory=list)
    returns: str = ""
    examples: List[str] = field(default_factory=list)
    timeout_seconds: int = 30
    rate_limit: int = 60
    
    def __post_init__(self):
        """Validate the metadata after initialization."""
        if not self.name:
            raise ValueError("Tool name cannot be empty")
        if not self.display_name:
            self.display_name = self.name
        if not self.description:
            raise ValueError(f"Tool '{self.name}' must have a description")
    
    @property
    def parameter_names(self) -> List[str]:
        """Get list of parameter names."""
        return [p.name for p in self.parameters]
    
    @property
    def required_parameters(self) -> List[ToolParameter]:
        """Get list of required parameters."""
        return [p for p in self.parameters if p.required]
    
    def to_tool_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI-style tool schema for LLM function calling."""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_schema()
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }


class ITool(ABC):
    """Abstract base class for all tools.
    
    Subclasses must implement:
    - metadata: ToolMetadata property
    - execute_async: Main execution method
    """
    
    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        """Get the tool's metadata."""
        pass
    
    @abstractmethod
    async def execute_async(self, **kwargs: Any) -> Any:
        """Execute the tool with the given parameters.
        
        Args:
            **kwargs: Parameters for the tool
            
        Returns:
            Tool execution result
            
        Raises:
            ToolExecutionError: If execution fails
            asyncio.TimeoutError: If execution times out
        """
        pass
    
    def __str__(self) -> str:
        """Return a human-readable summary of the tool."""
        params = ", ".join(p.name for p in self.metadata.parameters)
        return f"{self.metadata.display_name}({params}) - {self.metadata.description}"


class ToolRegistry:
    """Central registry for all available tools.
    
    Responsibilities:
    - Register tool instances
    - Provide tool lookup by name or category
    - Support filtering by permission level
    - Manage tool lifecycle
    
    Usage:
        registry = ToolRegistry()
        registry.register(my_tool)
        
        tool = registry.get("tool_name")
        tools = registry.list_by_category(ToolCategory.FILE_OPERATIONS)
    """
    
    def __init__(self):
        """Initialize the tool registry."""
        self._tools: Dict[str, ITool] = {}
        self._categories: Dict[ToolCategory, Dict[str, ITool]] = {
            cat: {} for cat in ToolCategory
        }
        self._lock = asyncio.Lock()
    
    @property
    def registered_tools(self) -> Dict[str, ITool]:
        """Get all registered tools."""
        return self._tools.copy()
    
    @property
    def tool_count(self) -> int:
        """Get the number of registered tools."""
        return len(self._tools)
    
    def register(self, tool: ITool, override: bool = False) -> None:
        """Register a tool instance.
        
        Args:
            tool: The tool instance to register
            override: Whether to override an existing tool with the same name
            
        Raises:
            ValueError: If a tool with the same name already exists and override=False
        """
        name = tool.metadata.name
        
        if name in self._tools and not override:
            raise ValueError(
                f"Tool '{name}' is already registered. "
                "Use override=True to replace it."
            )
        
        self._tools[name] = tool
        self._categories[tool.metadata.category][name] = tool
        
        # Log registration
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Registered tool: {name} ({tool.metadata.display_name})")
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool by name.
        
        Args:
            name: Name of the tool to unregister
            
        Returns:
            True if the tool was unregistered, False if it didn't exist
        """
        if name not in self._tools:
            return False
        
        tool = self._tools.pop(name)
        self._categories[tool.metadata.category].pop(name, None)
        
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Unregistered tool: {name}")
        return True
    
    def get(self, name: str) -> Optional[ITool]:
        """Get a tool by name.
        
        Args:
            name: Name of the tool
            
        Returns:
            The tool instance, or None if not found
        """
        return self._tools.get(name)
    
    def has(self, name: str) -> bool:
        """Check if a tool is registered.
        
        Args:
            name: Name of the tool
            
        Returns:
            True if the tool exists, False otherwise
        """
        return name in self._tools
    
    def list_by_category(
        self,
        category: ToolCategory,
        permission_filter: Optional[ToolPermissionLevel] = None
    ) -> List[ITool]:
        """List tools in a category, optionally filtered by permission level.
        
        Args:
            category: The category to filter by
            permission_filter: Only include tools with this permission level or lower
            
        Returns:
            List of matching tool instances
        """
        tools = list(self._categories[category].values())
        
        if permission_filter is not None:
            # Define permission hierarchy
            permission_order = [
                ToolPermissionLevel.NONE,
                ToolPermissionLevel.NOTIFY,
                ToolPermissionLevel.CONFIRM,
                ToolPermissionLevel.RESTRICTED,
            ]
            max_index = permission_order.index(permission_filter)
            tools = [
                t for t in tools
                if permission_order.index(t.metadata.permission_level) <= max_index
            ]
        
        return sorted(tools, key=lambda t: t.metadata.display_name)
    
    def get_tool_schemas(
        self,
        permission_filter: Optional[ToolPermissionLevel] = None
    ) -> List[Dict[str, Any]]:
        """Get OpenAI-style tool schemas for tools within permission level.
        
        Args:
            permission_filter: Maximum permission level to include
            
        Returns:
            List of tool schemas suitable for LLM function calling
        """
        schemas = []
        
        for tool in self._tools.values():
            if permission_filter is not None:
                permission_order = [
                    ToolPermissionLevel.NONE,
                    ToolPermissionLevel.NOTIFY,
                    ToolPermissionLevel.CONFIRM,
                    ToolPermissionLevel.RESTRICTED,
                ]
                tool_level = tool.metadata.permission_level
                if permission_order.index(tool_level) > permission_order.index(permission_filter):
                    continue
            
            schemas.append(tool.metadata.to_tool_schema())
        
        return schemas
    
    async def acquire(self, name: str) -> Optional[ITool]:
        """Thread-safe acquisition of a tool.
        
        Args:
            name: Name of the tool
            
        Returns:
            The tool instance, or None if not found
        """
        async with self._lock:
            return self.get(name)
