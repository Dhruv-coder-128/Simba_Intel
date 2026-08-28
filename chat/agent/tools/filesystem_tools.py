"""Sandboxed local filesystem tools for SIMBA_INTEL Agent.
Provides controlled file, folder, search, editing, and append operations with safe user boundaries and destructive action confirmation.
"""
import datetime
import fnmatch
import logging
import os
import pathlib
import shutil
import time
from typing import Any, Dict, List, Optional

from .registry import ExecutionResult, RiskLevel, Tool, ToolParameter, global_tool_registry

logger = logging.getLogger("simba_intel.agent.filesystem")

# Dangerous system paths to strictly protect
BLOCKED_PATH_PREFIXES = [
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\programdata",
    r"c:\system volume information",
    r"c:\$recycle.bin",
    r"c:\boot",
]


def _sanitize_path(raw_path: str) -> str:
    """Resolves and validates that the path is within safe user boundaries."""
    userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    desktop = os.path.join(userprofile, "Desktop")
    downloads = os.path.join(userprofile, "Downloads")
    documents = os.path.join(userprofile, "Documents")

    clean = raw_path.strip().strip('"\'')
    if not clean:
        raise ValueError("File path cannot be empty.")

    lower_clean = clean.lower()
    if lower_clean in ["downloads", "download"]:
        return downloads
    elif lower_clean in ["desktop"]:
        return desktop
    elif lower_clean in ["documents", "document", "my documents"]:
        return documents
    elif lower_clean in ["pictures", "photos"]:
        return os.path.join(userprofile, "Pictures")
    elif lower_clean in ["videos", "movies"]:
        return os.path.join(userprofile, "Videos")
    elif lower_clean in ["music"]:
        return os.path.join(userprofile, "Music")
    elif lower_clean in ["home", "user"]:
        return userprofile

    if not os.path.dirname(clean):
        if os.path.exists(clean):
            resolved = os.path.abspath(clean)
        elif os.path.exists(os.path.join(desktop, clean)):
            resolved = os.path.join(desktop, clean)
        elif os.path.exists(os.path.join(downloads, clean)):
            resolved = os.path.join(downloads, clean)
        elif os.path.exists(os.path.join(documents, clean)):
            resolved = os.path.join(documents, clean)
        else:
            resolved = os.path.abspath(os.path.join(desktop, clean))
    elif os.path.isabs(clean):
        resolved = os.path.abspath(clean)
    else:
        if os.path.exists(clean):
            resolved = os.path.abspath(clean)
        else:
            resolved = os.path.abspath(os.path.join(userprofile, clean))

    norm = resolved.lower()
    for blocked in BLOCKED_PATH_PREFIXES:
        if norm.startswith(blocked):
            raise PermissionError(f"Access to protected system path '{resolved}' is forbidden.")

    return resolved


def create_file(path: str, content: str = "") -> ExecutionResult:
    """Creates a text file safely on the user's computer."""
    try:
        full_path = _sanitize_path(path)
        if os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error=f"File '{os.path.basename(full_path)}' already exists. Use write_file or edit_file to modify.",
                is_sensitive=True,
                risk_level=RiskLevel.CAUTION.value,
                details={"path": full_path},
                action_type="file_create",
            )

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return ExecutionResult(
            success=True,
            output=f"Created file '{os.path.basename(full_path)}' at {full_path}.",
            details={"path": full_path, "size": len(content)},
            action_type="file_create",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to create file: {str(e)}",
            action_type="file_create",
        )


