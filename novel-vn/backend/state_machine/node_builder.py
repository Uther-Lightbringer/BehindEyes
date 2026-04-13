"""
P6 - 节点构建器
从小说原文构建剧情节点网络
支持：树结构生成（预览）+ 场景内容生成（确认后）
"""

import json
import uuid
from typing import List, Dict, Any, Optional


# ==================== Prompt 模板 ====================

PROMPT_TREE_BUILDING = """你是一个专业的游戏剧情设计师。请将以下小说片段转换为剧情节点树结构。

## 任务说明
生成一个节点树，每个节点代表一个场景/剧情点。此时只需要生成树的结构和预览信息，不需要生成完整的场景内容。

## 节点定义
每个节点包含：
- node_id: 节点标识（如 "node_1", "node_2_alt"）
- route: 所属路线 (main/branch_xxx)
- scene_preview: 场景的简短预览描述（50字以内）
- characters_involved: 涉及的角色名称列表
- choices: 在此节点的可选分支

## 分支设计原则
1. 主线选项：跟随原文剧情走向
2. 分支选项：创造不同的剧情走向（最多2个额外分支）
3. 每个选项要有明显的差异化效果
4. 分支要有实际意义，避免"假选择"

## 输出格式
```json
{{
  "nodes": [
    {{
      "node_id": "node_1",
      "route": "main",
      "scene_preview": "张三在城门口遇到了守卫...",
      "characters_involved": ["张三", "守卫"],
      "choices": [
        {{
          "choice_id": "choice_1",
          "prompt": "你打算怎么做？",
          "options": [
            {{
              "text": "出示通行证",
              "next_node": "node_2",
              "route": "main",
              "effects": {{"set_flags": ["通过检查"], "relationship_updates": {{"守卫": 5}}}}
            }},
            {{
              "text": "尝试绕道",
              "next_node": "node_2_alt",
              "route": "branch_sneak",
              "effects": {{"set_flags": ["潜行"]}}
            }}
          ]
        }}
      ]
    }}
  ]
}}
```
{context_section}
## 小说片段
{content}

## 玩家角色
{player_character}

## 已有角色列表
{characters}

请设计节点树，只输出JSON，不要其他文字。
"""

PROMPT_SCENE_GENERATION = """你是一个视觉小说编剧。请为以下剧情节点生成完整的场景内容。

## 节点信息
- 节点ID: {node_id}
- 路线: {route}
- 场景预览: {scene_preview}

## 角色信息
玩家角色: {player_character}
涉及角色: {characters_involved}

## 前文上下文
{context}

## 输出格式
生成标准的视觉小说场景格式：
```json
{{
  "scene_id": "{node_id}",
  "title": "场景标题",
  "location": "具体地点",
  "description": "场景的环境描述（包含视觉元素）",
  "characters": ["出现的角色名"],
  "dialogues": [
    {{
      "speaker": "角色名/旁白",
      "content": "对话内容",
      "emotion": "normal/happy/angry/sad/surprised",
      "is_narration": false
    }}
  ]
}}
```

请生成场景内容，只输出JSON。
"""


