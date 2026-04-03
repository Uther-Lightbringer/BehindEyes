"""
小说解析器 - 核心模块
从小说文本中提取角色、事件、剧情节点
"""

import re
import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Set
from collections import defaultdict


@dataclass
class Character:
    name: str
    aliases: List[str]  # 别名/昵称
    mentions: int  # 出现次数
    description: str  # 简短描述


@dataclass
class Event:
    id: int
    summary: str  # 事件摘要
    characters_involved: List[str]  # 涉及的角色
    chapter: int  # 章节
    keywords: List[str]  # 关键词


@dataclass
class PlotNode:
    id: int
    content: str  # 剧情内容
    choices: List[Dict]  # 选择列表
    next_node: int  # 默认下一节点
    characters: List[str]  # 出场的角色


class NovelParser:
    def __init__(self, text: str):
        self.text = text
        self.characters: Dict[str, Character] = {}
        self.events: List[Event] = []
        self.plot_nodes: List[PlotNode] = []

    def parse(self) -> Dict:
        """执行完整解析流程"""
        self._extract_characters()
        self._extract_events()
        self._build_plot_nodes()

        return {
            "characters": [asdict(c) for c in self.characters.values()],
            "events": [asdict(e) for e in self.events],
            "plot_nodes": [asdict(n) for n in self.plot_nodes]
        }

    def _extract_characters(self):
        """提取角色名（简单规则）"""
        # 匹配引号或特殊符号后的中文名字（2-4字）
        patterns = [
            r'[「"\']([A-Za-z\u4e00-\u9fa5]{2,4})[」"\'](?:说|道|问|答|笑|怒|叹|喊|叫|想|是|在|把|给|对|与|和|看)',
            r'([A-Za-z\u4e00-\u9fa5]{2,4})(?:说|道|问|答|笑|怒|叹|喊|叫|想)是',
            r'([A-Za-z\u4e00-\u9fa5]{2,4})(?:正|正在|的|在)',
        ]

        name_count = defaultdict(int)
        for pattern in patterns:
            matches = re.findall(pattern, self.text)
            for name in matches:
                if 2 <= len(name) <= 4 and name.encode('utf-8'):
                    name_count[name] += 1

        # 取出现次数最多的作为角色
        for name, count in sorted(name_count.items(), key=lambda x: -x[1])[:20]:
            if count >= 2:
                self.characters[name] = Character(
                    name=name,
                    aliases=[],
                    mentions=count,
                    description=""
                )

    def _extract_events(self):
        """提取关键事件"""
        # 按段落分割，检测对话和动作
        chapters = re.split(r'第[一二三四五六七八九十百千\d]+章', self.text)

        event_id = 0
        for idx, chapter_text in enumerate(chapters[1:], 1):  # 跳过第一个空段
            # 简单事件检测：包含角色名 + 动作词
            action_pattern = r'([，。]|[。！？])\1*'
            sentences = re.split(action_pattern, chapter_text)

            for sent in sentences:
                if len(sent) > 20 and any(name in sent for name in self.characters):
                    involved = [name for name in self.characters if name in sent]

                    self.events.append(Event(
                        id=event_id,
                        summary=sent[:100],
                        characters_involved=involved,
                        chapter=idx,
                        keywords=self._extract_keywords(sent)
                    ))
                    event_id += 1

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        keywords = []
        action_words = ['战斗', '相遇', '对话', '冲突', '和解', '死亡', '告白', '背叛', '发现', '秘密']
        for word in action_words:
            if word in text:
                keywords.append(word)
        return keywords

    def _build_plot_nodes(self):
        """构建剧情节点"""
        for idx, event in enumerate(self.events):
            choices = []
            if idx < len(self.events) - 1:
                # 为每个节点创建简单选择
                next_event = self.events[idx + 1]
                common_chars = set(event.characters_involved) & set(next_event.characters_involved)

                if common_chars:
                    choices.append({
                        "text": f"与{'、'.join(list(common_chars)[:2])}继续互动",
                        "next_node": idx + 1,
                        "effect": {}
                    })

            self.plot_nodes.append(PlotNode(
                id=idx,
                content=event.summary,
                choices=choices if choices else [{"text": "继续", "next_node": idx + 1, "effect": {}}],
                next_node=idx + 1 if idx < len(self.events) - 1 else -1,
                characters=event.characters_involved
            ))


def parse_novel_file(filepath: str) -> Dict:
    """解析小说文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    parser = NovelParser(text)
    result = parser.parse()

    # 输出到JSON
    output_path = filepath.replace('.txt', '_parsed.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


if __name__ == "__main__":
    # 测试解析
    sample_text = """
    第一章 初入江湖

    张三走在长安城的街道上，心中满是期待。他听说这里有一个神秘的剑客叫李四，剑法无双。
    李四此时正在城外的茶馆里喝茶，他感受到了张三点存在。
    张三拱手道：「久仰大名！」
    李四笑道：「彼此彼此。」

    第二章 酒楼冲突

    就在两人相谈甚欢之时，王五突然出现，他是本地的恶霸。
    王五冷笑一声：「这里是我们的地盘，识相的就滚！」
    张三怒道：「我偏不！」
    两人顿时剑拔弩张。
    """

    parser = NovelParser(sample_text)
    result = parser.parse()

    print("=== 解析结果 ===")
    print(f"角色数量: {len(result['characters'])}")
    print(f"事件数量: {len(result['events'])}")
    print(f"剧情节点: {len(result['plot_nodes'])}")
    print("\n角色列表:")
    for char in result['characters']:
        print(f"  - {char['name']}: 出现{char['mentions']}次")
