"""Built-in File Operations Tool for Nori Agent.

Provides safe file read/write/list/delete operations with sandbox restrictions.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..registry import ITool, ToolMetadata, ToolParameter, ToolCategory, ToolPermissionLevel
from ..executor import ToolExecutionContext, ToolExecutionResult


@dataclass
class FileOperationsConfig:
    """Configuration for file operations sandbox."""
    
    # Root directory for all file operations (sandbox)
    sandbox_root: str = field(default_factory=lambda: str(Path.home() / "nori_files"))
    
    # Maximum file size that can be read/written (in bytes)
    max_file_size: int = 10 * 1024 * 1024  # 10 MB
    
    # Allowed file extensions (empty = all allowed)
    allowed_extensions: List[str] = field(default_factory=list)
    
    # Disallowed file extensions (always blocked)
    blocked_extensions: List[str] = field(default_factory=lambda: [".exe", ".bat", ".cmd", ".sh", ".dll", ".so"])
    
    # Maximum directory listing depth
    max_list_depth: int = 5
    
    # Maximum number of files to return in list operation
    max_list_count: int = 1000


class FileOperationsTool(ITool):
    """Built-in tool for file system operations with safety constraints."""
    
    def __init__(self, config: Optional[FileOperationsConfig] = None):
        self.config = config or FileOperationsConfig()
        self._ensure_sandbox_exists()
    
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="file_operations",
            display_name="File Operations",
            description="Read, write, list, and delete files within a safe sandbox directory.",
            category=ToolCategory.FILE_OPERATIONS,
            permission_level=ToolPermissionLevel.CONFIRM,
            parameters=[
                ToolParameter(
                    name="operation",
                    description="The operation to perform: read, write, append, list, delete, exists, copy, move",
                    param_type="str",
                    required=True,
                    choices=["read", "write", "append", "list", "delete", "exists", "copy", "move"]
                ),
                ToolParameter(
                    name="path",
                    description="Relative path within sandbox (or source path for copy/move)",
                    param_type="str",
                    required=True
                ),
                ToolParameter(
                    name="content",
                    description="Content to write/append (required for write/append operations)",
                    param_type="str",
                    required=False
                ),
                ToolParameter(
                    name="destination",
                    description="Destination path (required for copy/move operations)",
                    param_type="str",
                    required=False
                ),
                ToolParameter(
                    name="encoding",
                    description="File encoding (default: utf-8)",
                    param_type="str",
                    required=False,
                    default="utf-8"
                ),
                ToolParameter(
                    name="recursive",
                    description="Whether to list recursively (default: false)",
                    param_type="bool",
                    required=False,
                    default=False
                )
            ],
            returns="File content or operation status",
            examples=[
                '{"operation": "read", "path": "notes.txt"}',
                '{"operation": "write", "path": "log.txt", "content": "Hello"}',
                '{"operation": "list", "path": "documents", "recursive": true}'
            ]
        )
    
    def _ensure_sandbox_exists(self) -> None:
        """Create sandbox directory if it doesn't exist."""
        sandbox_path = Path(self.config.sandbox_root)
        sandbox_path.mkdir(parents=True, exist_ok=True)
    
    def _resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path to absolute path within sandbox.
        
        Raises:
            ValueError: If path escapes sandbox
        """
        sandbox_root = Path(self.config.sandbox_root).resolve()
        target = (sandbox_root / relative_path).resolve()
        
        # Security check: ensure resolved path is within sandbox
        try:
            target.relative_to(sandbox_root)
        except ValueError:
            raise ValueError(f"Path escapes sandbox: {relative_path}")
        
        return target
    
    def _validate_extension(self, path: Path) -> bool:
        """Check if file extension is allowed."""
        ext = path.suffix.lower()
        
        # Check blocked extensions first
        if ext in [e.lower() for e in self.config.blocked_extensions]:
            return False
        
        # Check allowed extensions if specified
        if self.config.allowed_extensions and ext not in [e.lower() for e in self.config.allowed_extensions]:
            return False
        
        return True
    
    def _check_file_size(self, path: Path) -> bool:
        """Check if file size is within limits."""
        if not path.exists():
            return True
        
        try:
            size = path.stat().st_size
            return size <= self.config.max_file_size
        except OSError:
            return False
    
    async def execute_async(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Execute file operation asynchronously."""
        try:
            operation = context.arguments.get("operation")
            path_arg = context.arguments.get("path")
            
            if not operation or not path_arg:
                return ToolExecutionResult(
                    success=False,
                    error="Missing required arguments: 'operation' and 'path'"
                )
            
            # Route to specific operation
            op_method = getattr(self, f"_op_{operation}", None)
            if not op_method:
                return ToolExecutionResult(
                    success=False,
                    error=f"Unknown operation: {operation}"
                )
            
            # Execute operation
            result = await op_method(context)
            return result
            
        except ValueError as e:
            return ToolExecutionResult(success=False, error=str(e))
        except PermissionError as e:
            return ToolExecutionResult(success=False, error=f"Permission denied: {str(e)}")
        except FileNotFoundError as e:
            return ToolExecutionResult(success=False, error=f"File not found: {str(e)}")
        except Exception as e:
            return ToolExecutionResult(success=False, error=f"Unexpected error: {str(e)}")
    
    async def _op_read(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Read file content."""
        path_arg = context.arguments["path"]
        encoding = context.arguments.get("encoding", "utf-8")
        
        abs_path = self._resolve_path(path_arg)
        
        if not abs_path.exists():
            return ToolExecutionResult(success=False, error=f"File not found: {path_arg}")
        
        if not abs_path.is_file():
            return ToolExecutionResult(success=False, error=f"Not a file: {path_arg}")
        
        if not self._validate_extension(abs_path):
            return ToolExecutionResult(success=False, error=f"File type not allowed: {abs_path.suffix}")
        
        if not self._check_file_size(abs_path):
            return ToolExecutionResult(
                success=False, 
                error=f"File too large (max {self.config.max_file_size} bytes)"
            )
        
        # Read file content
        content = await asyncio.to_thread(abs_path.read_text, encoding=encoding)
        
        return ToolExecutionResult.success_result(
            result={
                "path": path_arg,
                "size": len(content),
                "content": content
            },
            tool_name=self.metadata.name,
            execution_time_ms=0
        )
    
    async def _op_write(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Write content to file (overwrite)."""
        path_arg = context.arguments["path"]
        content = context.arguments.get("content", "")
        encoding = context.arguments.get("encoding", "utf-8")
        
        if content is None:
            return ToolExecutionResult(success=False, error="Missing 'content' argument for write operation")
        
        abs_path = self._resolve_path(path_arg)
        
        if not self._validate_extension(abs_path):
            return ToolExecutionResult(success=False, error=f"File type not allowed: {abs_path.suffix}")
        
        if len(content.encode('utf-8')) > self.config.max_file_size:
            return ToolExecutionResult(
                success=False,
                error=f"Content too large (max {self.config.max_file_size} bytes)"
            )
        
        # Create parent directories if needed
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write content
        await asyncio.to_thread(abs_path.write_text, content, encoding=encoding)
        
        return ToolExecutionResult(
            success=True,
            data={
                "path": path_arg,
                "size": len(content.encode('utf-8')),
                "operation": "write"
            }
        )
    
    async def _op_append(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Append content to file."""
        path_arg = context.arguments["path"]
        content = context.arguments.get("content", "")
        encoding = context.arguments.get("encoding", "utf-8")
        
        if content is None:
            return ToolExecutionResult(success=False, error="Missing 'content' argument for append operation")
        
        abs_path = self._resolve_path(path_arg)
        
        if not self._validate_extension(abs_path):
            return ToolExecutionResult(success=False, error=f"File type not allowed: {abs_path.suffix}")
        
        # Create parent directories if needed
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Append content
        await asyncio.to_thread(
            lambda: abs_path.open('a', encoding=encoding).write(content)
        )
        
        return ToolExecutionResult(
            success=True,
            data={
                "path": path_arg,
                "operation": "append"
            }
        )
    
    async def _op_list(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """List directory contents."""
        path_arg = context.arguments["path"]
        recursive = context.arguments.get("recursive", False)
        
        abs_path = self._resolve_path(path_arg)
        
        if not abs_path.exists():
            return ToolExecutionResult(success=False, error=f"Path not found: {path_arg}")
        
        if not abs_path.is_dir():
            return ToolExecutionResult(success=False, error=f"Not a directory: {path_arg}")
        
        items = []
        count = 0
        
        if recursive:
            # Recursive listing with depth limit
            for root, dirs, files in os.walk(abs_path):
                root_path = Path(root)
                depth = len(root_path.relative_to(abs_path).parts)
                
                if depth >= self.config.max_list_depth:
                    dirs.clear()  # Don't descend further
                    continue
                
                for name in sorted(dirs + files):
                    if count >= self.config.max_list_count:
                        break
                    
                    item_path = root_path / name
                    rel_path = str(item_path.relative_to(abs_path))
                    
                    items.append({
                        "name": name,
                        "path": rel_path,
                        "type": "directory" if item_path.is_dir() else "file",
                        "size": item_path.stat().st_size if item_path.is_file() else None
                    })
                    count += 1
                
                if count >= self.config.max_list_count:
                    break
        else:
            # Non-recursive listing
            for item in sorted(abs_path.iterdir()):
                if count >= self.config.max_list_count:
                    break
                
                rel_path = str(item.relative_to(abs_path))
                items.append({
                    "name": item.name,
                    "path": rel_path,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })
                count += 1
        
        return ToolExecutionResult(
            success=True,
            data={
                "path": path_arg,
                "count": len(items),
                "items": items,
                "truncated": count >= self.config.max_list_count
            }
        )
    
    async def _op_delete(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Delete file or directory."""
        path_arg = context.arguments["path"]
        
        abs_path = self._resolve_path(path_arg)
        
        if not abs_path.exists():
            return ToolExecutionResult(success=False, error=f"Path not found: {path_arg}")
        
        if not self._validate_extension(abs_path) if abs_path.is_file() else True:
            return ToolExecutionResult(success=False, error=f"Operation not allowed on this path")
        
        if abs_path.is_file():
            await asyncio.to_thread(abs_path.unlink)
        elif abs_path.is_dir():
            # Only allow deleting empty directories for safety
            if any(abs_path.iterdir()):
                return ToolExecutionResult(
                    success=False,
                    error="Cannot delete non-empty directory. Remove contents first."
                )
            await asyncio.to_thread(abs_path.rmdir)
        
        return ToolExecutionResult(
            success=True,
            data={
                "path": path_arg,
                "operation": "delete"
            }
        )
    
    async def _op_exists(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Check if path exists."""
        path_arg = context.arguments["path"]
        
        try:
            abs_path = self._resolve_path(path_arg)
            exists = abs_path.exists()
            
            return ToolExecutionResult(
                success=True,
                data={
                    "path": path_arg,
                    "exists": exists,
                    "type": "file" if abs_path.is_file() else "directory" if abs_path.is_dir() else None
                }
            )
        except ValueError:
            # Path escapes sandbox, so it "doesn't exist" in our context
            return ToolExecutionResult(
                success=True,
                data={
                    "path": path_arg,
                    "exists": False
                }
            )
    
    async def _op_copy(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Copy file or directory."""
        path_arg = context.arguments["path"]
        dest_arg = context.arguments.get("destination")
        
        if not dest_arg:
            return ToolExecutionResult(success=False, error="Missing 'destination' argument for copy operation")
        
        src_path = self._resolve_path(path_arg)
        dest_path = self._resolve_path(dest_arg)
        
        if not src_path.exists():
            return ToolExecutionResult(success=False, error=f"Source not found: {path_arg}")
        
        if not self._validate_extension(src_path) if src_path.is_file() else True:
            return ToolExecutionResult(success=False, error="Operation not allowed on this file type")
        
        # Create parent directories if needed
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        if src_path.is_file():
            await asyncio.to_thread(shutil.copy2, src_path, dest_path)
        elif src_path.is_dir():
            await asyncio.to_thread(shutil.copytree, src_path, dest_path)
        
        return ToolExecutionResult(
            success=True,
            data={
                "source": path_arg,
                "destination": dest_arg,
                "operation": "copy"
            }
        )
    
    async def _op_move(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """Move/rename file or directory."""
        path_arg = context.arguments["path"]
        dest_arg = context.arguments.get("destination")
        
        if not dest_arg:
            return ToolExecutionResult(success=False, error="Missing 'destination' argument for move operation")
        
        src_path = self._resolve_path(path_arg)
        dest_path = self._resolve_path(dest_arg)
        
        if not src_path.exists():
            return ToolExecutionResult(success=False, error=f"Source not found: {path_arg}")
        
        if not self._validate_extension(src_path) if src_path.is_file() else True:
            return ToolExecutionResult(success=False, error="Operation not allowed on this file type")
        
        # Create parent directories if needed
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        await asyncio.to_thread(shutil.move, src_path, dest_path)
        
        return ToolExecutionResult(
            success=True,
            data={
                "source": path_arg,
                "destination": dest_arg,
                "operation": "move"
            }
        )


def create_tool(config: Optional[FileOperationsConfig] = None) -> ITool:
    """Factory function to create FileOperationsTool instance."""
    return FileOperationsTool(config)
