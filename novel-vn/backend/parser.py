"""
小说解析模块（本地规则增强）
"""

import re
import json
from typing import Dict, List, Any


class NovelParser:
    """小说文本解析器"""

    def __init__(self):
        self.characters = {}
        self.scenes = []

    @staticmethod
    def split_chapters(text: str) -> List[Dict[str, Any]]:
        """
        自动分割章节
        支持格式：
        - 第1章
        - 第一章
        - Chapter 1
        - == 第1章 ==
        """
        # 章节分割模式
        patterns = [
            r'(?:^|\n)(={2,}\s*)(第[一二三四五六七八九十百千\d]+章[^=\n]*)\1(?:\n|$)',
            r'(?:^|\n)(第[一二三四五六七八九十百千\d]+章[^\n]*)(?:\n|$)',
            r'(?:^|\n)(Chapter\s+\d+[^\n]*)(?:\n|$)',
            r'(?:^|\n)(\d+[.．][^\n]+)(?:\n|$)',  # 1. 章节名
        ]

        chapters = []
        current_pos = 0

        # 尝试按模式分割
        for pattern in patterns:
            matches = list(re.finditer(pattern, text, re.MULTILINE))
            if matches:
                for i, match in enumerate(matches):
                    start = match.start()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

                    chapter_title = match.group(2 or match.group(1)).strip()
                    chapter_content = text[start:end].strip()

                    if chapter_content:
                        chapters.append({
                            "title": chapter_title,
                            "content": chapter_content
                        })

                if chapters:
                    break

        # 如果没找到章节标记，整个作为单章
        if not chapters:
            chapters.append({
                "title": "全文",
                "content": text
            })

        return chapters

    @staticmethod
    def extract_dialogues(text: str) -> List[Dict[str, str]]:
        """
        提取对话和旁白
        """
        dialogues = []

        # 按句子分割
        sentences = re.split(r'[。！？\n]+', text)

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 3:
                continue

            # 检测引号对话
            quote_pattern = r'([「""])([^「」""]+)([」""])'
            matches = re.findall(quote_pattern, sent)

            if matches:
                for open_q, content, close_q in matches:
                    if content.strip():
                        # 尝试找说话者
                        before_quote = sent.split(open_q)[0].strip()
                        speaker = NovelParser._extract_speaker(before_quote)

                        dialogues.append({
                            "speaker": speaker,
                            "content": content.strip(),
                            "emotion": "neutral",
                            "is_narration": False
                        })
            else:
                # 旁白
                if len(sent) > 10:
                    dialogues.append({
                        "speaker": "旁白",
                        "content": sent,
                        "emotion": "neutral",
                        "is_narration": True
                    })

        return dialogues

    @staticmethod
    def _extract_speaker(text: str) -> str:
        """从文本中提取说话者"""
        patterns = [
            r'([A-Za-z\u4e00-\u9fa5]{2,4})(?:说|道|问|答|笑|怒|叹|喊|叫|想|对)',
            r'([A-Za-z\u4e00-\u9fa5]{2,4})(?:[：:])',
            r'[-–—]([A-Za-z\u4e00-\u9fa5]{2,4})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return "未知"

    @staticmethod
    def extract_characters(text: str) -> List[Dict[str, str]]:
        """提取角色列表"""
        # 找所有可能是角色的名字
        pattern = r'([A-Za-z\u4e00-\u9fa5]{2,4})(?:说|道|问|答|笑|怒)'
        names = re.findall(pattern, text)

        # 统计出现次数
        from collections import Counter
        name_counts = Counter(names)

        characters = []
        for name, count in name_counts.most_common(10):
            if count >= 2:
                characters.append({
                    "name": name,
                    "description": f"出现{count}次",
                    "personality": "",
                    "speaking_style": ""
                })

        return characters


def parse_novel_file(filepath: str) -> Dict[str, Any]:
    """解析小说文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    chapters = NovelParser.split_chapters(text)

    result = {
        "title": filepath.split('/')[-1].split('.')[0],
        "chapters": []
    }

    for i, chapter in enumerate(chapters):
        parser = NovelParser()
        dialogues = parser.extract_dialogues(text)

        result["chapters"].append({
            "chapter_id": i,
            "title": chapter["title"],
            "content": chapter["content"],
            "dialogues": dialogues,
            "characters": parser.extract_characters(chapter["content"])
        })

    return result
