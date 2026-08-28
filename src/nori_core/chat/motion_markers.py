"""
动作标记处理

对应 C#: MotionMarkers.cs

AI 在回复末尾用 [nori_motion:动作名] 表达动作，宿主剥掉标记并广播给桌宠窗口播放。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

# =============================================================================
# 常量定义
# =============================================================================

#: 动作标记起始串
MARKER_START: Final[str] = "[nori_motion:"


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class MotionGroup:
    """动作组定义"""
    group: str
    names: list[str]
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MotionGroup:
        """从字典创建"""
        return cls(
            group=data.get("group", ""),
            names=[str(n) for n in data.get("names", [])],
        )


# =============================================================================
# 动作标记处理
# =============================================================================

def extract(content: str) -> tuple[str, list[str]]:
    """
    从回复中提取动作标记
    
    Args:
        content: LLM 原始回复内容
    
    Returns:
        (剥离标记后的文本，动作名列表)
    
    对应 C#: MotionMarkers.Extract
    """
    clean_parts = []
    motions = []
    rest = content
    
    while True:
        start = rest.find(MARKER_START)
        if start < 0:
            break
        
        # 添加标记前的内容
        clean_parts.append(rest[:start])
        
        # 查找闭合括号
        after = rest[start + len(MARKER_START):]
        end = after.find(']')
        
        if end < 0:
            # 没有闭合的标记原样保留
            clean_parts.append(MARKER_START)
            rest = after
            continue
        
        # 提取动作名
        name = after[:end].strip()
        if name:
            motions.append(name)
        
        rest = after[end + 1:]
    
    # 添加剩余内容
    clean_parts.append(rest)
    
    return "".join(clean_parts), motions


def build_hint(config_getter: callable, model_id: str) -> str:
    """
    从配置读取当前模型动作列表，组装成提示词附录
    
    Args:
        config_getter: 配置获取函数 (key) -> value
        model_id: 模型 ID
    
    Returns:
        提示词附录字符串，如果没有动作则返回空串
    
    对应 C#: MotionMarkers.BuildHint
    
    优先读 l2d_motions_<模型 id>, 回退全局 l2d_motions; 没有动作时返回空串
    """
    # 确定查找键顺序
    if not model_id:
        keys = ["l2d_motions"]
    else:
        keys = [f"l2d_motions_{model_id}", "l2d_motions"]
    
    groups = None
    for key in keys:
        value = config_getter(key)
        if value is not None:
            groups = value
            break
    
    if not groups:
        return ""
    
    # 解析动作组
    lines = []
    for item in groups:
        if not isinstance(item, dict):
            continue
        
        name = item.get("group", "")
        names_list = item.get("names", [])
        
        if isinstance(names_list, list):
            names = ", ".join(str(n) for n in names_list if n)
        else:
            names = ""
        
        if name and names:
            lines.append(f"{name}: {names}")
    
    if not lines:
        return ""
    
    # 组装提示词附录
    hint = (
        "\n\n## 当前可用动作\n"
        "需要表达动作时，在回复末尾另起一行附加标记 [nori_motion:动作名], 每行一个，最多一个，"
        "动作名从下面选择，没有合适的就不加:\n"
    )
    return hint + "\n".join(lines)


def extract_with_regex(content: str) -> tuple[str, list[str]]:
    """
    使用正则表达式提取动作标记（备选实现）
    
    Args:
        content: LLM 原始回复内容
    
    Returns:
        (剥离标记后的文本，动作名列表)
    """
    # 匹配所有动作标记
    pattern = r'\[nori_motion:([^\]]+)\]'
    
    # 提取所有动作名
    motions = re.findall(pattern, content)
    
    # 剥离所有标记
    clean_content = re.sub(pattern, '', content)
    
    return clean_content.strip(), motions


def format_motion_marker(motion_name: str) -> str:
    """
    格式化动作标记
    
    Args:
        motion_name: 动作名
    
    Returns:
        格式化的动作标记字符串
    """
    return f"[nori_motion:{motion_name}]"


def validate_motion_name(name: str) -> bool:
    """
    验证动作名是否有效
    
    Args:
        name: 动作名
    
    Returns:
        是否有效
    """
    if not name or not name.strip():
        return False
    
    # 动作名只能包含字母、数字、下划线和连字符
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name.strip()))


def parse_motion_groups(raw_data: list[dict[str, Any]]) -> list[MotionGroup]:
    """
    解析动作组列表
    
    Args:
        raw_data: 原始字典列表
    
    Returns:
        MotionGroup 对象列表
    """
    groups = []
    for item in raw_data:
        try:
            group = MotionGroup.from_dict(item)
            if group.group and group.names:
                groups.append(group)
        except (KeyError, TypeError, ValueError):
            continue
    
    return groups
