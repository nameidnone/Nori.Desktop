"""
Nori Core Skills Module - Python 实现

内置技能预设，对应 C# SkillPresets.cs
"""

from dataclasses import dataclass


@dataclass
class SkillPreset:
    """技能预设定义"""
    id: str
    name: str
    description: str
    instructions: str
    category: str = "productivity"
    tags: list[str] = None
    icon: str = "sparkles"
    author: str = "Nori Team"
    version: str = "1.0.0"
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class SkillPresets:
    """内置技能预设集合"""
    
    ALL = [
        SkillPreset(
            id="summarizer",
            name="内容总结助手",
            description="快速总结长文本、文章、对话的核心要点",
            instructions="""
## 内容总结技能
当用户要求总结内容时：
1. 提取关键信息和核心观点
2. 用简洁的语言概括主要内容
3. 保持原文的逻辑结构
4. 突出重要结论和行动项
""".strip(),
            category="productivity",
            tags=["summary", "text-processing"],
            icon="file-text",
        ),
        SkillPreset(
            id="translator",
            name="多语言翻译",
            description="支持多种语言之间的准确翻译",
            instructions="""
## 翻译技能
当用户需要翻译时：
1. 识别源语言和目标语言
2. 保持原文的语气和风格
3. 注意文化差异和习语表达
4. 对专业术语保持一致性
""".strip(),
            category="communication",
            tags=["translation", "language"],
            icon="globe",
        ),
        SkillPreset(
            id="code-helper",
            name="编程助手",
            description="代码解释、调试、优化建议",
            instructions="""
## 编程助手技能
当用户询问代码相关问题时：
1. 理解代码的上下文和目的
2. 提供清晰的解释和说明
3. 指出潜在问题和改进建议
4. 给出可运行的示例代码
5. 遵循最佳实践和安全规范
""".strip(),
            category="development",
            tags=["coding", "debugging", "review"],
            icon="code",
        ),
        SkillPreset(
            id="creative-writer",
            name="创意写作",
            description="帮助创作文案、故事、诗歌等创意内容",
            instructions="""
## 创意写作技能
当用户需要创意写作帮助时：
1. 理解写作目的和受众
2. 提供富有创意的内容建议
3. 保持文风一致性和连贯性
4. 适当运用修辞手法增强表现力
""".strip(),
            category="creativity",
            tags=["writing", "creative", "content"],
            icon="pen-tool",
        ),
        SkillPreset(
            id="research-assistant",
            name="研究助手",
            description="帮助收集信息、整理资料、分析数据",
            instructions="""
## 研究助手技能
当用户需要进行研究或学习时：
1. 帮助梳理研究问题和目标
2. 提供相关信息和背景知识
3. 整理和归纳收集到的资料
4. 分析数据并得出结论
5. 标注信息来源和参考资料
""".strip(),
            category="education",
            tags=["research", "learning", "analysis"],
            icon="book-open",
        ),
    ]
    
    @classmethod
    def get_by_id(cls, skill_id: str) -> SkillPreset | None:
        """根据 ID 获取技能预设"""
        for preset in cls.ALL:
            if preset.id == skill_id:
                return preset
        return None
    
    @classmethod
    def get_by_category(cls, category: str) -> list[SkillPreset]:
        """根据分类获取技能预设"""
        return [p for p in cls.ALL if p.category == category]


__all__ = [
    "SkillPreset",
    "SkillPresets",
]