def write_file(path: str, content: str, overwrite: bool = False) -> ExecutionResult:
    """Writes content to a file. Overwriting an existing file requires confirmation."""
    try:
        full_path = _sanitize_path(path)
        file_exists = os.path.exists(full_path)

        if file_exists and not overwrite:
            return ExecutionResult(
                success=False,
                error=f"File '{os.path.basename(full_path)}' already exists. Overwrite confirmation required.",
                is_sensitive=True,
                requires_confirmation=True,
                risk_level=RiskLevel.CAUTION.value,
                confirmation_prompt=f"Overwrite existing file '{os.path.basename(full_path)}'?",
                sensitive_action_data={"tool_name": "write_file", "args": {"path": full_path, "content": content, "overwrite": True}},
                details={"path": full_path, "requires_overwrite": True},
                action_type="file_write",
            )

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        action_word = "Updated" if file_exists else "Created"
        return ExecutionResult(
            success=True,
            output=f"{action_word} file '{os.path.basename(full_path)}'.",
            details={"path": full_path, "size": len(content)},
            action_type="file_write",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to write file: {str(e)}",
            action_type="file_write",
        )


def append_file(path: str, content: str) -> ExecutionResult:
    """Appends content to the end of an existing file."""
    try:
        full_path = _sanitize_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "a", encoding="utf-8") as f:
            f.write(content)

        return ExecutionResult(
            success=True,
            output=f"Appended text to '{os.path.basename(full_path)}'.",
            details={"path": full_path, "appended_length": len(content)},
            action_type="file_write",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to append to file: {str(e)}",
            action_type="file_write",
        )


def edit_file(path: str, new_content: str, create_backup: bool = True) -> ExecutionResult:
    """Modifies a local file, creating a .bak backup before writing and verifying existence."""
    try:
        full_path = _sanitize_path(path)
        if not os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error=f"File '{os.path.basename(full_path)}' was not found to edit.",
                action_type="file_edit",
            )

        backup_path = None
        if create_backup:
            backup_path = f"{full_path}.bak"
            try:
                shutil.copy2(full_path, backup_path)
            except Exception as be:
                logger.warning("Could not create backup %s: %s", backup_path, be)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        if not os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error=f"Verification failed: File '{os.path.basename(full_path)}' missing after write.",
                action_type="file_edit",
            )

        return ExecutionResult(
            success=True,
            output=f"Successfully edited '{os.path.basename(full_path)}'.",
            details={"path": full_path, "backup_path": backup_path, "size": len(new_content)},
            action_type="file_edit",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to edit file: {str(e)}",
            action_type="file_edit",
        )


def read_file(path: str, max_chars: int = 15000) -> ExecutionResult:
    """Reads content from a local text, code, or PDF file."""
    try:
        full_path = _sanitize_path(path)
        if not os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error=f"File '{os.path.basename(full_path)}' was not found.",
                action_type="file_read",
            )

        ext = os.path.splitext(full_path)[1].lower()
        if ext == ".pdf":
            try:
                from chat.file_analyzer import analyze_file
                content = analyze_file(full_path)
                return ExecutionResult(
                    success=True,
                    output=content[:max_chars],
                    details={"path": full_path, "char_count": len(content), "is_pdf": True},
                    action_type="file_read",
                    risk_level=RiskLevel.SAFE.value,
                )
            except Exception as pe:
                logger.warning("PDF extraction failed: %s", pe)

        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)

        return ExecutionResult(
            success=True,
            output=content,
            details={"path": full_path, "char_count": len(content)},
            action_type="file_read",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to read file: {str(e)}",
            action_type="file_read",
        )


def delete_file(path: str, confirmed: bool = False) -> ExecutionResult:
    """Deletes a file safely. DANGEROUS action: requires explicit confirmation unless confirmed is True."""
    try:
        full_path = _sanitize_path(path)
        if not os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error=f"File '{os.path.basename(full_path)}' does not exist.",
                action_type="file_delete",
            )

        if not confirmed:
            parent_dir = os.path.basename(os.path.dirname(full_path)) or "current folder"
            return ExecutionResult(
                success=False,
                is_sensitive=True,
                requires_confirmation=True,
                risk_level=RiskLevel.DANGEROUS.value,
                confirmation_prompt=f"Delete '{os.path.basename(full_path)}' from {parent_dir}?",
                sensitive_action_data={"tool_name": "delete_file", "args": {"path": full_path, "confirmed": True}},
                output=f"Pending confirmation to delete '{os.path.basename(full_path)}'.",
                details={"path": full_path, "action": "delete_file"},
                action_type="file_delete",
            )

        os.remove(full_path)
        if os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error=f"Verification failed: File '{os.path.basename(full_path)}' could not be removed.",
                action_type="file_delete",
            )

        return ExecutionResult(
            success=True,
            output=f"Deleted '{os.path.basename(full_path)}'.",
            details={"path": full_path},
            action_type="file_delete",
            risk_level=RiskLevel.DANGEROUS.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to delete file: {str(e)}",
            action_type="file_delete",
        )


