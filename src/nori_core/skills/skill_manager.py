"""Skill manager for registering, discovering, and executing skills."""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Type

from .skill_definition import (
    SkillCategory,
    SkillContext,
    SkillDefinition,
    SkillFunc,
    SkillParameter,
)

logger = logging.getLogger(__name__)


class SkillManager:
    """Central registry and manager for all available skills.
    
    Responsibilities:
    - Register skill definitions (manual or auto-discovery)
    - Provide skill lookup by name or category
    - Execute skills with proper context
    - Support hot-reloading of skills
    - Manage skill lifecycle
    
    Usage:
        manager = SkillManager()
        await manager.initialize()
        
        # Register a skill
        manager.register(my_skill_def)
        
        # Execute a skill
        result = await manager.execute("skill_name", context, arg1=value1)
        
        # List available skills
        skills = manager.list_skills(category=SkillCategory.TEXT_PROCESSING)
    """
    
    def __init__(self):
        """Initialize the skill manager."""
        self._skills: Dict[str, SkillDefinition] = {}
        self._categories: Dict[SkillCategory, Set[str]] = {
            cat: set() for cat in SkillCategory
        }
        self._initialized = False
        self._lock = asyncio.Lock()
    
    @property
    def registered_skills(self) -> Dict[str, SkillDefinition]:
        """Get all registered skills."""
        return self._skills.copy()
    
    @property
    def skill_count(self) -> int:
        """Get the number of registered skills."""
        return len(self._skills)
    
    async def initialize(self, auto_discover: bool = True) -> None:
        """Initialize the skill manager.
        
        Args:
            auto_discover: Whether to automatically discover built-in skills
        """
        if self._initialized:
            logger.warning("SkillManager already initialized")
            return
        
        async with self._lock:
            if auto_discover:
                await self._discover_builtin_skills()
            
            self._initialized = True
            logger.info(f"SkillManager initialized with {self.skill_count} skills")
    
    async def _discover_builtin_skills(self) -> None:
        """Auto-discover and register built-in skills."""
        builtin_path = Path(__file__).parent / "builtin"
        
        if not builtin_path.exists():
            logger.debug("No builtin skills directory found")
            return
        
        try:
            for skill_file in builtin_path.glob("*.py"):
                if skill_file.name.startswith("_"):
                    continue
                
                module_name = f"nori_core.skills.builtin.{skill_file.stem}"
                
                try:
                    module = importlib.import_module(module_name)
                    
                    # Look for register_skills function
                    if hasattr(module, "register_skills"):
                        register_func = getattr(module, "register_skills")
                        if callable(register_func):
                            await register_func(self)
                            logger.debug(f"Registered skills from {module_name}")
                
                except Exception as e:
                    logger.error(f"Failed to load skill module {module_name}: {e}")
        
        except Exception as e:
            logger.error(f"Error discovering builtin skills: {e}")
    
    def register(
        self,
        definition: SkillDefinition,
        override: bool = False
    ) -> None:
        """Register a skill definition.
        
        Args:
            definition: The skill definition to register
            override: Whether to override an existing skill with the same name
            
        Raises:
            ValueError: If a skill with the same name already exists and override=False
        """
        if definition.name in self._skills and not override:
            raise ValueError(
                f"Skill '{definition.name}' is already registered. "
                "Use override=True to replace it."
            )
        
        self._skills[definition.name] = definition
        self._categories[definition.category].add(definition.name)
        
        logger.debug(f"Registered skill: {definition.name} ({definition.display_name})")
    
    def unregister(self, name: str) -> bool:
        """Unregister a skill by name.
        
        Args:
            name: Name of the skill to unregister
            
        Returns:
            True if the skill was unregistered, False if it didn't exist
        """
        if name not in self._skills:
            return False
        
        skill = self._skills.pop(name)
        self._categories[skill.category].discard(name)
        
        logger.debug(f"Unregistered skill: {name}")
        return True
    
    def get(self, name: str) -> Optional[SkillDefinition]:
        """Get a skill definition by name.
        
        Args:
            name: Name of the skill
            
        Returns:
            The skill definition, or None if not found
        """
        return self._skills.get(name)
    
    def has(self, name: str) -> bool:
        """Check if a skill is registered.
        
        Args:
            name: Name of the skill
            
        Returns:
            True if the skill exists, False otherwise
        """
        return name in self._skills
    
    def list_skills(
        self,
        category: Optional[SkillCategory] = None,
        include_hidden: bool = False
    ) -> List[SkillDefinition]:
        """List registered skills, optionally filtered by category.
        
        Args:
            category: Filter by category (None for all)
            include_hidden: Whether to include hidden skills
            
        Returns:
            List of matching skill definitions
        """
        skills = []
        
        for name, skill in self._skills.items():
            if category is not None and skill.category != category:
                continue
            if not include_hidden and skill.hidden:
                continue
            skills.append(skill)
        
        return sorted(skills, key=lambda s: s.display_name)
    
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAI-style tool schemas for all non-hidden skills.
        
        Returns:
            List of tool schemas suitable for LLM function calling
        """
        schemas = []
        
        for skill in self._skills.values():
            if not skill.hidden:
                schemas.append(skill.to_tool_schema())
        
        return schemas
    
    async def execute(
        self,
        name: str,
        context: SkillContext,
        **kwargs: Any
    ) -> Any:
        """Execute a skill by name.
        
        Args:
            name: Name of the skill to execute
            context: Runtime context for the skill
            **kwargs: Parameters to pass to the skill
            
        Returns:
            Result from the skill execution
            
        Raises:
            KeyError: If the skill is not found
            RuntimeError: If skill execution fails
        """
        skill = self.get(name)
        
        if skill is None:
            raise KeyError(f"Skill '{name}' not found")
        
        logger.debug(f"Executing skill: {name} with params: {list(kwargs.keys())}")
        
        try:
            result = await skill.execute(context, **kwargs)
            logger.debug(f"Skill '{name}' completed successfully")
            return result
        
        except asyncio.CancelledError:
            logger.info(f"Skill '{name}' was cancelled")
            raise
        
        except Exception as e:
            logger.error(f"Skill '{name}' failed: {e}")
            raise
    
    async def reload_skill(self, name: str) -> bool:
        """Reload a skill from its source module.
        
        Args:
            name: Name of the skill to reload
            
        Returns:
            True if the skill was reloaded, False if it didn't exist
        """
        skill = self.get(name)
        
        if skill is None:
            return False
        
        # Note: In a real implementation, this would reload the module
        # For now, just log that hot-reload is not fully implemented
        logger.warning(f"Hot-reload requested for '{name}' but not fully implemented")
        return True
    
    def create_context(
        self,
        user_id: str,
        session_id: str,
        config: Optional[Dict[str, Any]] = None,
        services: Optional[Dict[str, Any]] = None,
    ) -> SkillContext:
        """Create a new skill execution context.
        
        Args:
            user_id: ID of the user
            session_id: ID of the chat session
            config: Optional configuration dictionary
            services: Optional services dictionary
            
        Returns:
            New SkillContext instance
        """
        return SkillContext(
            user_id=user_id,
            session_id=session_id,
            config=config or {},
            services=services or {},
        )


# Global singleton instance (optional convenience)
_default_manager: Optional[SkillManager] = None


def get_default_manager() -> SkillManager:
    """Get or create the default global skill manager."""
    global _default_manager
    
    if _default_manager is None:
        _default_manager = SkillManager()
    
    return _default_manager
