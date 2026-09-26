"""SIMBA_INTEL Dedicated Agent Task Manager & Lifecycle Controller.
Tracks structured task lifecycle: IDLE, PLANNING, WAITING FOR APPROVAL, EXECUTING,
VERIFYING, COMPLETED, FAILED, CANCELLED, and PAUSED.
Maintains dedicated task execution history separate from assistant conversations.
"""
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from django.core.cache import cache

logger = logging.getLogger("simba_intel.agent.task_manager")


class TaskStatus:
    IDLE = "IDLE"
    READY = "READY"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    WAITING_FOR_PERMISSION = "WAITING_FOR_PERMISSION"
    WAITING_FOR_APPROVAL = "WAITING_FOR_PERMISSION"  # Alias for backwards compatibility
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


@dataclass
class TaskStepRecord:
    index: int
    tool: str
    description: str
    status: str = "pending"  # pending, executing, verified, failed, cancelled
    args: Dict[str, Any] = field(default_factory=dict)
    output: Optional[str] = None
    error: Optional[str] = None
    verified: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTaskRecord:
    task_id: str
    user_id: Optional[int]
    title: str = "Agent Task"
    user_request: str = ""
    status: str = TaskStatus.IDLE
    plan: Dict[str, Any] = field(default_factory=dict)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    current_step_index: int = 0
    active_tool: Optional[str] = None
    tool_result: Optional[Dict[str, Any]] = None
    verification_result: Optional[Dict[str, Any]] = None
    final_result: str = ""
    error: Optional[str] = None
    failure_reason: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    start_time: float = field(default_factory=time.time)
    completion_time: Optional[float] = None
    is_cancelled: bool = False
    session_id: Optional[int] = None
    requires_permission: bool = False
    requires_approval: bool = False
    permission_details: Optional[Dict[str, Any]] = None  # {tool, prompt, reason, risk, args}
    approval_details: Optional[Dict[str, Any]] = None

    @property
    def current_step(self) -> Optional[Dict[str, Any]]:
        if self.steps and 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def to_dict(self) -> Dict[str, Any]:
        duration = round((self.completion_time or time.time()) - self.start_time, 2)
        err = self.error or self.failure_reason or None
        req_perm = self.requires_permission or self.requires_approval
        perm_details = self.permission_details or self.approval_details
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "user_request": self.user_request,
            "title": self.title,
            "status": self.status,
            "plan": self.plan,
            "steps": self.steps,
            "current_step_index": self.current_step_index,
            "current_step": self.current_step,
            "active_tool": self.active_tool,
            "tool_result": self.tool_result,
            "verification_result": self.verification_result,
            "final_result": self.final_result,
            "error": err,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "duration": duration,
            "is_cancelled": self.is_cancelled,
            "session_id": self.session_id,
            "requires_permission": req_perm,
            "requires_approval": req_perm,
            "permission_details": perm_details,
            "approval_details": perm_details,
        }


