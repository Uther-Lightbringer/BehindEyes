"""
动态上下文管理器
在场景生成阶段，智能加载相关上下文
"""

import logging
from typing import List, Dict, Any, Optional
from .models import (
    KnowledgeContext,
    CharacterRelation,
    WorldSetting,
)

logger = logging.getLogger(__name__)


class DynamicContextManager:
    """
    动态上下文管理器 - 在生成阶段使用

    职责：
    1. 根据当前场景加载相关角色信息
    2. 加载角色间关系
    3. 加载相关事件
    4. 加载世界设定
    5. 加载上级摘要
    6. Token 预算控制
    """

    # 上下文优先级（数字越小优先级越高）
    PRIORITY = {
        "character_info": 1,
        "character_relations": 2,
        "parent_summaries": 3,
        "related_events": 4,
        "world_settings": 5,
    }

    def __init__(self, db=None, token_limit: int = 2000):
        """
        初始化上下文管理器

        Args:
            db: 数据库实例
            token_limit: Token 预算上限
        """
        self.db = db
        self.token_limit = token_limit

    def load_context_for_scene(
        self,
        novel_id: str,
        current_chapter: int,
        current_segment: int = 0,
        involved_characters: List[str] = None,
        max_tokens: int = None
    ) -> KnowledgeContext:
        """
        为当前场景加载相关上下文

        Args:
            novel_id: 小说 ID
            current_chapter: 当前章节编号
            current_segment: 当前片段编号
            involved_characters: 场景涉及的角色名称列表
            max_tokens: Token 预算（可选）

        Returns:
            KnowledgeContext 对象
        """
        if max_tokens is None:
            max_tokens = self.token_limit

        context = KnowledgeContext(token_budget=max_tokens)

        if not self.db:
            return context

        # 1. 加载角色信息
        context.related_characters = self._load_character_info(
            novel_id, involved_characters
        )

        # 2. 加载角色关系
        context.character_relations = self._load_character_relations(
            novel_id, involved_characters
        )

        # 3. 加载相关事件
        context.related_events = self._load_related_events(
            novel_id, current_chapter
        )

        # 4. 加载世界设定
        context.world_settings = self._load_world_settings(
            novel_id, involved_characters
        )

        # 5. 加载上级摘要
        context.parent_summaries = self._load_parent_summaries(
            novel_id, current_chapter, current_segment
        )

        # 6. 提取关键词
        context.keywords = self._extract_keywords(context)

        # 7. Token 预算控制
        context = self._trim_to_token_limit(context, max_tokens)

        return context

    def _load_character_info(self, novel_id: str,
                             character_names: List[str] = None) -> List[Dict]:
        """
        加载角色详细信息

        Args:
            novel_id: 小说 ID
            character_names: 角色名称列表

        Returns:
            角色信息列表
        """
        if not self.db:
            return []

        all_characters = self.db.get_characters_by_novel(novel_id)

        if character_names:
            # 过滤指定角色
            filtered = []
            for char in all_characters:
                name = char.get("name", "")
                # 匹配名称或别名
                if name in character_names:
                    filtered.append(char)
                    continue
                aliases = char.get("aliases", [])
                if any(alias in character_names for alias in aliases):
                    filtered.append(char)
            return filtered

        return all_characters[:10]  # 限制数量

    def _load_character_relations(self, novel_id: str,
                                  character_names: List[str] = None) -> List[CharacterRelation]:
        """
        加载角色间关系

        Args:
            novel_id: 小说 ID
            character_names: 角色名称列表

        Returns:
            角色关系列表
        """
        if not self.db:
            return []

        relations = []

        if character_names:
            for name in character_names:
                char_relations = self.db.get_character_relations(novel_id, name)
                for rel in char_relations:
                    # 转换为 CharacterRelation 对象
                    relations.append(CharacterRelation(
                        char_a=rel["char_a"],
                        char_b=rel["char_b"],
                        relation_type=rel.get("relation_type", "陌生人"),
                        current_affection=rel.get("current_affection", 0),
                        base_affection=rel.get("base_affection", 0),
                        history=rel.get("history", []),
                        source_chapter=rel.get("source_chapter")
                    ))
        else:
            # 获取所有关系
            all_relations = self.db.get_character_relations(novel_id)
            for rel in all_relations[:20]:  # 限制数量
                relations.append(CharacterRelation(
                    char_a=rel["char_a"],
                    char_b=rel["char_b"],
                    relation_type=rel.get("relation_type", "陌生人"),
                    current_affection=rel.get("current_affection", 0),
                    base_affection=rel.get("base_affection", 0),
                    history=rel.get("history", []),
                    source_chapter=rel.get("source_chapter")
                ))

        # 去重
        seen = set()
        unique_relations = []
        for rel in relations:
            key = tuple(sorted([rel.char_a, rel.char_b]))
            if key not in seen:
                seen.add(key)
                unique_relations.append(rel)

        return unique_relations[:15]  # 限制数量

    def _load_related_events(self, novel_id: str, chapter: int) -> List[Dict]:
        """
        加载相关事件

        Args:
            novel_id: 小说 ID
            chapter: 当前章节

        Returns:
            事件列表
        """
        if not self.db:
            return []

        events = self.db.get_story_events_by_novel(novel_id)

        # 过滤当前章节附近的事件
        related_events = []
        for event in events:
            # 简单策略：返回所有事件，按时序排序
            related_events.append({
                "event_id": event.get("event_id"),
                "name": event.get("name", ""),
                "description": event.get("description", ""),
                "trigger_conditions": event.get("trigger_conditions", {})
            })

        return related_events[:10]  # 限制数量

    def _load_world_settings(self, novel_id: str,
                             keywords: List[str] = None) -> List[WorldSetting]:
        """
        根据关键词加载世界设定

        Args:
            novel_id: 小说 ID
            keywords: 关键词列表

        Returns:
            世界设定列表
        """
        if not self.db:
            return []

        all_settings = self.db.get_world_settings_by_novel(novel_id)

        settings = []
        for setting in all_settings:
            ws = WorldSetting(
                category=setting.get("category", ""),
                name=setting.get("name", ""),
                description=setting.get("description", ""),
                attributes=setting.get("attributes", {}),
                first_mention_chapter=setting.get("first_mention_chapter")
            )
            settings.append(ws)

        # 如果有关键词，优先匹配
        if keywords:
            matched = []
            for ws in settings:
                if any(kw in ws.name or kw in ws.description for kw in keywords):
                    matched.append(ws)
            if matched:
                return matched[:10]

        return settings[:10]  # 限制数量

    def _load_parent_summaries(self, novel_id: str, chapter: int,
                               segment: int) -> List[str]:
        """
        加载上级摘要

        Args:
            novel_id: 小说 ID
            chapter: 当前章节
            segment: 当前片段

        Returns:
            摘要列表
        """
        if not self.db:
            return []

        summaries = []

        # 获取小说级摘要
        novel_summaries = self.db.get_summary_tree_by_novel(novel_id, "novel")
        if novel_summaries:
            summaries.append(novel_summaries[0].get("summary", ""))

        # 获取卷级摘要（如果有）
        volume_summaries = self.db.get_summary_tree_by_novel(novel_id, "volume")
        for vs in volume_summaries[:2]:
            if vs.get("summary"):
                summaries.append(vs["summary"])

        # 获取前一章的摘要（作为上下文）
        if chapter > 1:
            prev_chapter_summaries = self.db.get_summary_tree_by_novel(novel_id, "chapter")
            for cs in prev_chapter_summaries:
                ref_id = cs.get("ref_id", "")
                try:
                    if ref_id and int(ref_id) == chapter - 1:
                        summaries.append(cs.get("summary", ""))
                        break
                except:
                    pass

        return [s for s in summaries if s and len(s) > 20][:3]  # 过滤过短的摘要

    def _extract_keywords(self, context: KnowledgeContext) -> List[str]:
        """从上下文中提取关键词"""
        keywords = []

        # 从角色名称提取
        for char in context.related_characters:
            if char.get("name"):
                keywords.append(char["name"])

        # 从世界设定提取
        for ws in context.world_settings:
            if ws.name:
                keywords.append(ws.name)

        # 从摘要中提取（简单实现：取前几个词）
        for summary in context.parent_summaries[:1]:
            words = summary.split()[:5]
            keywords.extend([w for w in words if len(w) >= 2])

        return list(set(keywords))[:15]

    def _trim_to_token_limit(self, context: KnowledgeContext,
                             max_tokens: int) -> KnowledgeContext:
        """
        根据 Token 预算裁剪上下文

        优先级：角色信息 > 角色关系 > 上级摘要 > 相关事件 > 世界设定

        Args:
            context: 原始上下文
            max_tokens: Token 预算

        Returns:
            裁剪后的上下文
        """
        # 粗略估算当前 token 数
        estimated = context.estimate_tokens()

        if estimated <= max_tokens:
            return context

        # 按优先级裁剪
        # 1. 先裁剪世界设定
        while estimated > max_tokens and context.world_settings:
            context.world_settings.pop()
            estimated = context.estimate_tokens()

        # 2. 裁剪相关事件
        while estimated > max_tokens and context.related_events:
            context.related_events.pop()
            estimated = context.estimate_tokens()

        # 3. 裁剪上级摘要
        while estimated > max_tokens and context.parent_summaries:
            context.parent_summaries.pop()
            estimated = context.estimate_tokens()

        # 4. 裁剪角色关系
        while estimated > max_tokens and context.character_relations:
            context.character_relations.pop()
            estimated = context.estimate_tokens()

        # 5. 最后裁剪角色信息（最高优先级，最后裁剪）
        while estimated > max_tokens and len(context.related_characters) > 3:
            context.related_characters.pop()
            estimated = context.estimate_tokens()

        return context

    def format_for_prompt(self, context: KnowledgeContext) -> str:
        """
        格式化为 Prompt 文本

        Args:
            context: 知识上下文

        Returns:
            格式化的文本
        """
        lines = []

        # 角色信息
        if context.related_characters:
            lines.append("【相关角色】")
            for char in context.related_characters[:5]:
                personality = char.get("personality", "")
                traits = char.get("personality_traits", [])
                traits_str = "、".join(traits[:3]) if traits else ""
                info = f"- {char.get('name', '未知')}"
                if personality:
                    info += f": {personality[:50]}"
                if traits_str:
                    info += f"（{traits_str}）"
                lines.append(info)

        # 角色关系
        if context.character_relations:
            lines.append("\n【角色关系】")
            for rel in context.character_relations[:5]:
                affection_str = f"(好感度: {rel.current_affection})"
                lines.append(
                    f"- {rel.char_a} 与 {rel.char_b}: {rel.relation_type} {affection_str}"
                )

        # 前文摘要
        if context.parent_summaries:
            lines.append("\n【前文摘要】")
            for i, summary in enumerate(context.parent_summaries[:2], 1):
                # 截断过长的摘要
                truncated = summary[:300] + "..." if len(summary) > 300 else summary
                lines.append(f"- {truncated}")

        # 相关事件
        if context.related_events:
            lines.append("\n【相关事件】")
            for event in context.related_events[:3]:
                desc = event.get("description", "")[:100]
                lines.append(f"- {event.get('name', event.get('event_id', '未知'))}: {desc}")

        # 世界设定
        if context.world_settings:
            lines.append("\n【世界设定】")
            for ws in context.world_settings[:5]:
                lines.append(f"- {ws.category}: {ws.name} - {ws.description[:50]}")

        return "\n".join(lines)

    def format_for_json(self, context: KnowledgeContext) -> Dict[str, Any]:
        """
        格式化为 JSON 格式（供程序使用）

        Args:
            context: 知识上下文

        Returns:
            JSON 字典
        """
        return {
            "characters": [
                {
                    "name": c.get("name"),
                    "personality": c.get("personality"),
                    "traits": c.get("personality_traits", [])
                }
                for c in context.related_characters[:10]
            ],
            "relations": [r.to_dict() for r in context.character_relations[:10]],
            "events": context.related_events[:10],
            "world_settings": [s.to_dict() for s in context.world_settings[:10]],
            "summaries": context.parent_summaries[:3],
            "keywords": context.keywords[:15]
        }
