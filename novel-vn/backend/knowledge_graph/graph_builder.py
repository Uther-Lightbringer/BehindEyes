"""
知识图谱构建器
在小说解析阶段构建角色关系网络、事件因果链、世界设定
"""

import json
import uuid
import re
import logging
from typing import List, Dict, Any, Optional
from .models import (
    CharacterRelation,
    EventLink,
    SummaryNode,
    WorldSetting,
    get_default_affection,
)

logger = logging.getLogger(__name__)


# AI Prompt 模板
PROMPT_EXTRACT_RELATIONS = """分析以下小说文本，提取角色之间的关系。

请以 JSON 格式返回，格式如下：
{
  "relations": [
    {
      "char_a": "角色A名称",
      "char_b": "角色B名称",
      "relation_type": "关系类型（朋友/敌人/师徒/恋人/家人/陌生人等）",
      "affection": 好感度数值（-100到100）,
      "evidence": "关系依据（引用原文）"
    }
  ]
}

小说标题：{title}
章节：第{chapter}章

文本内容：
{text}

注意：
1. 只提取有明确关系描述的角色对
2. 关系类型要准确
3. 好感度根据文本描写判断
"""

PROMPT_EXTRACT_WORLD_SETTINGS = """分析以下小说文本，提取世界设定信息。

请以 JSON 格式返回，格式如下：
{
  "locations": [
    {"name": "地点名称", "description": "地点描述", "attributes": {}}
  ],
  "items": [
    {"name": "物品名称", "description": "物品描述", "attributes": {}}
  ],
  "concepts": [
    {"name": "概念名称", "description": "概念描述", "attributes": {}}
  ],
  "abilities": [
    {"name": "能力名称", "description": "能力描述", "attributes": {}}
  ]
}

小说标题：{title}
章节：第{chapter}章

文本内容：
{text}

注意：
1. 只提取有明确描述的设定
2. 重要的世界观元素要提取
3. 属性可以包含额外信息如威力等级、稀有度等
"""


