"""
知识图谱数据模型
定义角色关系、事件链、摘要树、世界设定等核心数据结构
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class CharacterRelation:
    """角色关系"""
    char_a: str
    char_b: str
    relation_type: str = "陌生人"
    base_affection: int = 0
    current_affection: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    source_chapter: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "char_a": self.char_a,
            "char_b": self.char_b,
            "relation_type": self.relation_type,
            "base_affection": self.base_affection,
            "current_affection": self.current_affection,
            "history": self.history,
            "source_chapter": self.source_chapter
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterRelation":
        return cls(
            char_a=data["char_a"],
            char_b=data["char_b"],
            relation_type=data.get("relation_type", "陌生人"),
            base_affection=data.get("base_affection", 0),
            current_affection=data.get("current_affection", 0),
            history=data.get("history", []),
            source_chapter=data.get("source_chapter")
        )


@dataclass
class EventLink:
    """事件因果链接"""
    event_id: str
    prerequisite_events: List[str] = field(default_factory=list)
    subsequent_events: List[str] = field(default_factory=list)
    mutually_exclusive: List[str] = field(default_factory=list)
    temporal_order: int = 0
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "prerequisite_events": self.prerequisite_events,
            "subsequent_events": self.subsequent_events,
            "mutually_exclusive": self.mutually_exclusive,
            "temporal_order": self.temporal_order,
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventLink":
        return cls(
            event_id=data["event_id"],
            prerequisite_events=data.get("prerequisite_events", []),
            subsequent_events=data.get("subsequent_events", []),
            mutually_exclusive=data.get("mutually_exclusive", []),
            temporal_order=data.get("temporal_order", 0),
            confidence=data.get("confidence", 1.0)
        )


@dataclass
class SummaryNode:
    """摘要树节点"""
    level: str  # novel/volume/chapter/section/segment
    summary: str
    key_characters: List[str] = field(default_factory=list)
    key_events: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    node_id: Optional[str] = None
    parent_id: Optional[str] = None
    ref_id: Optional[str] = None  # 对应的章节/片段 ID
    children: List["SummaryNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "level": self.level,
            "summary": self.summary,
            "key_characters": self.key_characters,
            "key_events": self.key_events,
            "keywords": self.keywords,
            "parent_id": self.parent_id,
            "ref_id": self.ref_id,
            "children": [c.to_dict() for c in self.children] if self.children else []
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SummaryNode":
        node = cls(
            level=data["level"],
            summary=data["summary"],
            key_characters=data.get("key_characters", []),
            key_events=data.get("key_events", []),
            keywords=data.get("keywords", []),
            node_id=data.get("node_id"),
            parent_id=data.get("parent_id"),
            ref_id=data.get("ref_id")
        )
        if data.get("children"):
            node.children = [cls.from_dict(c) for c in data["children"]]
        return node


@dataclass
class WorldSetting:
    """世界设定"""
    category: str  # location/item/concept/ability
    name: str
    description: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    first_mention_chapter: Optional[int] = None
    source_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "attributes": self.attributes,
            "first_mention_chapter": self.first_mention_chapter,
            "source_text": self.source_text
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldSetting":
        return cls(
            category=data["category"],
            name=data["name"],
            description=data.get("description", ""),
            attributes=data.get("attributes", {}),
            first_mention_chapter=data.get("first_mention_chapter"),
            source_text=data.get("source_text")
        )


@dataclass
class KnowledgeContext:
    """
    知识图谱上下文 - 用于传递给 AI 生成器

    包含当前场景相关的所有知识信息：
    - 相关角色信息
    - 角色间关系
    - 相关事件
    - 世界设定
    - 上级摘要
    - 关键词
    """
    # 相关角色信息
    related_characters: List[Dict[str, Any]] = field(default_factory=list)
    # 角色间关系
    character_relations: List[CharacterRelation] = field(default_factory=list)
    # 相关事件
    related_events: List[Dict[str, Any]] = field(default_factory=list)
    # 世界设定
    world_settings: List[WorldSetting] = field(default_factory=list)
    # 上级摘要（父级上下文）
    parent_summaries: List[str] = field(default_factory=list)
    # 关键词
    keywords: List[str] = field(default_factory=list)
    # Token 预算
    token_budget: int = 2000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "related_characters": self.related_characters,
            "character_relations": [r.to_dict() for r in self.character_relations],
            "related_events": self.related_events,
            "world_settings": [s.to_dict() for s in self.world_settings],
            "parent_summaries": self.parent_summaries,
            "keywords": self.keywords,
            "token_budget": self.token_budget
        }

    def estimate_tokens(self) -> int:
        """估算当前上下文的 token 数量（粗略估计：每 4 字符约 1 token）"""
        total_chars = 0
        total_chars += sum(len(str(c)) for c in self.related_characters)
        total_chars += sum(len(r.summary or "") + len(r.char_a) + len(r.char_b)
                          for r in self.character_relations)
        total_chars += sum(len(str(e)) for e in self.related_events)
        total_chars += sum(len(s.description or "") + len(s.name) for s in self.world_settings)
        total_chars += sum(len(s) for s in self.parent_summaries)
        return total_chars // 4  # 粗略估计


# 关系类型常量
RELATION_TYPES = {
    "陌生人": 0,
    "熟人": 10,
    "朋友": 30,
    "好友": 50,
    "挚友": 70,
    "恋人": 80,
    "夫妻": 90,
    "家人": 80,
    "师徒": 40,
    "同门": 25,
    "同僚": 20,
    "对手": -20,
    "敌人": -50,
    "死敌": -80,
}

# 关系类型到好感度的默认映射
DEFAULT_AFFECTION_MAP = {
    "陌生人": 0,
    "熟人": 10,
    "朋友": 30,
    "好友": 50,
    "挚友": 70,
    "恋人": 80,
    "夫妻": 90,
    "家人": 80,
    "师徒": 40,
    "同门": 25,
    "同僚": 20,
    "对手": -20,
    "敌人": -50,
    "死敌": -80,
}


def get_default_affection(relation_type: str) -> int:
    """根据关系类型获取默认好感度"""
    return DEFAULT_AFFECTION_MAP.get(relation_type, 0)
