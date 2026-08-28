"""Skill definition types and context for the Nori skills system."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar, Union

# Type alias for async skill function
SkillFunc = Callable[..., Coroutine[Any, Any, Any]]


class SkillCategory(Enum):
    """Categories of skills for organization and filtering."""
    
    TEXT_PROCESSING = "text_processing"
    WEB_TOOLS = "web_tools"
    FILE_OPERATIONS = "file_operations"
    SYSTEM_TOOLS = "system_tools"
    MEDIA_TOOLS = "media_tools"
    CUSTOM = "custom"


@dataclass
class SkillParameter:
    """Definition of a single parameter for a skill.
    
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
            "type": "string",  # Simplified - in real impl would map types
            "description": self.description,
        }
        
        if self.choices:
            schema["enum"] = self.choices
            
        return schema


@dataclass
class SkillContext:
    """Runtime context passed to skill execution.
    
    Provides skills with access to external services and state.
    
    Attributes:
        user_id: ID of the user invoking the skill
        session_id: Current chat session ID
        config: Configuration dictionary
        services: Dictionary of available services
        cancellation_token: asyncio.Event for cancellation
    """
    
    user_id: str
    session_id: str
    config: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    cancellation_token: Optional[asyncio.Event] = None
    
    def get_service(self, name: str) -> Any:
        """Get a service by name, raising KeyError if not found."""
        return self.services[name]
    
    def has_service(self, name: str) -> bool:
        """Check if a service is available."""
        return name in self.services
    
    @property
    def is_cancelled(self) -> bool:
        """Check if the operation has been cancelled."""
        if self.cancellation_token is None:
            return False
        return self.cancellation_token.is_set()


@dataclass
class SkillDefinition:
    """Complete definition of a skill including metadata and implementation.
    
    Attributes:
        name: Unique identifier for the skill
        display_name: Human-readable name
        description: Detailed description of what the skill does
        category: Skill category for organization
        function: Async callable that implements the skill
        parameters: List of parameter definitions
        returns: Description of return value
        examples: List of example usage strings
        hidden: Whether to hide from skill listings (for internal skills)
    """
    
    name: str
    display_name: str
    description: str
    category: SkillCategory
    function: SkillFunc
    parameters: List[SkillParameter] = field(default_factory=list)
    returns: str = ""
    examples: List[str] = field(default_factory=list)
    hidden: bool = False
    
    def __post_init__(self):
        """Validate the skill definition after initialization."""
        if not self.name:
            raise ValueError("Skill name cannot be empty")
        if not self.display_name:
            self.display_name = self.name
        if not self.description:
            raise ValueError(f"Skill '{self.name}' must have a description")
    
    @property
    def parameter_names(self) -> List[str]:
        """Get list of parameter names."""
        return [p.name for p in self.parameters]
    
    @property
    def required_parameters(self) -> List[SkillParameter]:
        """Get list of required parameters."""
        return [p for p in self.parameters if p.required]
    
    @property
    def optional_parameters(self) -> List[SkillParameter]:
        """Get list of optional parameters."""
        return [p for p in self.parameters if not p.required]
    
    def to_tool_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI-style tool schema for LLM function calling.
        
        Returns:
            Dictionary compatible with OpenAI Chat Completions API tool format.
        """
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
    
    async def execute(
        self,
        context: SkillContext,
        **kwargs: Any
    ) -> Any:
        """Execute the skill with the given context and parameters.
        
        Args:
            context: Runtime context for the skill
            **kwargs: Parameters to pass to the skill function
            
        Returns:
            Result from the skill function
            
        Raises:
            asyncio.CancelledError: If operation was cancelled
            TypeError: If required parameters are missing
        """
        # Check for cancellation before starting
        if context.is_cancelled:
            raise asyncio.CancelledError("Skill execution cancelled")
        
        # Validate required parameters
        missing = []
        for param in self.required_parameters:
            if param.name not in kwargs or kwargs.get(param.name) is None:
                if param.default is None:
                    missing.append(param.name)
        
        if missing:
            raise TypeError(
                f"Missing required parameters for skill '{self.name}': {missing}"
            )
        
        # Add defaults for optional parameters
        for param in self.optional_parameters:
            if param.name not in kwargs:
                kwargs[param.name] = param.default
        
        # Execute the skill function
        try:
            result = await self.function(context=context, **kwargs)
            return result
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Wrap exceptions with skill context
            raise RuntimeError(f"Skill '{self.name}' failed: {e}") from e
    
    def __str__(self) -> str:
        """Return a human-readable summary of the skill."""
        params = ", ".join(p.name for p in self.parameters)
        return f"{self.display_name}({params}) - {self.description}"