def move_file(source: str, destination: str, overwrite: bool = False) -> ExecutionResult:
    """Moves a file from source to destination."""
    try:
        src_path = _sanitize_path(source)
        if not os.path.exists(src_path):
            return ExecutionResult(
                success=False,
                error=f"Source file '{os.path.basename(src_path)}' was not found.",
                action_type="file_move",
            )

        dst_path = _sanitize_path(destination)
        if os.path.isdir(dst_path):
            dst_path = os.path.join(dst_path, os.path.basename(src_path))

        if os.path.exists(dst_path) and not overwrite:
            return ExecutionResult(
                success=False,
                error=f"Destination '{os.path.basename(dst_path)}' already exists.",
                is_sensitive=True,
                requires_confirmation=True,
                risk_level=RiskLevel.CAUTION.value,
                confirmation_prompt=f"Overwrite destination '{os.path.basename(dst_path)}' when moving?",
                sensitive_action_data={"tool_name": "move_file", "args": {"source": src_path, "destination": dst_path, "overwrite": True}},
                action_type="file_move",
            )

        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.move(src_path, dst_path)

        if not os.path.exists(dst_path):
            return ExecutionResult(
                success=False,
                error="Verification failed: file not found at destination.",
                action_type="file_move",
            )

        return ExecutionResult(
            success=True,
            output=f"Moved '{os.path.basename(src_path)}' to '{dst_path}'.",
            details={"source": src_path, "destination": dst_path},
            action_type="file_move",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to move file: {str(e)}",
            action_type="file_move",
        )


def copy_file(source: str, destination: str, overwrite: bool = False) -> ExecutionResult:
    """Copies a file from source to destination."""
    try:
        src_path = _sanitize_path(source)
        if not os.path.exists(src_path):
            return ExecutionResult(
                success=False,
                error=f"Source file '{os.path.basename(src_path)}' was not found.",
                action_type="file_copy",
            )

        dst_path = _sanitize_path(destination)
        if os.path.isdir(dst_path):
            dst_path = os.path.join(dst_path, os.path.basename(src_path))

        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)

        if not os.path.exists(dst_path):
            return ExecutionResult(
                success=False,
                error="Verification failed: copy destination not found.",
                action_type="file_copy",
            )

        return ExecutionResult(
            success=True,
            output=f"Copied '{os.path.basename(src_path)}' to '{dst_path}'.",
            details={"source": src_path, "destination": dst_path},
            action_type="file_copy",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to copy file: {str(e)}",
            action_type="file_copy",
        )


def rename_file(source: str, new_name: str) -> ExecutionResult:
    """Renames a file safely."""
    try:
        src_path = _sanitize_path(source)
        if not os.path.exists(src_path):
            return ExecutionResult(
                success=False,
                error=f"File '{os.path.basename(src_path)}' does not exist.",
                action_type="file_rename",
            )

        parent_dir = os.path.dirname(src_path)
        clean_new_name = os.path.basename(new_name.strip().strip('"\''))
        dst_path = os.path.join(parent_dir, clean_new_name)

        if os.path.exists(dst_path):
            return ExecutionResult(
                success=False,
                error=f"Cannot rename: target '{clean_new_name}' already exists.",
                action_type="file_rename",
            )

        os.rename(src_path, dst_path)

        if not os.path.exists(dst_path):
            return ExecutionResult(
                success=False,
                error="Verification failed: renamed file not found.",
                action_type="file_rename",
            )

        return ExecutionResult(
            success=True,
            output=f"Renamed '{os.path.basename(src_path)}' to '{clean_new_name}'.",
            details={"source": src_path, "new_path": dst_path},
            action_type="file_rename",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to rename file: {str(e)}",
            action_type="file_rename",
        )


