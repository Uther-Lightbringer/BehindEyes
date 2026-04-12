"""
P6 - 节点构建器
从小说原文构建剧情节点网络
"""

import json
import uuid
from typing import List, Dict, Any, Optional


PROMPT_NODE_BUILDING = """你是一个专业的游戏剧情设计师。请将以下小说片段转换为剧情节点网络。

## 节点定义
每个节点代表一个独立的场景/剧情点，包含：
- node_id: 节点标识
- route: 所属路线 (main/break_xxx)
- scene_preview: 场景预览描述
- choices: 在此节点的可选分支

## 分支设计
请根据原文内容设计合理的分支选项：
1. 主线选项：跟随原文剧情
2. 分支选项：创造不同的剧情走向

每个选项应该：
- 有明确的文本描述
- 指向下一个节点
- 可能影响状态（通过effects）
- 标记所属路线

## 输出格式
```json
{
  "nodes": [
    {
      "node_id": "node_1",
      "route": "main",
      "scene_preview": "场景描述...",
      "needs_generation": false,
      "choices": [
        {
          "prompt": "你打算怎么做？",
          "options": [
            {
              "text": "按照原文继续",
              "next_node": "node_2",
              "route": "main",
              "effects": {}
            },
            {
              "text": "尝试不同的选择",
              "next_node": "node_2_alt",
              "route": "branch_alt",
              "effects": {"set_flags": ["选择了不同路径"]}
            }
          ]
        }
      ]
    }
  ]
}
```

## 小说片段
{content}

## 玩家角色
{player_character}

请设计节点网络，只输出JSON，不要其他文字。
"""


class NodeBuilder:
    """节点构建器"""

    def __init__(self, deepseek_client):
        self.deepseek = deepseek_client

    async def build_nodes_from_content(
        self,
        content: str,
        novel_id: str,
        player_character: Dict[str, Any],
        existing_nodes: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        从内容构建节点

        Args:
            content: 小说片段内容
            novel_id: 小说ID
            player_character: 玩家角色信息
            existing_nodes: 已有节点（用于连接）

        Returns:
            节点列表
        """
        prompt = PROMPT_NODE_BUILDING.format(
            content=content[:6000],
            player_character=f"{player_character['name']}: {player_character.get('personality', '未知')}"
        )

        try:
            response = await self.deepseek._call_api(
                system_prompt="你是一个专业的游戏剧情设计师，负责将小说转换为可玩的节点网络。",
                user_prompt=prompt,
                max_tokens=6000,
                temperature=0.5
            )

            nodes = self._parse_response(response)

            # 添加 ID 和 novel_id
            for i, node in enumerate(nodes):
                pk = f"node_{uuid.uuid4().hex[:8]}"
                node["id"] = pk
                node["novel_id"] = novel_id
                # 确保节点ID唯一
                if not node.get("node_id"):
                    node["node_id"] = f"scene_{i}"

            return nodes

        except Exception as e:
            print(f"Node building error: {e}")
            return []

    def _parse_response(self, response: str) -> List[Dict[str, Any]]:
        """解析 AI 响应"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())
            return data.get("nodes", [])
        except json.JSONDecodeError:
            try:
                cleaned = response.replace("//", "")
                data = json.loads(cleaned)
                return data.get("nodes", [])
            except:
                return []

    async def build_nodes_from_segments(
        self,
        segments: List[Dict[str, Any]],
        novel_id: str,
        player_character: Dict[str, Any],
        mode: str = "pregenerate"
    ) -> List[Dict[str, Any]]:
        """
        从多个片段构建节点网络

        Args:
            segments: 片段列表
            novel_id: 小说ID
            player_character: 玩家角色
            mode: 生成模式 (pregenerate/realtime)

        Returns:
            节点列表
        """
        all_nodes = []
        last_node_id = None

        for i, segment in enumerate(segments):
            # 构建节点
            nodes = await self.build_nodes_from_content(
                content=segment["content"],
                novel_id=novel_id,
                player_character=player_character,
                existing_nodes=all_nodes
            )

            # 连接到前一个节点
            if last_node_id and nodes:
                # 找到前一个节点，添加连接
                for node in all_nodes:
                    if node["node_id"] == last_node_id:
                        # 如果没有选择，添加一个默认选择
                        if not node.get("choices"):
                            node["choices"] = []
                        # 确保能连接到新节点
                        if nodes:
                            node["choices"].append({
                                "prompt": "继续",
                                "options": [{
                                    "text": "继续",
                                    "next_node": nodes[0]["node_id"],
                                    "route": "main"
                                }]
                            })
                        break

            if nodes:
                all_nodes.extend(nodes)
                last_node_id = nodes[-1]["node_id"]

        return all_nodes

    def build_nodes_from_scenes(
        self,
        scenes: List[Dict[str, Any]],
        choices: List[Dict[str, Any]],
        novel_id: str
    ) -> List[Dict[str, Any]]:
        """
        从已生成的场景构建节点（兼容 v0.1 数据）

        Args:
            scenes: 场景列表
            choices: 选择列表
            novel_id: 小说ID

        Returns:
            节点列表
        """
        nodes = []

        for i, scene in enumerate(scenes):
            node_id = f"scene_{i}"
            pk = f"node_{uuid.uuid4().hex[:8]}"

            # 找到这个场景的选择
            scene_choices = []
            for choice in choices:
                if choice.get("at_scene") == i:
                    scene_choices.append({
                        "prompt": choice.get("prompt", "请选择"),
                        "options": choice.get("options", [])
                    })

            node = {
                "id": pk,
                "novel_id": novel_id,
                "node_id": node_id,
                "route": "main",
                "scene_data": scene,
                "possible_events": [],
                "choices": scene_choices,
                "prerequisites": {},
                "needs_generation": False,
                "generation_hint": ""
            }

            nodes.append(node)

        # 连接节点
        for i in range(len(nodes) - 1):
            if not nodes[i]["choices"]:
                # 添加默认连接
                nodes[i]["choices"] = [{
                    "prompt": "继续",
                    "options": [{
                        "text": "继续",
                        "next_node": nodes[i + 1]["node_id"],
                        "route": "main"
                    }]
                }]

        return nodes

    async def generate_branch_content(
        self,
        node: Dict[str, Any],
        context: Dict[str, Any],
        player_character: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成分支节点内容

        Args:
            node: 需要生成内容的节点
            context: 上下文信息（前文摘要等）
            player_character: 玩家角色

        Returns:
            生成的场景数据
        """
        prompt = f"""请为以下剧情节点生成具体的场景内容。

## 前文上下文
{json.dumps(context, ensure_ascii=False, indent=2)}

## 节点信息
- 路线: {node.get('route', 'main')}
- 预览: {node.get('scene_preview', '无')}

## 玩家角色
{player_character['name']}: {player_character.get('personality', '未知')}

请生成场景内容，包含：
- 场景描述
- 角色对话
- 可能的互动

输出JSON格式的场景数据。
"""

        try:
            response = await self.deepseek._call_api(
                system_prompt="你是一个视觉小说编剧，负责生成分支剧情内容。",
                user_prompt=prompt,
                max_tokens=4000,
                temperature=0.7
            )

            # 解析场景数据
            scene = self._parse_scene_response(response)
            return scene

        except Exception as e:
            print(f"Branch content generation error: {e}")
            return {}

    def _parse_scene_response(self, response: str) -> Dict[str, Any]:
        """解析场景响应"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            return json.loads(json_str.strip())
        except:
            # 返回基础场景结构
            return {
                "title": "分支场景",
                "description": response[:500] if len(response) > 500 else response,
                "dialogues": []
            }