class AgentTaskManager:
    """Thread-safe manager for SIMBA_INTEL task lifecycle and persistent history."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active_tasks: Dict[str, AgentTaskRecord] = {}
        self._user_active_task: Dict[int, str] = {}  # user_id -> task_id
        self._cancelled_tasks: set = set()

    def create_task(
        self,
        title: str = "Agent Task",
        user_id: Optional[int] = None,
        session_id: Optional[int] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        requires_approval: bool = False,
        approval_details: Optional[Dict[str, Any]] = None,
        user_request: str = "",
        plan: Optional[Dict[str, Any]] = None,
        initial_status: Optional[str] = None,
    ) -> AgentTaskRecord:
        """Initializes and registers a new agent task with a stable unique ID."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        formatted_steps = []
        if steps:
            for i, s in enumerate(steps):
                formatted_steps.append({
                    "index": i + 1,
                    "tool": s.get("tool", "unknown"),
                    "description": s.get("description", f"Step {i + 1}"),
                    "args": s.get("args", {}),
                    "status": "pending",
                    "verified": False,
                    "output": None,
                    "error": None,
                })

        if initial_status:
            status = initial_status
        elif requires_approval:
            status = TaskStatus.WAITING_FOR_PERMISSION
        elif user_request and not steps:
            status = TaskStatus.UNDERSTANDING
        else:
            status = TaskStatus.PLANNING

        now = time.time()
        record = AgentTaskRecord(
            task_id=task_id,
            user_id=user_id,
            session_id=session_id,
            user_request=user_request or title,
            title=title,
            status=status,
            plan=plan or {},
            steps=formatted_steps,
            requires_permission=requires_approval,
            requires_approval=requires_approval,
            permission_details=approval_details,
            approval_details=approval_details,
            created_at=now,
            updated_at=now,
            start_time=now,
        )

        with self._lock:
            self._active_tasks[task_id] = record
            if user_id is not None:
                self._user_active_task[user_id] = task_id

        # Cache task for multi-process / cluster availability
        self._save_to_cache(record)
        self._append_to_history(record)
        logger.info("Created Agent Task %s: '%s' status=%s (user_id=%s)", task_id, title, status, user_id)
        return record

    def set_task_understanding(self, task_id: str, user_request: Optional[str] = None):
        """Transitions task to UNDERSTANDING status."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if task:
                task.status = TaskStatus.UNDERSTANDING
                if user_request:
                    task.user_request = user_request
                task.updated_at = time.time()
                self._save_to_cache(task)
                self._update_in_history(task)

    def set_task_planning(
        self,
        task_id: str,
        plan: Optional[Dict[str, Any]] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        title: Optional[str] = None,
    ):
        """Transitions task to PLANNING status and hydrates plan and steps."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if task:
                task.status = TaskStatus.PLANNING
                if plan:
                    task.plan = plan
                if title:
                    task.title = title
                if steps is not None:
                    formatted_steps = []
                    for i, s in enumerate(steps):
                        formatted_steps.append({
                            "index": i + 1,
                            "tool": s.get("tool", "unknown"),
                            "description": s.get("description", f"Step {i + 1}"),
                            "args": s.get("args", {}),
                            "status": s.get("status", "pending"),
                            "verified": s.get("verified", False),
                            "output": s.get("output"),
                            "error": s.get("error"),
                        })
                    task.steps = formatted_steps
                task.updated_at = time.time()
                self._save_to_cache(task)
                self._update_in_history(task)

    def set_task_permission_required(
        self,
        task_id: str,
        step_index: int,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Transitions task to WAITING_FOR_PERMISSION status."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if task:
                task.status = TaskStatus.WAITING_FOR_PERMISSION
                task.requires_permission = True
                task.requires_approval = True
                task.permission_details = details or {}
                task.approval_details = details or {}
                task.current_step_index = step_index
                if 0 <= step_index < len(task.steps):
                    task.active_tool = task.steps[step_index].get("tool")
                    task.steps[step_index]["status"] = "waiting_for_permission"
                task.updated_at = time.time()
                self._save_to_cache(task)
                self._update_in_history(task)

    def set_task_executing(
        self,
        task_id: str,
        step_index: int,
        tool_name: Optional[str] = None,
    ):
        """Transitions task to EXECUTING status for a specific step."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if task:
                task.status = TaskStatus.EXECUTING
                task.current_step_index = step_index
                if 0 <= step_index < len(task.steps):
                    st = task.steps[step_index]
                    st["status"] = "executing"
                    task.active_tool = tool_name or st.get("tool")
                elif tool_name:
                    task.active_tool = tool_name
                task.updated_at = time.time()
                self._save_to_cache(task)
                self._update_in_history(task)

    def set_task_verifying(
        self,
        task_id: str,
        step_index: int,
        tool_result: Optional[Dict[str, Any]] = None,
        verification_result: Optional[Dict[str, Any]] = None,
    ):
        """Transitions task to VERIFYING status and records tool & verification results."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if task:
                task.status = TaskStatus.VERIFYING
                task.current_step_index = step_index
                if tool_result:
                    task.tool_result = tool_result
                if verification_result:
                    task.verification_result = verification_result
                task.updated_at = time.time()
                self._save_to_cache(task)
                self._update_in_history(task)

    def get_task(self, task_id: str) -> Optional[AgentTaskRecord]:
        """Retrieves a task record by ID from memory or cache."""
        with self._lock:
            if task_id in self._active_tasks:
                return self._active_tasks[task_id]

        cached = cache.get(f"agent_task:{task_id}")
        if cached and isinstance(cached, dict):
            try:
                rec = AgentTaskRecord(**{k: v for k, v in cached.items() if k in AgentTaskRecord.__dataclass_fields__})
                return rec
            except Exception as e:
                logger.warning("Failed to deserialize task %s from cache: %s", task_id, e)
        return None

    def get_active_task_for_user(self, user_id: int) -> Optional[AgentTaskRecord]:
        """Returns the currently active or in-flight task for a given user."""
        with self._lock:
            task_id = self._user_active_task.get(user_id)
            if task_id and task_id in self._active_tasks:
                task = self._active_tasks[task_id]
                if task.status in [
                    TaskStatus.UNDERSTANDING,
                    TaskStatus.PLANNING,
                    TaskStatus.WAITING_FOR_PERMISSION,
                    TaskStatus.WAITING_FOR_APPROVAL,
                    TaskStatus.EXECUTING,
                    TaskStatus.VERIFYING,
                    TaskStatus.PAUSED,
                ]:
                    return task
        return None

    def update_task_status(self, task_id: str, status: str, failure_reason: str = ""):
        """Updates the top-level lifecycle status of a task."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if task:
                task.status = status
                if failure_reason:
                    task.failure_reason = failure_reason
                    task.error = failure_reason
                task.updated_at = time.time()
                self._save_to_cache(task)
                self._update_in_history(task)

    def update_step_status(
        self,
        task_id: str,
        step_index: int,
        status: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
        verified: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Updates the execution status of a specific step in the task."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if not task:
                return
            task.current_step_index = step_index
            if 0 <= step_index < len(task.steps):
                step = task.steps[step_index]
                step["status"] = status
                if output is not None:
                    step["output"] = output
                if error is not None:
                    step["error"] = error
                    task.error = error
                step["verified"] = verified
                if details:
                    step["details"] = details
            task.updated_at = time.time()
            self._save_to_cache(task)
            self._update_in_history(task)

    def cancel_task(self, task_id: Optional[str] = None, user_id: Optional[int] = None) -> bool:
        """Safely stops and cancels an agent task, freeing the agent from EXECUTING state."""
        with self._lock:
            target_task_id = task_id
            if not target_task_id and user_id is not None:
                target_task_id = self._user_active_task.get(user_id)

            if not target_task_id:
                return False

            self._cancelled_tasks.add(target_task_id)
            task = self._active_tasks.get(target_task_id)
            if task:
                task.is_cancelled = True
                task.status = TaskStatus.CANCELLED
                task.completion_time = time.time()
                task.failure_reason = "Cancelled by user."
                self._save_to_cache(task)
                self._update_in_history(task)

            if user_id is not None and self._user_active_task.get(user_id) == target_task_id:
                self._user_active_task.pop(user_id, None)

        # Cancel any in-flight desktop agent commands via DesktopAgentHub
        if user_id is not None:
            try:
                from .agent_hub import default_agent_hub
                default_agent_hub.cancel_user_commands(user_id)
            except Exception as e:
                logger.warning("Error propagating cancellation to desktop agent hub: %s", e)

        logger.info("Cancelled Agent Task %s (user_id=%s)", target_task_id, user_id)
        return True

    def is_task_cancelled(self, task_id: Optional[str] = None, user_id: Optional[int] = None) -> bool:
        """Checks if a task has been flagged for cancellation."""
        with self._lock:
            if task_id and task_id in self._cancelled_tasks:
                return True
            if user_id and user_id in self._user_active_task:
                uid_task = self._user_active_task[user_id]
                if uid_task in self._cancelled_tasks:
                    return True
        return False

    def complete_task(
        self,
        task_id: str,
        success: bool = True,
        final_result: str = "",
        failure_reason: str = "",
    ):
        """Marks a task as finished (COMPLETED or FAILED) with timestamp and outcome summary."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if not task:
                return

            now = time.time()
            task.completion_time = now
            task.updated_at = now
            task.final_result = final_result
            if success:
                task.status = TaskStatus.COMPLETED
            else:
                task.status = TaskStatus.FAILED
                task.failure_reason = failure_reason or "Execution failed."
                task.error = task.failure_reason

            if task.user_id and self._user_active_task.get(task.user_id) == task_id:
                self._user_active_task.pop(task.user_id, None)

            self._save_to_cache(task)
            self._update_in_history(task)
            logger.info("Completed Agent Task %s: status=%s", task_id, task.status)

    def pause_task(self, task_id: str, reason: str = "Desktop Agent disconnected"):
        """Pauses a task when connection drops, preserving state for resume."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if task:
                task.status = TaskStatus.PAUSED
                task.failure_reason = reason
                task.error = reason
                task.updated_at = time.time()
                self._save_to_cache(task)
                logger.info("Paused Agent Task %s: %s", task_id, reason)

    def approve_task(self, task_id: str) -> bool:
        """Approves a waiting task, transitioning it to EXECUTING with confirmed arguments."""
        with self._lock:
            task = self._active_tasks.get(task_id)
            if not task:
                task = self.get_task(task_id)
            if not task:
                return False
            task.status = TaskStatus.EXECUTING
            task.requires_permission = False
            task.requires_approval = False
            pending_idx = task.current_step_index
            if task.permission_details and isinstance(task.permission_details, dict):
                pending_idx = task.permission_details.get("step_index", pending_idx)
            if 0 <= pending_idx < len(task.steps):
                step = task.steps[pending_idx]
                if "args" in step and isinstance(step["args"], dict):
                    step["args"]["confirmed"] = True
                    step["args"]["overwrite"] = True
                step["status"] = "approved"
            task.updated_at = time.time()
            self._save_to_cache(task)
            self._update_in_history(task)
            logger.info("Approved Agent Task %s: status=%s", task_id, task.status)
            return True


    def get_user_task_history(
        self,
        user_id: Optional[int],
        limit: int = 30,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves dedicated task history records for a user with optional search and status filter."""
        if user_id is None:
            return []
        cache_key = f"agent_task_history:{user_id}"
        history = cache.get(cache_key) or []

        filtered = []
        clean_search = (search or "").strip().lower()
        clean_status = (status_filter or "").strip().lower()

        for item in history:
            if clean_status and clean_status != "all":
                item_status = str(item.get("status", "")).lower()
                if clean_status == "completed" and item_status != "completed":
                    continue
                elif clean_status == "failed" and item_status not in ["failed", "cancelled"]:
                    continue
                elif clean_status == "running" and item_status not in ["planning", "executing", "verifying", "waiting_for_approval"]:
                    continue
                elif clean_status == "cancelled" and item_status != "cancelled":
                    continue
                elif clean_status not in ["completed", "failed", "running", "cancelled"] and clean_status != item_status:
                    continue

            if clean_search:
                title = str(item.get("title", "")).lower()
                final_res = str(item.get("final_result", "")).lower()
                steps_text = " ".join(str(s.get("description", "")) for s in item.get("steps", [])).lower()
                if clean_search not in title and clean_search not in final_res and clean_search not in steps_text:
                    continue

            filtered.append(item)

        return filtered[:limit]


    def _save_to_cache(self, task: AgentTaskRecord):
        try:
            cache.set(f"agent_task:{task.task_id}", task.to_dict(), timeout=86400)
        except Exception as e:
            logger.warning("Failed to save task %s to cache: %s", task.task_id, e)

    def _append_to_history(self, task: AgentTaskRecord):
        if task.user_id is None:
            return
        try:
            cache_key = f"agent_task_history:{task.user_id}"
            history: List[Dict[str, Any]] = cache.get(cache_key) or []
            # Keep newest first
            history = [h for h in history if h.get("task_id") != task.task_id]
            history.insert(0, task.to_dict())
            cache.set(cache_key, history[:50], timeout=86400 * 7)
        except Exception as e:
            logger.warning("Failed to append task %s to history: %s", task.task_id, e)

    def _update_in_history(self, task: AgentTaskRecord):
        if task.user_id is None:
            return
        try:
            cache_key = f"agent_task_history:{task.user_id}"
            history: List[Dict[str, Any]] = cache.get(cache_key) or []
            updated = []
            found = False
            for h in history:
                if h.get("task_id") == task.task_id:
                    updated.append(task.to_dict())
                    found = True
                else:
                    updated.append(h)
            if not found:
                updated.insert(0, task.to_dict())
            cache.set(cache_key, updated[:50], timeout=86400 * 7)
        except Exception as e:
            logger.warning("Failed to update task %s in history: %s", task.task_id, e)


default_task_manager = AgentTaskManager()