def create_folder(folder_path: str) -> ExecutionResult:
    """Creates a new folder safely."""
    try:
        full_path = _sanitize_path(folder_path)
        if os.path.exists(full_path):
            return ExecutionResult(
                success=True,
                output=f"Folder '{os.path.basename(full_path)}' already exists.",
                details={"path": full_path},
                action_type="folder_create",
                risk_level=RiskLevel.SAFE.value,
            )

        os.makedirs(full_path, exist_ok=True)
        if not os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error="Verification failed: folder was not created.",
                action_type="folder_create",
            )

        return ExecutionResult(
            success=True,
            output=f"Created folder '{os.path.basename(full_path)}'.",
            details={"path": full_path},
            action_type="folder_create",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to create folder: {str(e)}",
            action_type="folder_create",
        )


def delete_folder(folder_path: str, confirmed: bool = False) -> ExecutionResult:
    """Deletes a directory safely. DANGEROUS action: requires explicit confirmation."""
    try:
        full_path = _sanitize_path(folder_path)
        if not os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error=f"Folder '{os.path.basename(full_path)}' does not exist.",
                action_type="folder_delete",
            )

        if not confirmed:
            return ExecutionResult(
                success=False,
                is_sensitive=True,
                requires_confirmation=True,
                risk_level=RiskLevel.DANGEROUS.value,
                confirmation_prompt=f"Delete folder '{os.path.basename(full_path)}' and all its contents?",
                sensitive_action_data={"tool_name": "delete_folder", "args": {"folder_path": full_path, "confirmed": True}},
                output=f"Pending confirmation to delete folder '{os.path.basename(full_path)}'.",
                details={"path": full_path},
                action_type="folder_delete",
            )

        shutil.rmtree(full_path)
        if os.path.exists(full_path):
            return ExecutionResult(
                success=False,
                error="Verification failed: folder still exists after deletion attempt.",
                action_type="folder_delete",
            )

        return ExecutionResult(
            success=True,
            output=f"Deleted folder '{os.path.basename(full_path)}'.",
            details={"path": full_path},
            action_type="folder_delete",
            risk_level=RiskLevel.DANGEROUS.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to delete folder: {str(e)}",
            action_type="folder_delete",
        )


def list_directory(path: str = ".") -> ExecutionResult:
    """Lists files and directories in a safe directory."""
    try:
        full_path = _sanitize_path(path)
        if not os.path.exists(full_path) or not os.path.isdir(full_path):
            return ExecutionResult(
                success=False,
                error=f"Directory '{full_path}' does not exist.",
                action_type="dir_list",
            )

        items = []
        for entry in os.scandir(full_path):
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": stat.st_size if not entry.is_dir() else None,
                "modified": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })

        items_sorted = sorted(items, key=lambda x: (not x["is_dir"], x["name"].lower()))
        summary = f"Found {len(items_sorted)} items in {os.path.basename(full_path) or full_path}."
        return ExecutionResult(
            success=True,
            output=summary,
            details={"path": full_path, "items": items_sorted[:60], "total_count": len(items_sorted)},
            action_type="dir_list",
            risk_level=RiskLevel.SAFE.value,
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            error=f"Failed to list directory: {str(e)}",
            action_type="dir_list",
        )


