"""
知识图谱模块
提供长篇小说的知识图谱构建和查询能力
"""

from .models import (
    CharacterRelation,
    EventLink,
    SummaryNode,
    WorldSetting,
    KnowledgeContext,
)
from .graph_builder import KnowledgeGraphBuilder
from .summary_tree import HierarchicalSummaryTree
from .context_manager import DynamicContextManager

__all__ = [
    # 数据模型
    "CharacterRelation",
    "EventLink",
    "SummaryNode",
    "WorldSetting",
    "KnowledgeContext",
    # 核心组件
    "KnowledgeGraphBuilder",
    "HierarchicalSummaryTree",
    "DynamicContextManager",
]
