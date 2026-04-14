"""
层级摘要树
自底向上构建多层级摘要，支持动态上下文加载
"""

import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from .models import SummaryNode

logger = logging.getLogger(__name__)


# AI Prompt 模板
PROMPT_SUMMARY_MERGE = """请将以下多个摘要合并为一个更高级别的摘要。

合并要求：
1. 保留关键事件和角色
2. 去除重复信息
3. 保持逻辑连贯
4. 控制在 300 字以内

待合并的摘要：
{summaries}

请直接返回合并后的摘要文本，不需要 JSON 格式。
"""

PROMPT_NOVEL_SUMMARY = """请为以下小说生成一个总摘要。

小说标题：{title}
各卷摘要：
{volume_summaries}

要求：
1. 概括小说主题和主线剧情
2. 介绍主要角色
3. 控制在 500 字以内

请直接返回摘要文本。
"""


class HierarchicalSummaryTree:
    """层级摘要树管理器"""

    # 层级定义（从低到高）
    LEVELS = ["segment", "section", "chapter", "volume", "novel"]

    def __init__(self, llm_client=None, db=None):
        """
        初始化摘要树管理器

        Args:
            llm_client: LLM 客户端（用于摘要生成）
            db: 数据库实例
        """
        self.llm = llm_client
        self.db = db

    async def build_tree(self, novel_id: str, segments: List[Dict],
                         novel_title: str = "",
                         progress_callback=None) -> SummaryNode:
        """
        自底向上构建摘要树

        Args:
            novel_id: 小说 ID
            segments: 片段列表，每个片段包含 content, summary, chapter_id, segment_index
            novel_title: 小说标题
            progress_callback: 进度回调

        Returns:
            根节点（小说级摘要）
        """
        if not segments:
            return SummaryNode(level="novel", summary="无内容")

        # Level 1: 段落摘要（复用已有的 summary）
        segment_nodes = await self._build_segment_level(novel_id, segments)

        if progress_callback:
            progress_callback(1, 5, "段落摘要完成")

        # Level 2: 节摘要（合并相邻段落，每 3-5 个）
        section_nodes = await self._build_section_level(novel_id, segment_nodes)

        if progress_callback:
            progress_callback(2, 5, "节摘要完成")

        # Level 3: 章摘要
        chapter_nodes = await self._build_chapter_level(novel_id, section_nodes)

        if progress_callback:
            progress_callback(3, 5, "章摘要完成")

        # Level 4: 卷摘要（如果小说分卷）
        volume_nodes = await self._build_volume_level(novel_id, chapter_nodes)

        if progress_callback:
            progress_callback(4, 5, "卷摘要完成")

        # Level 5: 整部小说摘要
        novel_node = await self._build_novel_level(novel_id, volume_nodes, novel_title)

        if progress_callback:
            progress_callback(5, 5, "小说摘要完成")

        return novel_node

    async def _build_segment_level(self, novel_id: str,
                                   segments: List[Dict]) -> List[SummaryNode]:
        """构建段落级摘要节点"""
        nodes = []

        for seg in segments:
            # 复用已有的摘要，或生成新摘要
            summary = seg.get("summary", "")
            if not summary and seg.get("content"):
                summary = self._generate_simple_summary(seg["content"])

            node = SummaryNode(
                level="segment",
                summary=summary,
                ref_id=seg.get("id"),
                key_characters=seg.get("characters", []),
                keywords=self._extract_keywords(seg.get("content", ""))
            )

            # 保存到数据库
            node_id = f"sum_{uuid.uuid4().hex[:12]}"
            node.node_id = node_id
            if self.db:
                self.db.create_summary_node(
                    node_id=node_id,
                    novel_id=novel_id,
                    level="segment",
                    summary=summary,
                    ref_id=seg.get("id"),
                    key_characters=seg.get("characters", []),
                    keywords=node.keywords
                )

            nodes.append(node)

        return nodes

    async def _build_section_level(self, novel_id: str,
                                   segment_nodes: List[SummaryNode]) -> List[SummaryNode]:
        """构建节级摘要（合并相邻段落）"""
        nodes = []

        # 每 4 个段落合并为一个节
        chunk_size = 4
        for i in range(0, len(segment_nodes), chunk_size):
            chunk = segment_nodes[i:i + chunk_size]

            # 合并摘要
            merged_summary = await self._merge_summaries([n.summary for n in chunk])

            # 合并关键词和角色
            all_keywords = []
            all_characters = []
            for n in chunk:
                all_keywords.extend(n.keywords)
                all_characters.extend(n.key_characters)

            node = SummaryNode(
                level="section",
                summary=merged_summary,
                key_characters=list(set(all_characters))[:10],
                keywords=list(set(all_keywords))[:15]
            )

            # 保存
            node_id = f"sum_{uuid.uuid4().hex[:12]}"
            node.node_id = node_id
            node.children = chunk

            # 设置子节点的 parent_id
            for child in chunk:
                child.parent_id = node_id

            if self.db:
                self.db.create_summary_node(
                    node_id=node_id,
                    novel_id=novel_id,
                    level="section",
                    summary=merged_summary,
                    key_characters=node.key_characters,
                    keywords=node.keywords
                )

            nodes.append(node)

        return nodes

    async def _build_chapter_level(self, novel_id: str,
                                   section_nodes: List[SummaryNode]) -> List[SummaryNode]:
        """构建章级摘要"""
        nodes = []

        # 按章节分组
        chapter_groups = {}
        for node in section_nodes:
            # 从 ref_id 或 children 获取章节信息
            chapter_id = self._get_chapter_from_node(node)
            if chapter_id not in chapter_groups:
                chapter_groups[chapter_id] = []
            chapter_groups[chapter_id].append(node)

        for chapter_id, sections in chapter_groups.items():
            if not sections:
                continue

            merged_summary = await self._merge_summaries([n.summary for n in sections])

            all_keywords = []
            all_characters = []
            for n in sections:
                all_keywords.extend(n.keywords)
                all_characters.extend(n.key_characters)

            node = SummaryNode(
                level="chapter",
                summary=merged_summary,
                ref_id=str(chapter_id),
                key_characters=list(set(all_characters))[:10],
                keywords=list(set(all_keywords))[:15]
            )

            node_id = f"sum_{uuid.uuid4().hex[:12]}"
            node.node_id = node_id
            node.children = sections

            for child in sections:
                child.parent_id = node_id

            if self.db:
                self.db.create_summary_node(
                    node_id=node_id,
                    novel_id=novel_id,
                    level="chapter",
                    summary=merged_summary,
                    ref_id=str(chapter_id),
                    key_characters=node.key_characters,
                    keywords=node.keywords
                )

            nodes.append(node)

        return nodes

    async def _build_volume_level(self, novel_id: str,
                                  chapter_nodes: List[SummaryNode]) -> List[SummaryNode]:
        """构建卷级摘要"""
        # 如果章节数量较少，直接返回
        if len(chapter_nodes) <= 10:
            return chapter_nodes

        nodes = []

        # 每 10 章合并为一卷
        chunk_size = 10
        volume_num = 1
        for i in range(0, len(chapter_nodes), chunk_size):
            chunk = chapter_nodes[i:i + chunk_size]

            merged_summary = await self._merge_summaries([n.summary for n in chunk])

            all_keywords = []
            all_characters = []
            for n in chunk:
                all_keywords.extend(n.keywords)
                all_characters.extend(n.key_characters)

            node = SummaryNode(
                level="volume",
                summary=merged_summary,
                ref_id=f"volume_{volume_num}",
                key_characters=list(set(all_characters))[:10],
                keywords=list(set(all_keywords))[:15]
            )

            node_id = f"sum_{uuid.uuid4().hex[:12]}"
            node.node_id = node_id
            node.children = chunk

            for child in chunk:
                child.parent_id = node_id

            if self.db:
                self.db.create_summary_node(
                    node_id=node_id,
                    novel_id=novel_id,
                    level="volume",
                    summary=merged_summary,
                    ref_id=f"volume_{volume_num}",
                    key_characters=node.key_characters,
                    keywords=node.keywords
                )

            nodes.append(node)
            volume_num += 1

        return nodes

    async def _build_novel_level(self, novel_id: str,
                                 volume_nodes: List[SummaryNode],
                                 novel_title: str) -> SummaryNode:
        """构建小说级摘要"""
        if not volume_nodes:
            return SummaryNode(
                level="novel",
                summary="无内容",
                node_id=f"sum_{uuid.uuid4().hex[:12]}"
            )

        # 合并所有卷摘要
        if len(volume_nodes) == 1:
            # 只有一卷，直接使用
            merged_summary = volume_nodes[0].summary
        else:
            merged_summary = await self._merge_summaries([n.summary for n in volume_nodes])

        # 如果有 LLM，生成更好的总摘要
        if self.llm and len(volume_nodes) > 1:
            try:
                prompt = PROMPT_NOVEL_SUMMARY.format(
                    title=novel_title,
                    volume_summaries="\n\n".join([f"第{i+1}部分：{n.summary[:200]}"
                                                  for i, n in enumerate(volume_nodes[:5])])
                )
                ai_summary = await self.llm.chat(prompt)
                if ai_summary and len(ai_summary) > 50:
                    merged_summary = ai_summary[:500]
            except Exception as e:
                logger.warning(f"AI 生成总摘要失败: {e}")

        # 合并所有关键词和角色
        all_keywords = []
        all_characters = []
        for n in volume_nodes:
            all_keywords.extend(n.keywords)
            all_characters.extend(n.key_characters)

        node = SummaryNode(
            level="novel",
            summary=merged_summary,
            key_characters=list(set(all_characters))[:15],
            keywords=list(set(all_keywords))[:20]
        )

        node_id = f"sum_{uuid.uuid4().hex[:12]}"
        node.node_id = node_id
        node.children = volume_nodes

        for child in volume_nodes:
            child.parent_id = node_id

        if self.db:
            self.db.create_summary_node(
                node_id=node_id,
                novel_id=novel_id,
                level="novel",
                summary=merged_summary,
                key_characters=node.key_characters,
                keywords=node.keywords
            )

        return node

    async def _merge_summaries(self, summaries: List[str]) -> str:
        """合并多个摘要"""
        if not summaries:
            return ""

        # 过滤空摘要
        valid_summaries = [s for s in summaries if s and len(s) > 10]
        if not valid_summaries:
            return ""

        if len(valid_summaries) == 1:
            return valid_summaries[0]

        # 如果有 LLM，使用 AI 合并
        if self.llm:
            try:
                prompt = PROMPT_SUMMARY_MERGE.format(
                    summaries="\n\n".join([f"{i+1}. {s[:300]}" for i, s in enumerate(valid_summaries[:5])])
                )
                merged = await self.llm.chat(prompt)
                if merged and len(merged) > 20:
                    return merged[:500]
            except Exception as e:
                logger.warning(f"AI 合并摘要失败: {e}")

        # 降级：简单拼接
        return "；".join(valid_summaries[:3])[:500]

    def _generate_simple_summary(self, text: str, max_length: int = 200) -> str:
        """生成简单摘要（取文本开头）"""
        if not text:
            return ""

        # 去除空白字符
        clean_text = " ".join(text.split())

        if len(clean_text) <= max_length:
            return clean_text

        # 尝试在句子结束处截断
        end_pos = clean_text.find("。", max_length - 50)
        if end_pos > 0 and end_pos < max_length + 50:
            return clean_text[:end_pos + 1]

        return clean_text[:max_length] + "……"

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简单实现）"""
        if not text:
            return []

        keywords = []

        # 提取人名（简单规则：2-4 个汉字，首字母大写的词）
        import re
        name_pattern = r'[\u4e00-\u9fa5]{2,4}(?=说|道|问|答|笑|哭|喊|叫)'
        names = re.findall(name_pattern, text)
        keywords.extend(names[:5])

        # 提取地点
        location_pattern = r'在([\u4e00-\u9fa5]{2,6})(?=里|中|外|内)'
        locations = re.findall(location_pattern, text)
        keywords.extend(locations[:3])

        return list(set(keywords))[:10]

    def _get_chapter_from_node(self, node: SummaryNode) -> int:
        """从节点获取章节编号"""
        if node.ref_id:
            try:
                # 尝试从 ref_id 解析章节号
                if isinstance(node.ref_id, int):
                    return node.ref_id
                if node.ref_id.startswith("chapter_"):
                    return int(node.ref_id.replace("chapter_", ""))
                return int(node.ref_id)
            except:
                pass

        # 从子节点递归查找
        if node.children:
            return self._get_chapter_from_node(node.children[0])

        return 0

    def get_ancestor_summaries(self, node_id: str, levels: int = 2) -> List[str]:
        """
        获取上级摘要（用于上下文加载）

        Args:
            node_id: 当前节点 ID
            levels: 向上查找的层级数

        Returns:
            祖先摘要列表
        """
        summaries = []

        if not self.db:
            return summaries

        current_id = node_id
        for _ in range(levels):
            node = self.db.get_summary_node(current_id)
            if not node:
                break

            if node.get("parent_id"):
                parent = self.db.get_summary_node(node["parent_id"])
                if parent and parent.get("summary"):
                    summaries.append(parent["summary"])
                current_id = node["parent_id"]
            else:
                break

        return summaries

    def get_sibling_summaries(self, node_id: str) -> List[str]:
        """
        获取同级摘要（用于关联上下文）

        Args:
            node_id: 当前节点 ID

        Returns:
            同级摘要列表
        """
        summaries = []

        if not self.db:
            return summaries

        node = self.db.get_summary_node(node_id)
        if not node or not node.get("parent_id"):
            return summaries

        # 获取父节点的所有子节点
        siblings = self.db.get_summary_children(node["parent_id"])
        for sibling in siblings:
            if sibling.get("node_id") != node_id and sibling.get("summary"):
                summaries.append(sibling["summary"])

        return summaries[:3]  # 最多返回 3 个同级摘要