def find_files(query: str, folder: Optional[str] = None, extension: Optional[str] = None, modified_days: Optional[int] = None) -> ExecutionResult:
    """Searches user directories for files matching name pattern, extension, or modification date."""
    userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    search_dirs = []

    if folder:
        try:
            search_dirs.append(_sanitize_path(folder))
        except Exception:
            pass
    else:
        for sub in ["Downloads", "Desktop", "Documents"]:
            cand = os.path.join(userprofile, sub)
            if os.path.exists(cand):
                search_dirs.append(cand)
        search_dirs.append(os.getcwd())

    pattern = f"*{query.strip().lower()}*" if query else "*"
    if extension:
        ext_clean = extension.strip().lower()
        if not ext_clean.startswith("."):
            ext_clean = f".{ext_clean}"
        pattern = f"*{pattern}*{ext_clean}"

    now = time.time()
    cutoff_time = now - (modified_days * 86400) if modified_days is not None else None

    matches = []
    seen = set()

    for s_dir in search_dirs:
        try:
            for root, dirs, files in os.walk(s_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["node_modules", ".venv", "venv", "__pycache__", "AppData"]]
                for f in files:
                    f_path = os.path.join(root, f)
                    if f_path in seen:
                        continue
                    seen.add(f_path)

                    if fnmatch.fnmatch(f.lower(), pattern.lower()) or (query and query.lower() in f.lower()):
                        try:
                            st = os.stat(f_path)
                            if cutoff_time is not None and st.st_mtime < cutoff_time:
                                continue
                            matches.append({
                                "name": f,
                                "path": f_path,
                                "size": st.st_size,
                                "modified": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                                "folder": os.path.basename(root) or root,
                            })
                        except Exception:
                            continue
                        if len(matches) >= 30:
                            break
                if len(matches) >= 30:
                    break
        except Exception as e:
            logger.debug("Error walking %s: %s", s_dir, e)

    if matches:
        first_names = ", ".join(m["name"] for m in matches[:5])
        suffix = f" (showing first {len(matches[:5])} of {len(matches)})" if len(matches) > 5 else ""
        return ExecutionResult(
            success=True,
            output=f"Found {len(matches)} matching file(s): {first_names}{suffix}.",
            details={"matches": matches, "query": query, "count": len(matches)},
            action_type="file_find",
            risk_level=RiskLevel.SAFE.value,
        )
    else:
        return ExecutionResult(
            success=False,
            error=f"No files matching '{query or extension}' were found in user folders.",
            details={"query": query, "searched_directories": search_dirs},
            action_type="file_find",
        )


# Register all filesystem tools
global_tool_registry.register(
    Tool(
        name="create_file",
        description="Creates a new text or code file in user documents, desktop, or workspace.",
        parameters=[
            ToolParameter(name="path", type="string", description="Filename or path to create.", required=True),
            ToolParameter(name="content", type="string", description="Initial content for the file.", required=False, default=""),
        ],
        func=create_file,
        action_type="file_create",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="write_file",
        description="Writes or overwrites text/code in a file.",
        parameters=[
            ToolParameter(name="path", type="string", description="File path to write.", required=True),
            ToolParameter(name="content", type="string", description="Content to write.", required=True),
            ToolParameter(name="overwrite", type="boolean", description="Whether to overwrite existing file.", required=False, default=False),
        ],
        func=write_file,
        action_type="file_write",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="append_file",
        description="Appends text or code to the end of an existing file.",
        parameters=[
            ToolParameter(name="path", type="string", description="File path to append.", required=True),
            ToolParameter(name="content", type="string", description="Content to append.", required=True),
        ],
        func=append_file,
        action_type="file_write",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="edit_file",
        description="Edits a local file safely with backup preservation.",
        parameters=[
            ToolParameter(name="path", type="string", description="File path to edit.", required=True),
            ToolParameter(name="new_content", type="string", description="New content for the file.", required=True),
            ToolParameter(name="create_backup", type="boolean", description="Whether to create a .bak backup.", required=False, default=True),
        ],
        func=edit_file,
        action_type="file_edit",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="read_file",
        description="Reads the text content of a local file (text, code, PDF).",
        parameters=[
            ToolParameter(name="path", type="string", description="File path to read.", required=True),
            ToolParameter(name="max_chars", type="integer", description="Maximum characters to read.", required=False, default=15000),
        ],
        func=read_file,
        action_type="file_read",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="delete_file",
        description="Deletes a file permanently. DANGEROUS action: requires explicit user confirmation.",
        parameters=[
            ToolParameter(name="path", type="string", description="File path to delete.", required=True),
            ToolParameter(name="confirmed", type="boolean", description="Whether user explicitly confirmed deletion.", required=False, default=False),
        ],
        func=delete_file,
        is_sensitive=True,
        action_type="file_delete",
        risk_level=RiskLevel.DANGEROUS.value,
    )
)

