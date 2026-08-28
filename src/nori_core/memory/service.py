"""Memory Service - Long-term memory facade.

Write, retrieval and lifecycle logic are completed through the MemoryStore 
aggregation layer, retaining old public API compatibility.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .store import MemoryStore, MemoryItem, MemorySearchResult
from .models import MemoryContext, PersonalMemoryItem, KnowledgeItem, EchoItem


@dataclass
class MemorySettings:
    """Memory runtime settings."""
    
    enabled: bool = True
    reflection_enabled: bool = True
    reflection_rounds: int = 8
    reflection_min_chars: int = 2500
    recall_top_k: int = 6
    keyword_top_k: int = 20
    vector_top_k: int = 20
    max_cache_size: int = 250
    embedding_batch_size: int = 32


@dataclass
class EmbeddingJob:
    """Background embedding job."""
    
    text: str
    item_id: int | None = None
    priority: int = 0


class MemoryService:
    """Long-term memory facade.
    
    Provides write, retrieval and lifecycle management through MemoryStore.
    """
    
    MAX_CACHE_SIZE: int = 250
    EMBEDDING_BATCH_SIZE: int = 32
    REEMBED_FINGERPRINT_STATE: str = "embedding_reembed_fingerprint"
    REEMBED_CURSOR_STATE: str = "embedding_reembed_cursor"
    
    def __init__(
        self,
        store: MemoryStore,
        embedding_adapter: Any | None = None,
        config: Any | None = None,
        start_background_worker: bool = True,
    ) -> None:
        self._store = store
        self._embedding = embedding_adapter
        self._config = config
        self._ai_settings = None  # Will be initialized from config
        self._transfer = None  # MemoryTransferService
        self._reembed_gate = asyncio.Semaphore(1)
        self._embedding_queue: asyncio.Queue[EmbeddingJob] = asyncio.Queue(maxsize=128)
        self._embedding_worker_task: asyncio.Task | None = None
        self._disposed = False
        
        if start_background_worker and self._embedding is not None:
            self._embedding_worker_task = asyncio.create_task(
                self._process_embedding_queue_async()
            )
    
    @property
    def store(self) -> MemoryStore:
        """Get underlying memory store."""
        return self._store
    
    @property
    def transfer(self) -> Any | None:
        """Get memory transfer service for migration."""
        return self._transfer
    
    def _read_int(self, key: str, default: int, min_val: int, max_val: int) -> int:
        """Read integer config value with bounds checking."""
        if self._config is None:
            return default
        try:
            value = getattr(self._config, 'get_int', lambda k, d: d)(key, default)
            return max(min_val, min(max_val, value))
        except (ValueError, TypeError):
            return default
    
    @property
    def settings(self) -> MemorySettings:
        """Read memory runtime settings."""
        if self._config is None:
            return MemorySettings()
        
        return MemorySettings(
            enabled=getattr(self._config, 'get_bool', lambda k, d: d)("memory_enabled", True),
            reflection_enabled=getattr(self._config, 'get_bool', lambda k, d: d)("memory_reflection_enabled", True),
            reflection_rounds=self._read_int("memory_reflection_rounds", 8, 1, 32),
            reflection_min_chars=self._read_int("memory_reflection_min_chars", 2500, 100, 20000),
            recall_top_k=self._read_int("memory_recall_top_k", 6, 1, 20),
            keyword_top_k=self._read_int("memory_keyword_top_k", 20, 1, 100),
            vector_top_k=self._read_int("memory_vector_top_k", 20, 1, 100),
            max_cache_size=self.MAX_CACHE_SIZE,
            embedding_batch_size=self.EMBEDDING_BATCH_SIZE,
        )
    
    async def build_context_async(
        self,
        user_text: str,
        recent_history: list[tuple[str, str]],
        cancellation_token: Any | None = None,
    ) -> MemoryContext:
        """Build memory context for LLM prompt.
        
        Args:
            user_text: Current user input
            recent_history: Recent dialogue history as (role, content) tuples
            cancellation_token: Optional cancellation token
            
        Returns:
            MemoryContext with personal memories, knowledge, and echoes
        """
        if not self.settings.enabled:
            return MemoryContext(personal=[], knowledge=[], echoes=[], atoms=[])
        
        # Combine user text with recent history for context building
        context_text = user_text
        for role, content in reversed(recent_history[-6:]):
            if role in ("user", "assistant"):
                context_text = f"{role}: {content}\n" + context_text
        
        # Search for relevant memories
        search_results = await self._store.search_async(
            query=context_text,
            top_k=self.settings.recall_top_k,
            include_keywords=True,
            include_vectors=True,
        )
        
        # Build personal memories
        personal = []
        for result in search_results[:self.settings.recall_top_k]:
            if isinstance(result, MemorySearchResult):
                item = result.item
                personal.append(PersonalMemoryItem(
                    id=item.id,
                    content=item.content,
                    persona_summary=item.persona_summary,
                    canonical_summary=item.canonical_summary,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                ))
        
        # Build knowledge items (from knowledge service if available)
        knowledge = []
        if hasattr(self, '_knowledge_service') and self._knowledge_service:
            knowledge_results = await self._knowledge_service.search_async(
                query=user_text,
                top_k=self.settings.vector_top_k,
            )
            for item in knowledge_results:
                knowledge.append(KnowledgeItem(
                    id=item.get("id", 0),
                    content=item.get("content", ""),
                    awareness=item.get("awareness", "related"),
                ))
        
        # Build echo items (reflections)
        echoes = []
        if self.settings.reflection_enabled:
            # Get recent reflections/echoes
            echo_results = await self._store.get_recent_echoes_async(
                limit=self.settings.recall_top_k // 2
            )
            for item in echo_results:
                echoes.append(EchoItem(
                    id=item.id,
                    content=item.content,
                    created_at=item.created_at,
                ))
        
        # Build atoms (raw memory fragments)
        atoms = []
        for result in search_results[self.settings.recall_top_k:]:
            if isinstance(result, MemorySearchResult):
                item = result.item
                atoms.append({
                    "id": item.id,
                    "content": item.content,
                    "created_at": item.created_at.isoformat() if hasattr(item.created_at, 'isoformat') else str(item.created_at),
                })
        
        return MemoryContext(
            personal=personal,
            knowledge=knowledge,
            echoes=echoes,
            atoms=atoms,
        )
    
    async def add_memory_async(
        self,
        content: str,
        persona_summary: str | None = None,
        canonical_summary: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Add a new memory item.
        
        Args:
            content: Memory content
            persona_summary: Optional persona-specific summary
            canonical_summary: Optional canonical summary
            tags: Optional tags for categorization
            
        Returns:
            ID of the newly created memory item
        """
        item = MemoryItem(
            id=0,  # Will be assigned by database
            content=content,
            persona_summary=persona_summary,
            canonical_summary=canonical_summary,
            tags=tags or [],
        )
        return await self._store.insert_async(item)
    
    async def queue_embedding_async(self, text: str, item_id: int | None = None) -> None:
        """Queue text for background embedding generation."""
        try:
            job = EmbeddingJob(text=text, item_id=item_id)
            self._embedding_queue.put_nowait(job)
        except asyncio.QueueFull:
            pass  # Drop if queue full
    
    async def _process_embedding_queue_async(self) -> None:
        """Background worker to process embedding jobs."""
        while not self._disposed:
            try:
                job = await asyncio.wait_for(
                    self._embedding_queue.get(),
                    timeout=1.0
                )
                
                if self._embedding is None:
                    continue
                
                # Generate embedding
                embedding = await self._embedding.embed_async(job.text)
                
                # Store embedding with memory item
                if job.item_id is not None:
                    await self._store.update_embedding_async(job.item_id, embedding)
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                # Log error but continue processing
                pass
    
    async def dispose_async(self) -> None:
        """Dispose resources and stop background workers."""
        if self._disposed:
            return
        
        self._disposed = True
        
        if self._embedding_worker_task is not None:
            self._embedding_worker_task.cancel()
            try:
                await self._embedding_worker_task
            except asyncio.CancelledError:
                pass


# Re-export commonly used types
__all__ = [
    "MemoryService",
    "MemorySettings",
    "EmbeddingJob",
]
