"""Built-in translation skill for Nori."""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..skill_definition import (
    SkillCategory,
    SkillContext,
    SkillDefinition,
    SkillParameter,
)

logger = logging.getLogger(__name__)

# Common language codes
SUPPORTED_LANGUAGES = {
    "en": "English",
    "zh": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
}


async def translate_text(
    context: SkillContext,
    text: str,
    target_language: str,
    source_language: Optional[str] = None,
    formality: str = "neutral"
) -> str:
    """Translate text from one language to another.
    
    Args:
        context: Skill execution context
        text: The text to translate
        target_language: Target language code (e.g., 'en', 'zh', 'ja')
        source_language: Source language code (optional, will auto-detect if None)
        formality: Formality level - 'formal', 'casual', or 'neutral'
        
    Returns:
        Translated text
    """
    # Validate target language
    if target_language not in SUPPORTED_LANGUAGES:
        available = ", ".join(SUPPORTED_LANGUAGES.keys())
        raise ValueError(
            f"Unsupported target language '{target_language}'. "
            f"Supported: {available}"
        )
    
    # Get LLM service
    llm_service = context.services.get("llm_adapter")
    
    if llm_service is None:
        # Fallback: return original text with warning
        logger.warning("No LLM service available for translation")
        return f"[Translation unavailable] {text}"
    
    # Build translation prompt
    source_info = ""
    if source_language:
        if source_language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Unknown source language '{source_language}', will auto-detect")
        else:
            source_info = f"from {SUPPORTED_LANGUAGES[source_language]} "
    
    formality_instructions = {
        "formal": "Use formal and polite language.",
        "casual": "Use casual and conversational language.",
        "neutral": "Use neutral, standard language.",
    }
    
    formality_prompt = formality_instructions.get(formality, formality_instructions["neutral"])
    
    target_name = SUPPORTED_LANGUAGES[target_language]
    
    prompt = f"""Translate the following text {source_info}to {target_name}.

{formality_prompt}
Only output the translation, no explanations.

Text to translate:
{text}
"""
    
    try:
        # Call LLM for translation
        if hasattr(llm_service, "complete"):
            result = await llm_service.complete(prompt)
            return result.text.strip() if hasattr(result, "text") else str(result).strip()
        else:
            logger.warning("LLM service does not have 'complete' method")
            raise ValueError("LLM service incompatible")
    
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        raise RuntimeError(f"Translation failed: {e}") from e


async def detect_language(context: SkillContext, text: str) -> str:
    """Detect the language of a given text.
    
    Args:
        context: Skill execution context
        text: Text to analyze
        
    Returns:
        Detected language code (e.g., 'en', 'zh', 'ja')
    """
    llm_service = context.services.get("llm_adapter")
    
    if llm_service is None:
        # Simple heuristic fallback
        text_lower = text.lower()
        if any(ord(c) > 127 for c in text):
            # Has non-ASCII characters
            if any('\u4e00' <= c <= '\u9fff' for c in text):
                return "zh"
            elif any('\u3040' <= c <= '\u309f' for c in text):
                return "ja"
            elif any('\uac00' <= c <= '\ud7af' for c in text):
                return "ko"
        return "en"  # Default
    
    prompt = f"""Detect the language of the following text and respond with only the ISO 639-1 language code (e.g., 'en', 'zh', 'ja', 'ko').

Text: {text[:500]}  # Limit length for efficiency
"""
    
    try:
        if hasattr(llm_service, "complete"):
            result = await llm_service.complete(prompt)
            code = (result.text if hasattr(result, "text") else str(result)).strip().lower()
            # Extract just the code
            code = code.split()[0] if code else "en"
            return code
        else:
            raise ValueError("LLM service incompatible")
    except Exception:
        return "en"  # Fallback


async def register_skills(manager: Any) -> None:
    """Register built-in translation skills with the manager.
    
    Args:
        manager: SkillManager instance
    """
    from ..skill_manager import SkillManager
    
    if not isinstance(manager, SkillManager):
        raise TypeError("Expected SkillManager instance")
    
    # Translation skill
    translate_skill = SkillDefinition(
        name="translate",
        display_name="Translate Text",
        description="Translate text between different languages",
        category=SkillCategory.TEXT_PROCESSING,
        function=translate_text,
        parameters=[
            SkillParameter(
                name="text",
                description="The text content to translate",
                param_type="str",
                required=True,
            ),
            SkillParameter(
                name="target_language",
                description=f"Target language code. Supported: {', '.join(SUPPORTED_LANGUAGES.keys())}",
                param_type="str",
                required=True,
            ),
            SkillParameter(
                name="source_language",
                description="Source language code (optional, auto-detect if not provided)",
                param_type="str",
                required=False,
                default=None,
            ),
            SkillParameter(
                name="formality",
                description="Formality level: formal, casual, or neutral",
                param_type="str",
                required=False,
                default="neutral",
                choices=["formal", "casual", "neutral"],
            ),
        ],
        returns="The translated text",
        examples=[
            "translate(text='Hello world', target_language='zh')",
            "translate(text='Bonjour', target_language='en', source_language='fr')",
            "translate(text='Thank you', target_language='ja', formality='formal')",
        ],
    )
    
    # Language detection skill (hidden, used internally)
    detect_skill = SkillDefinition(
        name="detect_language",
        display_name="Detect Language",
        description="Detect the language of a given text",
        category=SkillCategory.TEXT_PROCESSING,
        function=detect_language,
        parameters=[
            SkillParameter(
                name="text",
                description="The text to analyze",
                param_type="str",
                required=True,
            ),
        ],
        returns="ISO 639-1 language code",
        hidden=True,  # Internal use only
    )
    
    manager.register(translate_skill)
    manager.register(detect_skill)
    logger.debug("Registered 'translate' and 'detect_language' skills")
