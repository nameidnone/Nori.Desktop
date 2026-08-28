"""Built-in text summarization skill for Nori."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..skill_definition import (
    SkillCategory,
    SkillContext,
    SkillDefinition,
    SkillParameter,
)

logger = logging.getLogger(__name__)


async def summarize_text(
    context: SkillContext,
    text: str,
    max_length: Optional[int] = None,
    style: str = "concise"
) -> str:
    """Summarize a given text.
    
    Args:
        context: Skill execution context
        text: The text to summarize
        max_length: Maximum length of summary in words (optional)
        style: Summary style - 'concise', 'detailed', or 'bullet_points'
        
    Returns:
        Summarized text
    """
    # Get LLM service if available
    llm_service = context.services.get("llm_adapter")
    
    if llm_service is None:
        # Fallback: simple extractive summary (first N sentences)
        sentences = text.split(".")
        limit = 3 if max_length is None else max(max_length // 20, 1)
        summary = ".".join(sentences[:limit]).strip()
        if summary and not summary.endswith("."):
            summary += "."
        return summary
    
    # Build prompt based on style
    style_prompts = {
        "concise": "Provide a brief, one-paragraph summary.",
        "detailed": "Provide a comprehensive summary covering all key points.",
        "bullet_points": "Provide a summary as bullet points highlighting key information.",
    }
    
    style_prompt = style_prompts.get(style, style_prompts["concise"])
    
    length_constraint = ""
    if max_length:
        length_constraint = f" Keep the summary under {max_length} words."
    
    prompt = f"""Please summarize the following text:

{text}

{style_prompt}{length_constraint}
"""
    
    try:
        # Call LLM for abstractive summary
        # Note: This assumes llm_service has a complete method
        if hasattr(llm_service, "complete"):
            result = await llm_service.complete(prompt)
            return result.text if hasattr(result, "text") else str(result)
        else:
            logger.warning("LLM service does not have 'complete' method")
            raise ValueError("LLM service incompatible")
    
    except Exception as e:
        logger.error(f"LLM summarization failed: {e}, falling back to extractive")
        # Fallback to extractive
        sentences = text.split(".")
        limit = 3
        summary = ".".join(sentences[:limit]).strip()
        if summary and not summary.endswith("."):
            summary += "."
        return summary


async def register_skills(manager: Any) -> None:
    """Register built-in summarization skills with the manager.
    
    Args:
        manager: SkillManager instance
    """
    from ..skill_manager import SkillManager
    
    if not isinstance(manager, SkillManager):
        raise TypeError("Expected SkillManager instance")
    
    # Define the summarize skill
    summarize_skill = SkillDefinition(
        name="summarize",
        display_name="Summarize Text",
        description="Summarize a given text in various styles and lengths",
        category=SkillCategory.TEXT_PROCESSING,
        function=summarize_text,
        parameters=[
            SkillParameter(
                name="text",
                description="The text content to summarize",
                param_type="str",
                required=True,
            ),
            SkillParameter(
                name="max_length",
                description="Maximum length of the summary in words (optional)",
                param_type="int",
                required=False,
                default=None,
            ),
            SkillParameter(
                name="style",
                description="Summary style: concise, detailed, or bullet_points",
                param_type="str",
                required=False,
                default="concise",
                choices=["concise", "detailed", "bullet_points"],
            ),
        ],
        returns="The summarized text",
        examples=[
            "summarize(text='Long article content...', style='concise')",
            "summarize(text='Meeting notes...', max_length=50, style='bullet_points')",
        ],
    )
    
    manager.register(summarize_skill)
    logger.debug("Registered 'summarize' skill")
