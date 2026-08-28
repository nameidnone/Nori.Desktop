"""浏览器自动化 - DOM 操作、任务计划和执行上下文。

本模块提供浏览器 DOM 自动化功能，包括：
- 结构化动作定义（导航、点击、填写、滚动、等待、读取）
- 任务计划解析和验证
- 执行上下文和审批机制
- 进度报告和脱敏
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable, Final, Self, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class BrowserAutomationActionKind(IntEnum):
    """浏览器 DOM 自动化允许的结构化动作种类。"""

    NAVIGATE = 1
    CLICK = 2
    FILL = 3
    SCROLL = 4
    WAIT = 5
    READ_VISIBLE_TEXT = 6


class BrowserAutomationActionValidationException(Exception):
    """浏览器结构化动作解析错误。"""

    pass


@dataclass(frozen=True)
class BrowserAutomationAction:
    """浏览器 DOM 自动化动作基类；不包含脚本、文件或权限提升能力。"""

    kind: BrowserAutomationActionKind


@dataclass(frozen=True)
class BrowserNavigateAction(BrowserAutomationAction):
    """导航动作。"""

    url: str
    kind: BrowserAutomationActionKind = field(
        default=BrowserAutomationActionKind.NAVIGATE, init=False
    )

    def __post_init__(self):
        if not self.url or not self.url.strip():
            raise BrowserAutomationActionValidationException("导航 URL 不能为空")


@dataclass(frozen=True)
class BrowserClickAction(BrowserAutomationAction):
    """元素点击动作。"""

    selector: str
    kind: BrowserAutomationActionKind = field(
        default=BrowserAutomationActionKind.CLICK, init=False
    )

    def __post_init__(self):
        if not self.selector or not self.selector.strip():
            raise BrowserAutomationActionValidationException("选择器不能为空")


@dataclass(frozen=True)
class BrowserFillAction(BrowserAutomationAction):
    """表单填写动作；文本只在内存执行链中传递。"""

    selector: str
    text: str
    kind: BrowserAutomationActionKind = field(
        default=BrowserAutomationActionKind.FILL, init=False
    )

    def __post_init__(self):
        if not self.selector or not self.selector.strip():
            raise BrowserAutomationActionValidationException("选择器不能为空")
        if not self.text:
            raise BrowserAutomationActionValidationException("填写文本不能为空")


@dataclass(frozen=True)
class BrowserScrollAction(BrowserAutomationAction):
    """页面滚动动作。"""

    pixels: int
    kind: BrowserAutomationActionKind = field(
        default=BrowserAutomationActionKind.SCROLL, init=False
    )


@dataclass(frozen=True)
class BrowserWaitAction(BrowserAutomationAction):
    """有限等待动作。"""

    milliseconds: int
    kind: BrowserAutomationActionKind = field(
        default=BrowserAutomationActionKind.WAIT, init=False
    )

    def __post_init__(self):
        if self.milliseconds < 0:
            raise BrowserAutomationActionValidationException("等待时间不能为负数")


@dataclass(frozen=True)
class BrowserReadVisibleTextAction(BrowserAutomationAction):
    """读取页面可见文本的动作。"""

    kind: BrowserAutomationActionKind = field(
        default=BrowserAutomationActionKind.READ_VISIBLE_TEXT, init=False
    )


class BrowserAutomationTaskLimits:
    """浏览器任务的不可放宽边界。"""

    MAX_ACTIONS: Final[int] = 20
    MAXIMUM_DURATION_SECONDS: Final[float] = 120.0
    MAX_VISIBLE_TEXT_BYTES: Final[int] = 32 * 1024
    MAX_VISIBLE_TEXT_CHARACTERS: Final[int] = MAX_VISIBLE_TEXT_BYTES

    @classmethod
    def truncate_visible_text(cls, value: str) -> str:
        """按 UTF-8 字节边界截断文本，绝不拆开 UTF-16 代理项对。"""
        if not value:
            return ""

        byte_count = len(value.encode("utf-8"))
        if byte_count <= cls.MAX_VISIBLE_TEXT_BYTES:
            return value

        encoded = value.encode("utf-8")[: cls.MAX_VISIBLE_TEXT_BYTES]
        decoded = encoded.decode("utf-8", errors="ignore")

        if len(decoded) > 0 and ord(decoded[-1]) >= 0xD800 and ord(decoded[-1]) <= 0xDBFF:
            decoded = decoded[:-1]

        return decoded


@dataclass
class BrowserAutomationTaskPlan:
    """已解析的浏览器动作计划；只保留当前内存执行所需数据。"""

    actions: list[BrowserAutomationAction]

    def __post_init__(self):
        if not self.actions:
            raise BrowserAutomationActionValidationException(
                f"浏览器任务动作数必须在 1 到 {BrowserAutomationTaskLimits.MAX_ACTIONS} 之间"
            )
        if len(self.actions) > BrowserAutomationTaskLimits.MAX_ACTIONS:
            raise BrowserAutomationActionValidationException(
                f"浏览器任务最多允许 {BrowserAutomationTaskLimits.MAX_ACTIONS} 个动作"
            )
        if any(action is None for action in self.actions):
            raise BrowserAutomationActionValidationException("浏览器任务包含空动作")

    @classmethod
    def parse(cls, actions_data: list[dict[str, Any]]) -> Self:
        """从桥接 JSON 解析严格白名单动作。"""
        if not isinstance(actions_data, list):
            raise BrowserAutomationActionValidationException("浏览器任务 actions 必须是数组")

        actions: list[BrowserAutomationAction] = []
        for item in actions_data:
            if len(actions) == BrowserAutomationTaskLimits.MAX_ACTIONS:
                raise BrowserAutomationActionValidationException(
                    f"浏览器任务最多允许 {BrowserAutomationTaskLimits.MAX_ACTIONS} 个动作"
                )
            actions.append(cls._parse_action(item))

        return cls(actions=actions)

    @staticmethod
    def _parse_action(value: dict[str, Any]) -> BrowserAutomationAction:
        if not isinstance(value, dict):
            raise BrowserAutomationActionValidationException("浏览器动作必须是对象")

        action_type = BrowserAutomationTaskPlan._required_string(value, "type")

        if action_type == "navigate":
            return BrowserNavigateAction(
                url=BrowserAutomationTaskPlan._required_string(value, "url")
            )
        elif action_type == "click":
            return BrowserClickAction(
                selector=BrowserAutomationTaskPlan._required_string(value, "selector")
            )
        elif action_type == "fill":
            return BrowserFillAction(
                selector=BrowserAutomationTaskPlan._required_string(value, "selector"),
                text=BrowserAutomationTaskPlan._required_string(value, "text"),
            )
        elif action_type == "scroll":
            return BrowserScrollAction(
                pixels=BrowserAutomationTaskPlan._required_int(value, "pixels")
            )
        elif action_type == "wait":
            return BrowserWaitAction(
                milliseconds=BrowserAutomationTaskPlan._required_int(
                    value, "milliseconds"
                )
            )
        elif action_type in ("read_visible_text", "read-visible-text"):
            return BrowserReadVisibleTextAction()
        else:
            raise BrowserAutomationActionValidationException(
                "浏览器动作类型不在白名单内"
            )

    @staticmethod
    def _required_string(value: dict[str, Any], name: str) -> str:
        if name not in value or not isinstance(value[name], str):
            raise BrowserAutomationActionValidationException(
                f"浏览器动作缺少字符串字段：{name}"
            )
        text = value[name].strip()
        if not text:
            raise BrowserAutomationActionValidationException(
                f"浏览器动作字段无效：{name}"
            )
        return text

    @staticmethod
    def _required_int(value: dict[str, Any], name: str) -> int:
        if name not in value or not isinstance(value[name], (int, float)):
            raise BrowserAutomationActionValidationException(
                f"浏览器动作缺少整数字段：{name}"
            )
        return int(value[name])


class BrowserAutomationProgressState(Enum):
    """浏览器任务向宿主报告的脱敏进度状态。"""

    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    ACTION_SUCCEEDED = "action_succeeded"
    PAUSED = "paused"


@dataclass(frozen=True)
class BrowserAutomationProgress:
    """浏览器任务脱敏进度；不包含 URL、选择器、文本或页面内容。"""

    step: int
    action_kind: BrowserAutomationActionKind | None
    state: BrowserAutomationProgressState
    approval_request_id: uuid.UUID | None = None
    pause_reason: str | None = None


@runtime_checkable
class AutomationApprovalCallback(Protocol):
    """审批回调协议。"""

    def __call__(
        self, task_id: uuid.UUID, action: BrowserAutomationAction
    ) -> bool:
        """审批一个动作。返回 True 表示允许执行。"""
        ...


@dataclass
class BrowserAutomationExecutionContext:
    """浏览器执行上下文；由宿主提供审批、入口复核和脱敏进度投影。"""

    task_id: uuid.UUID
    approval_callback: Callable[[uuid.UUID, BrowserAutomationAction], bool] | None = (
        None
    )
    progress_callbacks: list[Callable[[BrowserAutomationProgress], None]] = field(
        default_factory=list
    )
    current_step: int = 0
    is_paused: bool = False
    pause_reason: str | None = None

    def report_progress(
        self,
        action_kind: BrowserAutomationActionKind | None,
        state: BrowserAutomationProgressState,
        approval_request_id: uuid.UUID | None = None,
    ) -> None:
        """报告脱敏进度。"""
        progress = BrowserAutomationProgress(
            step=self.current_step,
            action_kind=action_kind,
            state=state,
            approval_request_id=approval_request_id,
            pause_reason=self.pause_reason if self.is_paused else None,
        )

        for callback in self.progress_callbacks:
            try:
                callback(progress)
            except Exception as e:
                logger.error(f"进度回调失败：{e}")

    def request_approval(self, action: BrowserAutomationAction) -> bool:
        """请求审批一个动作。"""
        if not self.approval_callback:
            return True

        self.report_progress(
            action.kind, BrowserAutomationProgressState.AWAITING_APPROVAL
        )

        try:
            approved = self.approval_callback(self.task_id, action)
            if approved:
                self.report_progress(action.kind, BrowserAutomationProgressState.RUNNING)
            else:
                self.report_progress(
                    action.kind, BrowserAutomationProgressState.PAUSED
                )
                self.is_paused = True
                self.pause_reason = "用户拒绝审批"
            return approved
        except Exception as e:
            logger.error(f"审批回调失败：{e}")
            self.report_progress(action.kind, BrowserAutomationProgressState.PAUSED)
            self.is_paused = True
            self.pause_reason = f"审批错误：{e}"
            return False

    def advance_step(self) -> None:
        """前进到下一步。"""
        self.current_step += 1
        self.is_paused = False
        self.pause_reason = None

    def pause(self, reason: str) -> None:
        """暂停执行。"""
        self.is_paused = True
        self.pause_reason = reason
        self.report_progress(None, BrowserAutomationProgressState.PAUSED)

    def resume(self) -> None:
        """恢复执行。"""
        self.is_paused = False
        self.pause_reason = None
        self.report_progress(None, BrowserAutomationProgressState.RUNNING)


class BrowserAutomationCapability:
    """浏览器自动化能力声明。"""

    def __init__(
        self,
        allow_pointer: bool = False,
        allow_keyboard: bool = False,
        allow_scroll: bool = False,
        browser_enabled: bool = False,
    ):
        self.allow_pointer = allow_pointer
        self.allow_keyboard = allow_keyboard
        self.allow_scroll = allow_scroll
        self.browser_enabled = browser_enabled

    @property
    def is_fully_enabled(self) -> bool:
        """是否完全启用。"""
        return (
            self.browser_enabled
            and self.allow_pointer
            and self.allow_keyboard
            and self.allow_scroll
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_pointer": self.allow_pointer,
            "allow_keyboard": self.allow_keyboard,
            "allow_scroll": self.allow_scroll,
            "browser_enabled": self.browser_enabled,
        }


class BrowserAutomationPolicy:
    """浏览器自动化安全策略。"""

    ALLOWED_URL_SCHEMES: Final[set[str]] = {"http", "https"}

    @classmethod
    def is_url_allowed(cls, url: str) -> bool:
        """检查 URL 是否在白名单内。"""
        if not url:
            return False

        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return parsed.scheme.lower() in cls.ALLOWED_URL_SCHEMES
        except Exception:
            return False

    @classmethod
    def validate_selector(cls, selector: str) -> bool:
        """验证 CSS 选择器是否安全。"""
        if not selector or len(selector) > 500:
            return False

        dangerous_patterns = [
            "javascript:",
            "data:",
            "vbscript:",
            "<script",
            "</script",
            "onclick",
            "onerror",
            "onload",
        ]

        selector_lower = selector.lower()
        return not any(pattern in selector_lower for pattern in dangerous_patterns)


__all__ = [
    "BrowserAutomationActionKind",
    "BrowserAutomationActionValidationException",
    "BrowserAutomationAction",
    "BrowserNavigateAction",
    "BrowserClickAction",
    "BrowserFillAction",
    "BrowserScrollAction",
    "BrowserWaitAction",
    "BrowserReadVisibleTextAction",
    "BrowserAutomationTaskLimits",
    "BrowserAutomationTaskPlan",
    "BrowserAutomationProgressState",
    "BrowserAutomationProgress",
    "AutomationApprovalCallback",
    "BrowserAutomationExecutionContext",
    "BrowserAutomationCapability",
    "BrowserAutomationPolicy",
]
