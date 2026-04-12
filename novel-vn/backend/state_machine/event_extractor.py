"""
P5 - 事件提取器
从小说原文中提取事件定义
"""

import json
import uuid
from typing import List, Dict, Any, Optional


PROMPT_EVENT_EXTRACTION = """你是一个专业的剧情分析师。请从以下小说片段中提取剧情事件。

## 事件定义
事件是能够改变游戏状态的关键剧情节点，例如：
- 获得物品（设置标记）
- 角色关系变化（更新角色状态）
- 场景切换（更新位置）
- 重要决定（影响后续剧情）

## 输出格式
请以JSON格式输出事件列表：
```json
{{
  "events": [
    {{
      "name": "事件名称",
      "description": "事件描述",
      "trigger_conditions": {{
        "required_flags": ["需要的前置标记"],
        "forbidden_flags": ["不能有的标记"],
        "player_location": "触发地点（可选）"
      }},
      "effects": {{
        "set_flags": ["设置的标记"],
        "clear_flags": ["清除的标记"],
        "character_updates": {{
          "角色名": {{
            "location": "新位置",
            "mood": "新情绪",
            "relationship_with_player": 10
          }}
        }},
        "global_updates": {{
          "current_time": "时间",
          "main_quest_stage": "任务阶段"
        }}
      }}
    }}
  ]
}}
```

## 小说片段
{content}

## 角色信息
{characters}

请分析并提取事件，只输出JSON，不要其他文字。
"""


class EventExtractor:
    """事件提取器"""

    def __init__(self, deepseek_client):
        self.deepseek = deepseek_client

    async def extract_events(
        self,
        content: str,
        characters: List[Dict[str, Any]],
        novel_id: str,
        mode: str = "auto"
    ) -> List[Dict[str, Any]]:
        """
        从内容中提取事件

        Args:
            content: 小说片段内容
            characters: 角色列表
            novel_id: 小说ID
            mode: 提取模式 (auto/manual/hybrid)

        Returns:
            事件列表
        """
        if mode == "manual":
            # 手动模式：不自动提取，需要用户标注
            return []

        # 构建角色信息
        char_info = "\n".join([
            f"- {c['name']}: {c.get('personality', '未知性格')}"
            for c in characters
        ])

        # 调用 AI 提取事件
        prompt = PROMPT_EVENT_EXTRACTION.format(
            content=content[:6000],  # 限制长度
            characters=char_info
        )

        try:
            response = await self.deepseek._call_api(
                system_prompt="你是一个专业的剧情分析师，负责从小说中提取游戏事件。",
                user_prompt=prompt,
                max_tokens=4000,
                temperature=0.3
            )

            # 解析响应
            events = self._parse_response(response)

            # 添加 ID 和 novel_id
            for event in events:
                event["id"] = f"event_{uuid.uuid4().hex[:8]}"
                event["novel_id"] = novel_id
                event["event_id"] = event["id"]

            return events

        except Exception as e:
            print(f"Event extraction error: {e}")
            return []

    def _parse_response(self, response: str) -> List[Dict[str, Any]]:
        """解析 AI 响应"""
        try:
            # 尝试提取 JSON
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            json_str = json_str.strip()

            # 如果不是以 { 开头，尝试找到 JSON 对象
            if not json_str.startswith("{"):
                if "{" in json_str:
                    json_str = json_str[json_str.find("{"):]

            data = json.loads(json_str)
            return data.get("events", [])
        except json.JSONDecodeError as e:
            print(f"Event JSON decode error: {e}")
            print(f"Response preview: {response[:500]}")
            # 尝试修复常见问题
            try:
                # 移除可能的注释
                cleaned = response.replace("//", "").strip()
                # 尝试找到 JSON 对象
                if "{" in cleaned and "}" in cleaned:
                    start = cleaned.find("{")
                    end = cleaned.rfind("}") + 1
                    json_str = cleaned[start:end]
                    data = json.loads(json_str)
                    return data.get("events", [])
                else:
                    # 尝试直接包装成对象
                    # 处理类似 '\n  "events": [...]' 的情况
                    if '"events"' in cleaned:
                        wrapped = "{" + cleaned + "}"
                        try:
                            data = json.loads(wrapped)
                            return data.get("events", [])
                        except:
                            pass
            except Exception as e2:
                print(f"Event parse fallback also failed: {e2}")
            return []

    async def extract_events_from_segments(
        self,
        segments: List[Dict[str, Any]],
        characters: List[Dict[str, Any]],
        novel_id: str,
        mode: str = "auto"
    ) -> List[Dict[str, Any]]:
        """
        从多个片段中提取事件（并发控制，最多5个并发）

        Args:
            segments: 片段列表
            characters: 角色列表
            novel_id: 小说ID
            mode: 提取模式

        Returns:
            合并后的事件列表
        """
        if mode == "manual":
            return []

        import asyncio

        # 使用信号量限制并发数为 5
        semaphore = asyncio.Semaphore(5)

        async def extract_with_limit(seg):
            async with semaphore:
                return await self.extract_events(
                    content=seg["content"],
                    characters=characters,
                    novel_id=novel_id,
                    mode=mode
                )

        # 并行执行所有片段的事件提取
        tasks = [extract_with_limit(seg) for seg in segments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并所有事件，过滤掉异常
        all_events = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"片段 {i} 事件提取失败: {r}")
            else:
                all_events.extend(r)

        # 去重和合并相似事件
        return self._merge_events(all_events)

    def _merge_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """合并相似事件"""
        # 简单实现：按名称去重
        seen_names = set()
        merged = []
        for event in events:
            name = event.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                merged.append(event)
        return merged