class NodeBuilder:
    """节点构建器 - 支持树结构生成和内容生成分离"""

    def __init__(self, deepseek_client):
        self.deepseek = deepseek_client

    # ==================== 树结构生成 ====================

    async def build_tree_from_content(
        self,
        content: str,
        novel_id: str,
        player_character: Dict[str, Any],
        all_characters: List[Dict[str, Any]],
        parent_node_id: str = None,
        context: str = ""
    ) -> List[Dict[str, Any]]:
        """
        从内容生成节点树结构（不含完整场景内容）

        Args:
            content: 小说片段内容
            novel_id: 小说ID
            player_character: 玩家角色信息
            all_characters: 所有角色列表
            parent_node_id: 父节点ID（用于连接）
            context: 前文上下文（累积的故事摘要、关键事件、角色状态）

        Returns:
            节点列表（只有树结构和预览，无完整场景）
        """
        char_names = [c.get("name", "") for c in all_characters]

        # 构建上下文部分
        if context:
            context_section = f"""
## 前文上下文
{context}

**注意：请确保新生成的节点与前文保持连贯性，角色的行为和对话要符合之前的设定。**
"""
        else:
            context_section = ""

        prompt = PROMPT_TREE_BUILDING.format(
            content=content[:6000],
            player_character=f"{player_character['name']}: {player_character.get('personality', '未知')}",
            characters=", ".join(char_names[:10]),  # 限制角色数量
            context_section=context_section
        )

        try:
            print(f"[NodeBuilder] Calling API for content length: {len(content)}")
            response = await self.deepseek._call_api(
                system_prompt="你是一个专业的游戏剧情设计师，负责将小说转换为可玩的节点树结构。",
                user_prompt=prompt,
                max_tokens=6000,
                temperature=0.6
            )

            print(f"[NodeBuilder] API response length: {len(response)}, preview: {response[:100]}")

            nodes = self._parse_tree_response(response)
            print(f"[NodeBuilder] Parsed nodes count: {len(nodes)}")

            # 添加必要字段
            for i, node in enumerate(nodes):
                pk = f"node_{uuid.uuid4().hex[:8]}"
                node["id"] = pk
                node["novel_id"] = novel_id
                node["parent_node"] = parent_node_id if i == 0 else None
                node["scene_data"] = None  # 待后续生成
                node["possible_events"] = []
                node["needs_generation"] = True  # 标记需要生成内容
                node["generation_hint"] = node.get("scene_preview", "")

            # 连接父节点
            if parent_node_id and nodes:
                nodes[0]["parent_node"] = parent_node_id

            return nodes

        except Exception as e:
            print(f"Tree building error: {e}")
            return []

    async def build_tree_from_segments(
        self,
        segments: List[Dict[str, Any]],
        novel_id: str,
        player_character: Dict[str, Any],
        all_characters: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        从多个片段构建完整的节点树（串行处理 + 累积上下文传递）

        Args:
            segments: 片段列表
            novel_id: 小说ID
            player_character: 玩家角色
            all_characters: 所有角色

        Returns:
            完整的节点树
        """
        if not segments:
            return []

        all_nodes = []
        cumulative_context = {
            "story_summary": "",      # 故事整体摘要
            "key_events": [],         # 关键事件列表
            "character_states": {},   # 角色状态追踪
        }
        last_node_id = None

        for idx, segment in enumerate(segments):
            print(f"[NodeBuilder] Processing segment {idx + 1}/{len(segments)}")

            # 构建传递给 AI 的上下文字符串
            context_str = self._build_context_string(cumulative_context, idx)

            # 生成节点（传入累积上下文）
            nodes = await self.build_tree_from_content(
                content=segment["content"],
                novel_id=novel_id,
                player_character=player_character,
                all_characters=all_characters,
                parent_node_id=last_node_id,
                context=context_str
            )

            if not nodes:
                print(f"[NodeBuilder] Segment {idx} generated no nodes, skipping")
                continue

            # 连接到前一个片段
            if last_node_id and nodes:
                nodes[0]["parent_node"] = last_node_id

                # 设置自动跳转：前一个片段的最后一个节点直接连接到当前片段的第一个节点
                prev_node = self._find_node_by_id(all_nodes, last_node_id)
                if prev_node:
                    # 如果没有选择分支，设置自动跳转
                    if not prev_node.get("choices"):
                        prev_node["auto_next"] = nodes[0]["node_id"]

            all_nodes.extend(nodes)
            last_node_id = nodes[-1]["node_id"]

            # 更新累积上下文（而不是只保存前一个摘要）
            cumulative_context = self._update_cumulative_context(cumulative_context, nodes)

        return all_nodes

    def _build_context_string(self, context: Dict[str, Any], current_segment_index: int) -> str:
        """构建传递给 AI 的上下文字符串"""
        parts = []

        # 故事摘要
        if context.get("story_summary"):
            parts.append(f"【前文摘要】\n{context['story_summary']}")

        # 关键事件（最多保留最近10个）
        events = context.get("key_events", [])
        if events:
            recent_events = events[-10:]
            events_str = "\n".join([f"- {e}" for e in recent_events])
            parts.append(f"【已发生的关键事件】\n{events_str}")

        # 角色状态变化
        char_states = context.get("character_states", {})
        if char_states:
            states_list = []
            for char_name, state in char_states.items():
                if state:
                    states_list.append(f"- {char_name}: {state}")
            if states_list:
                parts.append(f"【角色当前状态】\n" + "\n".join(states_list))

        if not parts:
            return ""

        result = "\n\n".join(parts)
        # 限制总长度，避免爆 token
        if len(result) > 1500:
            result = result[:1500] + "..."
        return result

    def _update_cumulative_context(
        self,
        context: Dict[str, Any],
        new_nodes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """更新累积上下文"""
        # 1. 更新故事摘要
        segment_summary = self._generate_segment_summary(new_nodes)
        if context.get("story_summary"):
            # 合并摘要，保留最近的内容
            combined = context["story_summary"]
            if len(combined) < 500:
                combined = combined + " → " + segment_summary
            else:
                # 如果已经很长，截断旧内容，保留最近部分
                combined = "... → " + combined[-300:] + " → " + segment_summary
            context["story_summary"] = combined
        else:
            context["story_summary"] = segment_summary

        # 2. 提取关键事件（从 choices 的 effects 中提取）
        for node in new_nodes:
            choices = node.get("choices", [])
            for choice in choices:
                for option in choice.get("options", []):
                    effects = option.get("effects", {})
                    # 提取设置标记
                    set_flags = effects.get("set_flags", [])
                    for flag in set_flags:
                        if flag and flag not in context["key_events"]:
                            context["key_events"].append(flag)

        # 3. 更新角色状态（从 effects 中提取关系变化）
        for node in new_nodes:
            choices = node.get("choices", [])
            for choice in choices:
                for option in choice.get("options", []):
                    effects = option.get("effects", {})
                    rel_updates = effects.get("relationship_updates", {})
                    for char_name, change in rel_updates.items():
                        if char_name not in context["character_states"]:
                            context["character_states"][char_name] = ""
                        # 记录关系变化
                        old_state = context["character_states"][char_name]
                        if change > 0:
                            new_state = f"好感度+{change}"
                        elif change < 0:
                            new_state = f"好感度{change}"
                        else:
                            continue
                        if old_state:
                            context["character_states"][char_name] = old_state + ", " + new_state
                        else:
                            context["character_states"][char_name] = new_state

        # 限制角色状态数量，只保留最近变化的角色
        if len(context["character_states"]) > 10:
            # 保留最近的10个角色
            keys = list(context["character_states"].keys())[-10:]
            context["character_states"] = {k: context["character_states"][k] for k in keys}

        return context

    def _generate_segment_summary(self, nodes: List[Dict[str, Any]]) -> str:
        """根据节点列表生成片段摘要"""
        if not nodes:
            return ""

        summaries = []
        for node in nodes:
            preview = node.get("scene_preview", "") or node.get("generation_hint", "")
            if preview:
                summaries.append(preview)

        if summaries:
            return " → ".join(summaries[:5])  # 最多取5个节点的预览
        return ""

    # ==================== 场景内容生成 ====================

    async def generate_node_scene(
        self,
        node: Dict[str, Any],
        player_character: Dict[str, Any],
        context: Dict[str, Any] = None,
        characters_map: Dict[str, Dict] = None
    ) -> Dict[str, Any]:
        """
        为单个节点生成完整的场景内容

        Args:
            node: 节点信息
            player_character: 玩家角色
            context: 前文上下文
            characters_map: 角色名到角色信息的映射

        Returns:
            完整的场景数据
        """
        context_str = json.dumps(context, ensure_ascii=False, indent=2) if context else "无"

        characters_involved = node.get("characters_involved", [])
        char_info = self._format_characters_info(characters_involved, characters_map)

        prompt = PROMPT_SCENE_GENERATION.format(
            node_id=node.get("node_id", "unknown"),
            route=node.get("route", "main"),
            scene_preview=node.get("scene_preview", ""),
            player_character=f"{player_character['name']}: {player_character.get('personality', '未知')}",
            characters_involved=", ".join(characters_involved) if characters_involved else "未知",
            context=context_str
        )

        try:
            response = await self.deepseek._call_api(
                system_prompt="你是一个专业的视觉小说编剧，负责生成场景内容。",
                user_prompt=prompt,
                max_tokens=4000,
                temperature=0.7
            )

            scene = self._parse_scene_response(response)

            # 标记玩家角色
            if scene.get("dialogues"):
                for d in scene["dialogues"]:
                    if d.get("speaker") == player_character.get("name"):
                        d["is_player"] = True

            return scene

        except Exception as e:
            print(f"Scene generation error for node {node.get('node_id')}: {e}")
            return self._create_fallback_scene(node, player_character)

    async def generate_all_node_scenes(
        self,
        nodes: List[Dict[str, Any]],
        player_character: Dict[str, Any],
        characters_map: Dict[str, Dict] = None,
        progress_callback=None
    ) -> List[Dict[str, Any]]:
        """
        为所有需要生成内容的节点生成场景

        Args:
            nodes: 节点列表
            player_character: 玩家角色
            characters_map: 角色映射
            progress_callback: 进度回调函数

        Returns:
            更新后的节点列表
        """
        nodes_to_generate = [n for n in nodes if n.get("needs_generation") or not n.get("scene_data")]
        total = len(nodes_to_generate)

        context = {}

        for i, node in enumerate(nodes):
            if node.get("needs_generation") or not node.get("scene_data"):
                # 生成场景内容
                scene = await self.generate_node_scene(
                    node=node,
                    player_character=player_character,
                    context=context,
                    characters_map=characters_map
                )

                node["scene_data"] = scene
                node["needs_generation"] = False

                # 更新上下文（用于下一个节点）
                context = {
                    "last_location": scene.get("location", ""),
                    "last_characters": scene.get("characters", []),
                    "summary": scene.get("description", "")[:200]
                }

                # 进度回调
                if progress_callback:
                    progress_callback(i + 1, total, node.get("node_id"))

        return nodes

    # ==================== 辅助方法 ====================

    def _parse_tree_response(self, response: str) -> List[Dict[str, Any]]:
        """解析树结构响应"""
        last_error = None

        try:
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
            nodes = data.get("nodes", [])
            if nodes:
                return nodes
            last_error = "JSON 中没有 nodes 字段或 nodes 为空"
        except json.JSONDecodeError as e:
            print(f"Tree JSON decode error: {e}")
            print(f"Response preview: {response[:500]}")
            last_error = str(e)

        # 尝试 fallback 解析
        try:
            cleaned = response.replace("//", "").strip()
            # 尝试找到 JSON 对象
            if "{" in cleaned and "}" in cleaned:
                start = cleaned.find("{")
                end = cleaned.rfind("}") + 1
                json_str = cleaned[start:end]
                data = json.loads(json_str)
                nodes = data.get("nodes", [])
                if nodes:
                    return nodes
            # 尝试直接包装成对象
            if '"nodes"' in cleaned:
                wrapped = "{" + cleaned + "}"
                try:
                    data = json.loads(wrapped)
                    nodes = data.get("nodes", [])
                    if nodes:
                        return nodes
                except:
                    pass
        except Exception as e2:
            print(f"Tree parse fallback also failed: {e2}")
            last_error = str(e2)

        # 解析失败，抛出异常
        raise ValueError(f"无法解析 AI 响应为节点树: {last_error or '未知错误'}。响应前100字符: {response[:100]}")

    def _parse_scene_response(self, response: str) -> Dict[str, Any]:
        """解析场景响应"""
        try:
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

            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"Scene JSON decode error: {e}")
            print(f"Response preview: {response[:500]}")
            try:
                cleaned = response.replace("//", "").strip()
                if "{" in cleaned and "}" in cleaned:
                    start = cleaned.find("{")
                    end = cleaned.rfind("}") + 1
                    json_str = cleaned[start:end]
                    return json.loads(json_str)
            except Exception as e2:
                print(f"Scene parse fallback also failed: {e2}")
            return {
                "title": "场景",
                "location": "未知地点",
                "description": response[:300] if len(response) > 300 else response,
                "dialogues": [{"speaker": "旁白", "content": response[:500], "is_narration": True}]
            }

    def _find_node_by_id(self, nodes: List[Dict], node_id: str) -> Optional[Dict]:
        """通过 node_id 查找节点"""
        for node in nodes:
            if node.get("node_id") == node_id:
                return node
        return None

    def _format_characters_info(self, char_names: List[str], characters_map: Dict[str, Dict]) -> str:
        """格式化角色信息"""
        if not characters_map or not char_names:
            return ", ".join(char_names) if char_names else "未知"

        info = []
        for name in char_names:
            char = characters_map.get(name, {})
            if char:
                info.append(f"{name}: {char.get('personality', '未知性格')}")
            else:
                info.append(name)
        return "; ".join(info)

    def _create_fallback_scene(self, node: Dict, player_character: Dict) -> Dict[str, Any]:
        """创建备用场景"""
        return {
            "scene_id": node.get("node_id", "unknown"),
            "title": node.get("scene_preview", "场景")[:30],
            "location": "未知地点",
            "description": node.get("scene_preview", ""),
            "characters": node.get("characters_involved", []),
            "dialogues": [
                {
                    "speaker": "旁白",
                    "content": node.get("scene_preview", "场景描述"),
                    "is_narration": True
                }
            ]
        }

    # ==================== 兼容 v0.1 数据 ====================

    def build_nodes_from_scenes(
        self,
        scenes: List[Dict[str, Any]],
        choices: List[Dict[str, Any]],
        novel_id: str
    ) -> List[Dict[str, Any]]:
        """
        从已生成的场景构建节点（兼容 v0.1 数据）

        用于迁移旧数据
        """
        nodes = []

        for i, scene in enumerate(scenes):
            node_id = f"scene_{i}"
            pk = f"node_{uuid.uuid4().hex[:8]}"

            # 找到这个场景的选择
            scene_choices = []
            for choice in choices:
                if choice.get("at_scene") == i:
                    options = choice.get("options", [])
                    scene_choices.append({
                        "choice_id": f"choice_{i}_{uuid.uuid4().hex[:6]}",
                        "prompt": choice.get("prompt", "请选择"),
                        "options": [{
                            "text": opt.get("text", ""),
                            "next_node": f"scene_{opt.get('next_scene', i+1)}",
                            "route": opt.get("route", "main"),
                            "effects": opt.get("effect", {})
                        } for opt in options]
                    })

            node = {
                "id": pk,
                "novel_id": novel_id,
                "node_id": node_id,
                "route": "main",
                "scene_preview": scene.get("description", "")[:50] if scene.get("description") else scene.get("title", ""),
                "scene_data": scene,
                "characters_involved": scene.get("characters", []),
                "possible_events": [],
                "choices": scene_choices,
                "prerequisites": {},
                "needs_generation": False,
                "generation_hint": ""
            }

            nodes.append(node)

        # 确保节点连接
        for i in range(len(nodes) - 1):
            if not nodes[i].get("choices"):
                nodes[i]["choices"] = [{
                    "choice_id": f"auto_choice_{i}",
                    "prompt": "继续",
                    "options": [{
                        "text": "继续",
                        "next_node": nodes[i + 1]["node_id"],
                        "route": "main",
                        "effects": {}
                    }]
                }]

        return nodes