global_tool_registry.register(
    Tool(
        name="move_file",
        description="Moves a file to a new folder or filename.",
        parameters=[
            ToolParameter(name="source", type="string", description="Source file path.", required=True),
            ToolParameter(name="destination", type="string", description="Destination folder or path.", required=True),
            ToolParameter(name="overwrite", type="boolean", description="Whether to overwrite if destination exists.", required=False, default=False),
        ],
        func=move_file,
        action_type="file_move",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="copy_file",
        description="Copies a file to a new folder or filename.",
        parameters=[
            ToolParameter(name="source", type="string", description="Source file path.", required=True),
            ToolParameter(name="destination", type="string", description="Destination folder or path.", required=True),
            ToolParameter(name="overwrite", type="boolean", description="Whether to overwrite if destination exists.", required=False, default=False),
        ],
        func=copy_file,
        action_type="file_copy",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="rename_file",
        description="Renames a file.",
        parameters=[
            ToolParameter(name="source", type="string", description="Current file path or name.", required=True),
            ToolParameter(name="new_name", type="string", description="New filename.", required=True),
        ],
        func=rename_file,
        action_type="file_rename",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="create_folder",
        description="Creates a new directory in user documents, desktop, or workspace.",
        parameters=[
            ToolParameter(name="folder_path", type="string", description="Folder name or path to create.", required=True),
        ],
        func=create_folder,
        action_type="folder_create",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="delete_folder",
        description="Deletes a directory permanently. DANGEROUS action: requires explicit user confirmation.",
        parameters=[
            ToolParameter(name="folder_path", type="string", description="Folder name or path to delete.", required=True),
            ToolParameter(name="confirmed", type="boolean", description="Whether user explicitly confirmed deletion.", required=False, default=False),
        ],
        func=delete_folder,
        is_sensitive=True,
        action_type="folder_delete",
        risk_level=RiskLevel.DANGEROUS.value,
    )
)

global_tool_registry.register(
    Tool(
        name="list_directory",
        description="Lists files and subdirectories inside a directory.",
        parameters=[
            ToolParameter(name="path", type="string", description="Folder path to inspect.", required=False, default="."),
        ],
        func=list_directory,
        action_type="dir_list",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="find_files",
        description="Searches user directories for files by filename pattern, extension, or modification date.",
        parameters=[
            ToolParameter(name="query", type="string", description="Search query or pattern.", required=False, default=""),
            ToolParameter(name="folder", type="string", description="Optional folder to search inside.", required=False, default=None),
            ToolParameter(name="extension", type="string", description="Optional file extension filter (e.g. '.pdf', '.py').", required=False, default=None),
            ToolParameter(name="modified_days", type="integer", description="Only files modified within the last N days.", required=False, default=None),
        ],
        func=find_files,
        action_type="file_find",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="save_file",
        description="Alias for write_file / create_file. Saves content to a file on disk.",
        parameters=[
            ToolParameter(name="path", type="string", description="File path to save.", required=True),
            ToolParameter(name="content", type="string", description="Content to save.", required=True),
            ToolParameter(name="overwrite", type="boolean", description="Whether to overwrite existing file.", required=False, default=True),
        ],
        func=lambda path, content, overwrite=True: write_file(path, content, overwrite=overwrite),
        action_type="file_write",
    )
)