class KnowledgeGraphBuilder:
    """知识图谱构建器 - 在解析阶段构建"""

    def __init__(self, llm_client=None, db=None):
        """
        初始化知识图谱构建器

        Args:
            llm_client: LLM 客户端（可选，用于 AI 分析）
            db: 数据库实例
        """
        self.llm = llm_client
        self.db = db

    async def build_from_novel(self, novel_id: str, chapters: List[Dict],
                               characters: List[Dict] = None,
                               progress_callback=None) -> Dict[str, Any]:
        """
        从小说构建完整知识图谱

        Args:
            novel_id: 小说 ID
            chapters: 章节列表，每个章节包含 title, content, chapter_id
            characters: 角色列表（可选）
            progress_callback: 进度回调函数

        Returns:
            构建的知识图谱统计信息
        """
        stats = {
            "relations": 0,
            "event_chains": 0,
            "summary_nodes": 0,
            "world_settings": 0
        }

        total_steps = len(chapters) + 2
        current_step = 0

        # 1. 构建角色关系网络
        if progress_callback:
            progress_callback(current_step, total_steps, "正在构建角色关系网络...")

        relations = await self._build_character_relations(novel_id, chapters, characters)
        stats["relations"] = len(relations)
        current_step += 1

        # 2. 构建事件因果链
        if progress_callback:
            progress_callback(current_step, total_steps, "正在构建事件因果链...")

        event_chains = await self._build_event_chains(novel_id)
        stats["event_chains"] = len(event_chains)
        current_step += 1

        # 3. 提取世界设定
        for chapter in chapters:
            if progress_callback:
                progress_callback(current_step, total_steps,
                                f"正在提取第{chapter.get('chapter_id', current_step)}章的世界设定...")

            settings = await self._extract_world_settings_from_chapter(
                novel_id, chapter.get("content", ""), chapter.get("title", ""),
                chapter.get("chapter_id", 0)
            )
            stats["world_settings"] += len(settings)
            current_step += 1

        logger.info(f"知识图谱构建完成: {stats}")
        return stats

    async def _build_character_relations(self, novel_id: str,
                                         chapters: List[Dict],
                                         characters: List[Dict] = None) -> List[CharacterRelation]:
        """
        构建角色关系网络

        策略：
        1. 如果有 LLM 客户端，使用 AI 分析角色关系
        2. 否则使用规则提取
        """
        relations = []
        char_names = set()

        # 收集角色名称
        if characters:
            for c in characters:
                char_names.add(c.get("name", ""))
                # 也收集别名
                for alias in c.get("aliases", []):
                    char_names.add(alias)

        # 遍历章节提取关系
        for chapter in chapters:
            content = chapter.get("content", "")
            chapter_id = chapter.get("chapter_id", 0)

            if self.llm:
                # 使用 AI 分析
                chapter_relations = await self._extract_relations_with_ai(
                    novel_id, content, char_names, chapter_id
                )
            else:
                # 使用规则提取
                chapter_relations = self._extract_relations_with_rules(
                    novel_id, content, char_names, chapter_id
                )

            relations.extend(chapter_relations)

        # 合并和去重
        merged_relations = self._merge_relations(relations)

        # 存储到数据库
        if self.db:
            for rel in merged_relations:
                self._save_relation_to_db(novel_id, rel)

        return merged_relations

    async def _extract_relations_with_ai(self, novel_id: str, content: str,
                                         char_names: set, chapter_id: int) -> List[CharacterRelation]:
        """使用 AI 提取角色关系"""
        relations = []

        if not self.llm or not content:
            return relations

        try:
            prompt = PROMPT_EXTRACT_RELATIONS.format(
                title="",
                chapter=chapter_id,
                text=content[:3000]  # 限制长度
            )

            response = await self.llm.chat(prompt)
            data = self._parse_json_response(response)

            if data and "relations" in data:
                for r in data["relations"]:
                    char_a = r.get("char_a", "")
                    char_b = r.get("char_b", "")

                    # 验证角色名称
                    if char_a and char_b and (char_a in char_names or char_b in char_names or len(char_names) == 0):
                        relations.append(CharacterRelation(
                            char_a=char_a,
                            char_b=char_b,
                            relation_type=r.get("relation_type", "陌生人"),
                            current_affection=r.get("affection", 0),
                            base_affection=r.get("affection", 0),
                            source_chapter=chapter_id
                        ))
        except Exception as e:
            logger.warning(f"AI 提取角色关系失败: {e}")

        return relations

    def _extract_relations_with_rules(self, novel_id: str, content: str,
                                      char_names: set, chapter_id: int) -> List[CharacterRelation]:
        """使用规则提取角色关系"""
        relations = []

        # 关系关键词模式
        relation_patterns = [
            (r"(\w+)是(\w+)的(师父|师傅|徒弟|师兄|师弟|师姐|师妹)", "师徒"),
            (r"(\w+)和(\w+)是(朋友|好友|挚友|死党)", "朋友"),
            (r"(\w+)与(\w+)是(敌人|死敌|仇人)", "敌人"),
            (r"(\w+)是(\w+)的(父亲|母亲|哥哥|姐姐|弟弟|妹妹)", "家人"),
            (r"(\w+)和(\w+)(相爱|相爱了|在一起|结为夫妻)", "恋人"),
            (r"(\w+)对(\w+)(心生爱慕|暗恋|喜欢)", "暗恋"),
        ]

        for pattern, relation_type in relation_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                char_a, char_b = match[0], match[1]
                if char_a and char_b and len(char_a) >= 2 and len(char_b) >= 2:
                    affection = get_default_affection(relation_type)
                    relations.append(CharacterRelation(
                        char_a=char_a,
                        char_b=char_b,
                        relation_type=relation_type,
                        current_affection=affection,
                        base_affection=affection,
                        source_chapter=chapter_id
                    ))

        return relations

    def _merge_relations(self, relations: List[CharacterRelation]) -> List[CharacterRelation]:
        """合并相同角色对的关系"""
        merged = {}

        for rel in relations:
            # 规范化键（按字母序排列）
            key = tuple(sorted([rel.char_a, rel.char_b]))

            if key in merged:
                existing = merged[key]
                # 更新好感度（取最新值）
                if rel.source_chapter and (not existing.source_chapter or
                                          rel.source_chapter > existing.source_chapter):
                    existing.current_affection = rel.current_affection
                    existing.source_chapter = rel.source_chapter
                    # 如果关系类型更具体，更新
                    if rel.relation_type != "陌生人":
                        existing.relation_type = rel.relation_type
            else:
                merged[key] = rel

        return list(merged.values())

    def _save_relation_to_db(self, novel_id: str, relation: CharacterRelation):
        """保存关系到数据库"""
        if not self.db:
            return

        relation_id = f"rel_{uuid.uuid4().hex[:12]}"
        self.db.create_character_relation(
            relation_id=relation_id,
            novel_id=novel_id,
            char_a=relation.char_a,
            char_b=relation.char_b,
            relation_type=relation.relation_type,
            base_affection=relation.base_affection,
            current_affection=relation.current_affection,
            history=relation.history,
            source_chapter=relation.source_chapter
        )

    async def _build_event_chains(self, novel_id: str) -> List[EventLink]:
        """
        构建事件因果链

        从 story_events 表读取事件，分析事件间的因果关系
        """
        event_chains = []

        if not self.db:
            return event_chains

        # 获取所有事件
        events = self.db.get_story_events_by_novel(novel_id)

        if not events:
            return event_chains

        # 简单策略：按 temporal_order 排序，相邻事件可能有因果关系
        events_sorted = sorted(events, key=lambda e: e.get("temporal_order", 0))

        for i, event in enumerate(events_sorted):
            link = EventLink(
                event_id=event.get("event_id", ""),
                temporal_order=event.get("temporal_order", i),
                prerequisite_events=[events_sorted[i-1].get("event_id")] if i > 0 else [],
                subsequent_events=[events_sorted[i+1].get("event_id")] if i < len(events_sorted) - 1 else []
            )
            event_chains.append(link)

            # 保存到数据库
            chain_id = f"chain_{uuid.uuid4().hex[:12]}"
            self.db.create_event_chain(
                chain_id=chain_id,
                novel_id=novel_id,
                event_id=link.event_id,
                prerequisite_events=link.prerequisite_events,
                subsequent_events=link.subsequent_events,
                temporal_order=link.temporal_order
            )

        return event_chains

    async def _extract_world_settings_from_chapter(self, novel_id: str, content: str,
                                                   title: str, chapter_id: int) -> List[WorldSetting]:
        """从章节提取世界设定"""
        settings = []

        if not content:
            return settings

        if self.llm:
            # 使用 AI 提取
            settings = await self._extract_settings_with_ai(novel_id, content, title, chapter_id)
        else:
            # 使用规则提取
            settings = self._extract_settings_with_rules(novel_id, content, chapter_id)

        # 保存到数据库
        if self.db:
            for setting in settings:
                setting_id = f"ws_{uuid.uuid4().hex[:12]}"
                self.db.create_world_setting(
                    setting_id=setting_id,
                    novel_id=novel_id,
                    category=setting.category,
                    name=setting.name,
                    description=setting.description,
                    attributes=setting.attributes,
                    first_mention_chapter=setting.first_mention_chapter,
                    source_text=setting.source_text
                )

        return settings

    async def _extract_settings_with_ai(self, novel_id: str, content: str,
                                        title: str, chapter_id: int) -> List[WorldSetting]:
        """使用 AI 提取世界设定"""
        settings = []

        if not self.llm:
            return settings

        try:
            prompt = PROMPT_EXTRACT_WORLD_SETTINGS.format(
                title=title,
                chapter=chapter_id,
                text=content[:3000]
            )

            response = await self.llm.chat(prompt)
            data = self._parse_json_response(response)

            if data:
                for category in ["locations", "items", "concepts", "abilities"]:
                    category_map = {
                        "locations": "location",
                        "items": "item",
                        "concepts": "concept",
                        "abilities": "ability"
                    }
                    items = data.get(category, [])
                    for item in items:
                        settings.append(WorldSetting(
                            category=category_map.get(category, category),
                            name=item.get("name", ""),
                            description=item.get("description", ""),
                            attributes=item.get("attributes", {}),
                            first_mention_chapter=chapter_id
                        ))
        except Exception as e:
            logger.warning(f"AI 提取世界设定失败: {e}")

        return settings

    def _extract_settings_with_rules(self, novel_id: str, content: str,
                                     chapter_id: int) -> List[WorldSetting]:
        """使用规则提取世界设定"""
        settings = []

        # 地点模式
        location_patterns = [
            r"在([\u4e00-\u9fa5]{2,8})(城|镇|村|山|谷|宫|殿|阁|楼|府|院|岛|海|江|河)",
            r"来到([\u4e00-\u9fa5]{2,8})",
            r"身处([\u4e00-\u9fa5]{2,8})",
        ]

        for pattern in location_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                name = match if isinstance(match, str) else match[0]
                if len(name) >= 2:
                    settings.append(WorldSetting(
                        category="location",
                        name=name,
                        description="",
                        first_mention_chapter=chapter_id
                    ))

        # 去重
        seen = set()
        unique_settings = []
        for s in settings:
            key = (s.category, s.name)
            if key not in seen:
                seen.add(key)
                unique_settings.append(s)

        return unique_settings

    def _parse_json_response(self, response: str) -> Optional[Dict]:
        """解析 AI 响应中的 JSON"""
        if not response:
            return None

        # 尝试直接解析
        try:
            return json.loads(response)
        except:
            pass

        # 尝试提取 JSON 块
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass

        # 尝试查找花括号包围的内容
        brace_match = re.search(r'\{[\s\S]*\}', response)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except:
                pass

        return None

    def clear_knowledge_graph(self, novel_id: str):
        """清除小说的知识图谱数据"""
        if self.db:
            self.db.delete_character_relations_by_novel(novel_id)
            self.db.delete_event_chains_by_novel(novel_id)
            self.db.delete_summary_tree_by_novel(novel_id)
            self.db.delete_world_settings_by_novel(novel_id)
            logger.info(f"已清除小说 {novel_id} 的知识图谱数据")
