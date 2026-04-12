"""
DeepSeek API 客户端 - 角色视角版本
支持: 雪花ID生成、两阶段解析(角色卡→场景)、AI审阅、角色视角生成
"""

import os
import json
import time
import threading
from openai import OpenAI
from typing import Dict, Any, List, Optional


# ============================================================
# Prompt 模板常量 - 集中管理所有 AI 调用 prompt
# ============================================================
PROMPT_CHARACTER_CARD_SYSTEM = "你是一个小说角色分析助手，输出规范JSON数组。"
PROMPT_CHARACTER_CARD_USER_TEMPLATE = """分析以下小说章节，提取所有角色的详细信息。

要求输出JSON数组，每个角色包含:
- id: 雪花ID（使用 generate_id() 函数生成，确保全局唯一）
- name: 角色姓名
- gender: 性别（男/女/未知）
- age_range: 年龄段（儿童/少年/青年/中年/老年）
- appearance: 外貌描写（从原文提取，约20-50字，包含：体型、发型发色、眼睛、面容特征等。如原文无描写，根据角色特点合理推测）
- clothing: 典型服装/装束（从原文提取或根据角色身份推测）
- distinctive_features: 显著特征（疤痕、胎记、配饰等特殊标记）
- aliases: 别名/昵称列表（数组）
- personality: 性格特征描述（20字内）
- speaking_style: 说话风格描述（20字内）
- is_playable: 是否可扮演（重要角色为true，配角/NPC为false）
- relations: 与其他角色的关系 {{"角色名": "关系描述"}} 的字典

请确保:
1. 主角和重要配角 is_playable 设为 true
2. 只出现1-2次的路人等 is_playable 设为 false
3. speaking_style要能指导后续对话生成
4. appearance 和 clothing 尽量从原文提取真实描写，如无则合理推测

章节内容:
{content}

只输出JSON，不要其他内容。"""

PROMPT_SCENE_SYSTEM = """你是一名资深视觉小说（Visual Novel）编剧助手。你的任务是将小说章节改写为视觉小说剧本格式。

核心要求：
1. 对话为主、旁白为辅。对话应占全部内容的70%以上
2. 每个角色说话时必须标明其名字作为speaker
3. 旁白只用于描写环境、动作、心理活动，绝不包含角色说的话
4. 玩家角色（第一人称）的内心独白也应算作玩家对话，is_player=true
5. 不要直接复制原文，要将原文全部转化为角色间的对话和场景描写
6. 当NPC说话时，speaker设为NPC名字；当玩家说话/想时，is_player=true, is_narration=false

【特别重要 - 禁止全是旁白】
- 如果原文是叙述性文字（没有角色对话），你必须创造性地改写：
  - 让玩家角色进行内心独白（speaker=玩家角色名，is_player=true，is_narration=false）
  - 让旁白以"引路人/讲述者"的身份与玩家对话
  - 将作者的叙述转化为玩家角色的见闻和感想
- 绝对不允许输出连续多条旁白而没有对话！
- 每个场景至少要有2条以上玩家角色的对话/独白"""

PROMPT_SCENE_USER_TEMPLATE = """你是一名视觉小说编剧。现在要将以下小说章节从角色【{char_name}】的**第一人称视角**改编为视觉小说剧本。

【最重要规则 - 违反即为失败】
1. **禁止全是旁白！** 对话必须占70%以上
2. 玩家角色【{char_name}】必须有对话或内心独白，不能只是旁观者
3. 如果原文是纯叙述，你要创造性地将其转化为：
   - {char_name}的所见所闻（以内心独白形式）
   - {char_name}与他人/自己的对话
   - 场景中的互动

【对话处理规则】
1. 你必须将原文中的**每一段对话都提取出来**，以对话形式输出
2. **不能把角色说的话放到旁白里！** 谁说的话，speaker就必须是谁的名字
3. 旁白只能是环境描写、动作描写，不能包含任何对话或长篇叙述
4. 玩家角色【{char_name}】说的每一句话（包括内心独白），is_player必须为true，is_narration必须为false
5. 不要直接复制原文，要**改写**为视觉小说风格

【视角规则】
1. 所有内容都要以【{char_name}】的视角来写
2. 旁白描述的是{char_name}能看到/听到/想到的内容
3. 在关键决策点生成选择分支

角色信息:
- 玩家角色: {char_name}
  - 性格: {personality}
  - 说话风格: {speaking_style}

可扮演角色: {playable_chars}
所有角色: {all_char_names}

输出JSON格式:
{{
  "scenes": [
    {{
      "scene_id": 0,
      "title": "场景标题",
      "location": "地点名称",
      "description": "场景描述（1-2句）",
      "characters": ["出场的角色名列表，按出场顺序"],
      "dialogues": [
        {{
          "speaker": "旁白/{char_name}/{{NPC名}}",
          "content": "对话/旁白内容",
          "emotion": "normal/excited/angry/sad/surprised/calm等",
          "is_narration": true/false,
          "is_player": true/false
        }}
      ]
    }}
  ],
  "choices": [
    {{
      "at_scene": 场景ID,
      "prompt": "选择场景的描述",
      "options": [
        {{
          "text": "选项文字",
          "next_scene": 下一个场景ID,
          "route": "路线标签",
          "effect": {{}}
        }}
      ]
    }}
  ]
}}

章节内容:
{chunk_content}

只输出JSON，不要其他内容。记住：对话占70%以上，禁止全是旁白！"""

PROMPT_REVIEW_SYSTEM = "你是一个对话审阅助手，输出规范JSON。"
PROMPT_REVIEW_USER_TEMPLATE = """你是一个对话审阅助手。请检查以下角色视角场景数据中的问题。

审阅标准:
1. 检查每个dialogue的speaker是否正确
2. 旁白（is_narration=true）应该是描述动作、环境、事件的内容
3. NPC说的话应该speaker是NPC的名字
4. 玩家角色（{player_char_name}）的对话is_player应该为true
5. 检查choices中的next_scene是否有效

角色视角场景数据:
{generated_data_json}

原始小说摘要:
{original_content}

输出JSON格式:
{{
  "has_issues": true/false,
  "issues": [
    {{
      "scene_id": 场景ID,
      "dialogue_index": 对话索引,
      "issue_type": "speaker_error/missing_choice/invalid_next等",
      "description": "问题描述"
    }}
  ],
  "fixed_scenes": [
    {{
      "scene_id": 场景ID,
      "dialogues": 修复后的dialogues数组
    }}
  ]
}}

只输出JSON，不要其他内容。"""

PROMPT_SELF_EVAL_SYSTEM = "你是一个Prompt质量评估助手。"
PROMPT_SELF_EVAL_USER_TEMPLATE = """评估以下AI prompt 的效果：

System Prompt:
{system_prompt}

User Prompt:
{user_prompt}

请用JSON格式评估（1-5分，1条建议）：
{{"score": 1-5, "suggestion": "改进建议"}}"""


# ============================================================
# 雪花ID生成器
# ============================================================
class SnowflakeIDGenerator:
    """Twitter Snowflake 算法实现"""

    def __init__(self, datacenter_id: int = 1, worker_id: int = 1):
        self.twepoch = 1288834974657
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.sequence = 0
        self.lock = threading.Lock()
        self.worker_id_bits = 5
        self.datacenter_id_bits = 5
        self.sequence_bits = 12
        self.worker_id_shift = self.sequence_bits
        self.datacenter_id_shift = self.sequence_bits + self.worker_id_bits
        self.timestamp_left_shift = self.sequence_bits + self.worker_id_bits + self.datacenter_id_bits
        self.sequence_mask = -1 ^ (-1 << self.sequence_bits)
        self.worker_id_mask = -1 ^ (-1 << self.worker_id_bits)
        self.datacenter_id_mask = -1 ^ (-1 << self.datacenter_id_bits)
        self.last_timestamp = -1

    def _current_millis(self) -> int:
        return int(time.time() * 1000)

    def generate(self) -> int:
        with self.lock:
            timestamp = self._current_millis()
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.sequence_mask
                if self.sequence == 0:
                    while timestamp <= self.last_timestamp:
                        timestamp = self._current_millis()
            else:
                self.sequence = 0
            self.last_timestamp = timestamp
            new_id = (
                ((timestamp - self.twepoch) << self.timestamp_left_shift)
                | (self.datacenter_id << self.datacenter_id_shift)
                | (self.worker_id << self.worker_id_shift)
                | self.sequence
            )
            return new_id


snowflake = SnowflakeIDGenerator()


def generate_id() -> str:
    return str(snowflake.generate())


# ============================================================
# DeepSeek 客户端
# ============================================================
class DeepSeekClient:
    def __init__(self, db=None):
        self.db = db
        api_key = os.getenv("AI_DEEPSEEK_API_KEY")
        if not api_key:
            print("警告: AI_DEEPSEEK_API_KEY 环境变量未设置")
            self.client = None
        else:
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )

    def is_configured(self) -> bool:
        return self.client is not None

    # ============================================================
    # 阶段1: 生成角色卡片（一次性生成所有角色）
    # ============================================================
    async def generate_character_cards(self, content: str, user_id: str = None, novel_id: str = None) -> List[Dict[str, Any]]:
        """第一阶段: 使用AI生成详细角色卡片"""
        if not self.client:
            return self._fallback_characters(content)

        system_prompt = PROMPT_CHARACTER_CARD_SYSTEM
        user_prompt = PROMPT_CHARACTER_CARD_USER_TEMPLATE.format(content=content[:5000])

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                    timeout=120.0,
                    response_format={"type": "json_object"}
                )

                result_text = response.choices[0].message.content
                if not result_text or not result_text.strip():
                    print(f"角色卡片生成返回空内容，重试 {attempt + 1}/{max_retries}")
                    continue

                result_text = self._extract_json(result_text)
                data = json.loads(result_text)

                if isinstance(data, list):
                    characters = data
                elif isinstance(data, dict) and "characters" in data:
                    characters = data["characters"]
                else:
                    characters = []

                for char in characters:
                    if "id" not in char or not char["id"]:
                        char["id"] = generate_id()
                    if "is_playable" not in char:
                        char["is_playable"] = True

                self._record_prompt(
                    prompt_type="character_card",
                    sys_prompt=system_prompt,
                    user_prompt=user_prompt,
                    ai_response=result_text,
                    model="deepseek-chat",
                    user_id=user_id,
                    novel_id=novel_id,
                )

                return characters

            except json.JSONDecodeError as e:
                print(f"角色卡片JSON解析失败: {e}，重试 {attempt + 1}/{max_retries}")
                continue
            except Exception as e:
                print(f"角色卡片生成失败: {e}")
                break

        return self._fallback_characters(content)

    def _fallback_characters(self, content: str) -> List[Dict[str, Any]]:
        import re
        name_pattern = r'([A-Za-z\u4e00-\u9fa5]{2,4})(?:说|道|问|答|笑|怒)'
        names = re.findall(name_pattern, content)
        seen = set()
        characters = []
        for name in names:
            if name not in seen and len(characters) < 10:
                seen.add(name)
                characters.append({
                    "id": generate_id(),
                    "name": name,
                    "aliases": [],
                    "personality": "",
                    "speaking_style": "",
                    "is_playable": len(characters) < 3,
                    "relations": {}
                })
        return characters

    def merge_characters(self, char_lists: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        合并多个片段的角色卡:
        1. 按名字匹配
        2. 合并 personality, speaking_style, aliases, relations
        3. 去重并保留统一的ID

        Args:
            char_lists: 多个片段的角色列表

        Returns:
            合并后的角色列表
        """
        merged = {}

        for chars in char_lists:
            for char in chars:
                name = char.get("name", "")
                if not name:
                    continue

                if name in merged:
                    # 合并信息
                    existing = merged[name]

                    # 合并 personality
                    if char.get("personality"):
                        existing_p = existing.get("personality", "")
                        new_p = char["personality"]
                        if new_p and new_p not in existing_p:
                            existing["personality"] = f"{existing_p}；{new_p}".strip("；")

                    # 合并 speaking_style
                    if char.get("speaking_style"):
                        existing_s = existing.get("speaking_style", "")
                        new_s = char["speaking_style"]
                        if new_s and new_s not in existing_s:
                            existing["speaking_style"] = f"{existing_s}；{new_s}".strip("；")

                    # 合并 aliases
                    if char.get("aliases"):
                        existing_aliases = set(existing.get("aliases", []))
                        existing_aliases.update(char.get("aliases", []))
                        existing["aliases"] = list(existing_aliases)

                    # 合并 relations
                    if char.get("relations"):
                        existing_r = existing.get("relations", {})
                        new_r = char.get("relations", {})
                        existing_r.update(new_r)
                        existing["relations"] = existing_r

                    # 保持 is_playable 为 True 如果任意片段为 True
                    if char.get("is_playable"):
                        existing["is_playable"] = True
                else:
                    # 新角色
                    merged[name] = dict(char)
                    # 确保有ID
                    if not merged[name].get("id"):
                        merged[name]["id"] = generate_id()

        return list(merged.values())

    def find_characters_in_segment(self, content: str, characters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        在片段内容中找出出现的角色

        Args:
            content: 片段内容
            characters: 全局角色列表

        Returns:
            本片段出现的角色列表
        """
        found = []
        for char in characters:
            name = char.get("name", "")
            if name and name in content:
                # 检查别名
                aliases = char.get("aliases", [])
                found_in_aliases = any(alias in content for alias in aliases if alias)

                if name in content or found_in_aliases:
                    found.append(char)
        return found

    # ============================================================
    # 分段工具
    # ============================================================
    def _chunk_content(self, content: str, chunk_size: int = 5000, overlap: int = 300) -> List[Dict[str, Any]]:
        """将长文本拆分为片段，段间重叠，优先在段落边界断开

        Returns:
            List[Dict]: 片段列表，每个片段包含:
            - index: 片段序号
            - content: 片段内容
            - start_pos: 在原文中的起始位置
            - end_pos: 在原文中的结束位置
        """
        if len(content) <= chunk_size:
            return [{
                "index": 0,
                "content": content,
                "start_pos": 0,
                "end_pos": len(content)
            }]

        chunks = []
        pos = 0
        segment_index = 0

        while pos < len(content):
            end = pos + chunk_size
            if end >= len(content):
                chunks.append({
                    "index": segment_index,
                    "content": content[pos:],
                    "start_pos": pos,
                    "end_pos": len(content)
                })
                break

            # 优先在段落边界断开
            best_cut = -1
            for boundary in ['\n\n', '\n', '。', '！', '？', '.']:
                search_start = max(pos + chunk_size - overlap - len(boundary), pos)
                search_end = pos + chunk_size
                idx = content.rfind(boundary, search_start, search_end)
                if idx > pos:
                    best_cut = idx + len(boundary)
                    break

            if best_cut <= pos:
                best_cut = end

            chunks.append({
                "index": segment_index,
                "content": content[pos:best_cut],
                "start_pos": pos,
                "end_pos": best_cut
            })

            # 下一段从重叠区域开始
            overlap_start = max(best_cut - overlap, 0)
            next_pos = overlap_start
            for boundary in ['\n\n', '\n']:
                idx = content.find(boundary, overlap_start)
                if idx != -1 and idx < best_cut:
                    next_pos = idx + len(boundary)
                    break
            pos = next_pos if next_pos > overlap_start else overlap_start
            segment_index += 1

        return chunks

    # ============================================================
    # 摘要生成
    # ============================================================
    async def generate_segment_summary(self, content: str, user_id: str = None, novel_id: str = None) -> str:
        """生成片段的故事摘要"""
        if not self.client:
            return ""

        prompt = f"""请用简洁的语言概括以下小说片段的主要内容（100字以内）：

{content[:3000]}

只输出摘要内容，不要其他文字。"""

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200,
                timeout=30.0
            )

            summary = response.choices[0].message.content.strip()

            self._record_prompt(
                prompt_type="segment_summary",
                sys_prompt="",
                user_prompt=prompt,
                ai_response=summary,
                model="deepseek-chat",
                user_id=user_id,
                novel_id=novel_id,
            )

            return summary

        except Exception as e:
            print(f"摘要生成失败: {e}")
            return ""

    def _merge_scenes(self, results: List[Dict[str, Any]], char_name: str) -> Dict[str, Any]:
        """合并多个分段生成的场景结果

        每段 AI 返回的 scenes 都是从 scene_id=0 开始独立编号的。
        合并时全局重新编号，同时偏移 choices 中的 at_scene 和 next_scene。
        """
        all_scenes = []
        all_choices = []
        offset = 0  # 当前段之前的 scene 总数

        for idx, result in enumerate(results):
            scenes = result.get("scenes", [])
            choices = result.get("choices", [])

            # 在交界处添加过渡提示（非第一段的首个场景）
            if idx > 0 and scenes:
                scenes[0].setdefault("description", "")
                if not scenes[0]["description"].startswith("（续接前段）"):
                    scenes[0]["description"] = "（续接前段场景）" + scenes[0]["description"]

            # 重编号 scene_id
            for scene in scenes:
                scene["scene_id"] = scene["scene_id"] + offset

            # 偏移 choices 中的 at_scene 和 next_scene
            for choice in choices:
                c = dict(choice)
                if "at_scene" in c and isinstance(c["at_scene"], int):
                    c["at_scene"] = c["at_scene"] + offset
                for opt in c.get("options", []):
                    ns = opt.get("next_scene")
                    if isinstance(ns, int) and ns >= 0:
                        opt["next_scene"] = ns + offset
                all_choices.append(c)

            # 段间串联：如果不是最后一段，自动添加一个"继续"选项指向下一段的第一个场景
            if idx < len(results) - 1 and scenes:
                next_first = scenes[-1]["scene_id"] + 1  # 下一段的第一个 scene_id
                all_choices.append({
                    "at_scene": scenes[-1]["scene_id"],
                    "prompt": "继续",
                    "is_auto_transition": True,
                    "options": [
                        {
                            "text": "继续",
                            "next_scene": next_first,
                            "route": "续接",
                            "effect": {}
                        }
                    ]
                })

            offset += len(scenes)
            all_scenes.extend(scenes)

        # 重新处理玩家标记
        for scene in all_scenes:
            for d in scene.get("dialogues", []):
                if d.get("speaker") == char_name:
                    d["is_player"] = True
                elif d.get("speaker") != "旁白":
                    d["is_player"] = False

        return {"scenes": all_scenes, "choices": all_choices}

    # ============================================================
    # 阶段2: 以玩家角色视角生成场景
    # ============================================================
    async def generate_scenes_from_perspective(
        self,
        content: str,
        characters: List[Dict[str, Any]],
        player_character_id: str,
        segments: List[Dict[str, Any]] = None,
        user_id: str = None,
        novel_id: str = None,
    ) -> Dict[str, Any]:
        """第二阶段: 以选定角色的第一人称视角生成场景

        Args:
            content: 章节原始内容（当 segments 为空时使用）
            characters: 角色列表
            player_character_id: 玩家角色ID
            segments: 片段列表（包含 content 和 summary），如果提供则使用片段生成
            user_id: 用户ID
            novel_id: 小说ID

        Returns:
            生成的场景数据
        """

        self._current_user_id = user_id
        self._current_novel_id = novel_id

        if not self.client:
            return self._fallback_scenes(content, characters, player_character_id)

        # 找到玩家角色
        player_char = None
        for c in characters:
            if c["id"] == player_character_id:
                player_char = c
                break

        if not player_char:
            print(f"未找到玩家角色ID: {player_character_id}")
            return self._fallback_scenes(content, characters, player_character_id)

        # 构建角色信息
        playable_chars = [c for c in characters if c.get("is_playable", False)]
        all_char_names = [c["name"] for c in characters]

        def _build_prompt(chunk_text: str, previous_summary: str = "") -> str:
            """构建场景生成 Prompt，支持上下文摘要"""
            base_prompt = PROMPT_SCENE_USER_TEMPLATE.format(
                char_name=player_char["name"],
                personality=player_char.get("personality", ""),
                speaking_style=player_char.get("speaking_style", ""),
                playable_chars=", ".join([c["name"] for c in playable_chars]),
                all_char_names=", ".join(all_char_names),
                chunk_content=chunk_text[:6000],
            )

            if previous_summary:
                context_prompt = f"""

【前文摘要】
{previous_summary}

请根据前文摘要的上下文，将当前片段改编为视觉小说场景，注意保持与前文的连贯性。"""
                return base_prompt + context_prompt

            return base_prompt

        async def _generate_single_segment(
            segment_content: str,
            segment_index: int,
            previous_summary: str = ""
        ) -> Optional[Dict[str, Any]]:
            """对单个片段调用 AI 生成场景"""
            prompt = _build_prompt(segment_content, previous_summary)
            system_prompt = PROMPT_SCENE_SYSTEM
            max_retries = 3

            for attempt in range(max_retries):
                try:
                    response = self.client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.5,
                        max_tokens=8000,
                        timeout=180.0,
                        response_format={"type": "json_object"}
                    )

                    result_text = response.choices[0].message.content
                    if not result_text or not result_text.strip():
                        print(f"场景生成返回空内容，重试 {attempt + 1}/{max_retries}")
                        continue

                    result_text = self._extract_json(result_text)
                    result = json.loads(result_text)

                    scenes = result.get("scenes", [])
                    choices = result.get("choices", [])

                    for i, scene in enumerate(scenes):
                        scene["scene_id"] = i
                        for d in scene.get("dialogues", []):
                            if d.get("speaker") == player_char["name"]:
                                d["is_player"] = True
                            elif d.get("speaker") != "旁白":
                                d["is_player"] = False

                    self._record_prompt(
                        prompt_type="scene_generation",
                        sys_prompt=system_prompt,
                        user_prompt=prompt,
                        ai_response=result_text,
                        model="deepseek-chat",
                        user_id=getattr(self, '_current_user_id', None),
                        novel_id=getattr(self, '_current_novel_id', None),
                        character_id=player_char["id"],
                    )

                    return {"scenes": scenes, "choices": choices}

                except json.JSONDecodeError as e:
                    print(f"场景JSON解析失败: {e}，重试 {attempt + 1}/{max_retries}")
                    continue
                except Exception as e:
                    print(f"场景生成失败: {e}")
                    break
            return None

        # 判断是否使用片段模式
        if segments and len(segments) > 0:
            # 使用提供的片段列表
            print(f"片段模式生成: {len(segments)} 个片段")
            results = []
            previous_summary = ""

            for seg in segments:
                seg_content = seg.get("content", "")
                seg_summary = seg.get("summary", "")
                seg_index = seg.get("index", 0)

                print(f"  生成第 {seg_index + 1}/{len(segments)} 段...")
                chunk_result = await _generate_single_segment(seg_content, seg_index, previous_summary)

                if chunk_result:
                    results.append(chunk_result)
                    # 更新摘要传递给下一段
                    if seg_summary:
                        previous_summary = seg_summary

            if results:
                merged = self._merge_scenes(results, player_char["name"])
                merged["player_character_id"] = player_character_id
                merged["player_character_name"] = player_char["name"]
                return merged

        else:
            # 无片段，使用原始内容
            result = await _generate_single_segment(content, 0)
            if result:
                result["player_character_id"] = player_character_id
                result["player_character_name"] = player_char["name"]
                return result

        return self._fallback_scenes(content, characters, player_character_id)

    # ============================================================
    # 阶段3: AI审阅
    # ============================================================
    async def review_and_fix(
        self,
        generated_data: Dict[str, Any],
        original_content: str,
        player_char_name: str,
        user_id: str = None,
        novel_id: str = None,
    ) -> Dict[str, Any]:
        """审阅生成的角色视角场景，检查问题并修复"""

        if not self.client:
            return {"fixed": False, "data": generated_data}

        scenes = generated_data.get("scenes", [])
        choices = generated_data.get("choices", [])

        system_prompt = PROMPT_REVIEW_SYSTEM
        prompt = PROMPT_REVIEW_USER_TEMPLATE.format(
            player_char_name=player_char_name,
            generated_data_json=json.dumps({"scenes": scenes, "choices": choices}, ensure_ascii=False, indent=2),
            original_content=original_content[:1500],
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=6000,
                    timeout=120.0,
                    response_format={"type": "json_object"}
                )

                result_text = response.choices[0].message.content
                if not result_text or not result_text.strip():
                    continue

                result_text = self._extract_json(result_text)
                review_result = json.loads(result_text)

                if not review_result.get("has_issues", False):
                    self._record_prompt(
                        prompt_type="review",
                        sys_prompt=system_prompt,
                        user_prompt=prompt,
                        ai_response=result_text,
                        model="deepseek-chat",
                        user_id=user_id,
                        novel_id=novel_id,
                    )
                    return {"fixed": False, "data": generated_data}

                fixed_scenes = review_result.get("fixed_scenes", [])
                if fixed_scenes:
                    fixed_map = {f["scene_id"]: f["dialogues"] for f in fixed_scenes}
                    for scene in scenes:
                        sid = scene.get("scene_id")
                        if sid in fixed_map:
                            scene["dialogues"] = fixed_map[sid]

                print(f"审阅修复了 {len(review_result.get('issues', []))} 个问题")

                self._record_prompt(
                    prompt_type="review",
                    sys_prompt=system_prompt,
                    user_prompt=prompt,
                    ai_response=result_text,
                    model="deepseek-chat",
                    user_id=user_id,
                    novel_id=novel_id,
                )

                return {"fixed": True, "data": generated_data}

            except json.JSONDecodeError as e:
                print(f"审阅JSON解析失败: {e}，重试 {attempt + 1}/{max_retries}")
                continue
            except Exception as e:
                print(f"审阅失败: {e}")
                break

        return {"fixed": False, "data": generated_data}

    def _fallback_scenes(
        self,
        content: str,
        characters: List[Dict[str, Any]],
        player_character_id: str
    ) -> Dict[str, Any]:
        """无API时的降级场景生成"""
        import re

        player_char = None
        for c in characters:
            if c["id"] == player_character_id:
                player_char = c
                break

        if not player_char:
            player_char = characters[0] if characters else {"name": "旁白", "id": generate_id()}

        sentences = re.split(r'[。！？\n]+', content)
        dialogues = []

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue

            quote_patterns = [
                r'[""\'"]([^""\'"]+)[""\'"]',
                r'「([^」]+)」',
                r'『([^』]+)』',
            ]

            found = False
            for pattern in quote_patterns:
                quotes = re.findall(pattern, sent)
                for q in quotes:
                    if len(q) > 2:
                        dialogues.append({
                            "speaker": "NPC",
                            "content": q.strip(),
                            "emotion": "normal",
                            "is_narration": False,
                            "is_player": False
                        })
                        found = True

            if not found and len(sent) > 5:
                dialogues.append({
                    "speaker": "旁白",
                    "content": sent,
                    "emotion": "normal",
                    "is_narration": True,
                    "is_player": False
                })

        if not dialogues:
            dialogues.append({
                "speaker": "旁白",
                "content": content[:200],
                "emotion": "normal",
                "is_narration": True,
                "is_player": False
            })

        return {
            "scenes": [{
                "scene_id": 0,
                "title": "场景",
                "location": "未知地点",
                "description": "",
                "characters": [player_char["name"]],
                "dialogues": dialogues
            }],
            "choices": [],
            "player_character_id": player_character_id,
            "player_character_name": player_char["name"]
        }

    def _extract_json(self, text: str) -> str:
        """从响应中提取JSON"""
        text = text.strip()

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1]

        text = text.strip()

        if text.startswith('{'):
            open_braces = 0
            open_brackets = 0
            in_string = False
            escape_next = False
            last_valid_pos = -1

            for i, char in enumerate(text):
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"' and not (i > 0 and text[i-1] == '\\'):
                    in_string = not in_string
                    continue
                if in_string:
                    continue

                if char == '{':
                    open_braces += 1
                elif char == '}':
                    open_braces -= 1
                elif char == '[':
                    open_brackets += 1
                elif char == ']':
                    open_brackets -= 1

                if open_braces == 0 and open_brackets == 0 and (char == '}' or char == ']'):
                    last_valid_pos = i

            if last_valid_pos > 0 and last_valid_pos < len(text) - 1:
                text = text[:last_valid_pos + 1]

        return text.strip()

    # ============================================================
    # Prompt 历史记录 & Self-Eval
    # ============================================================
    def _record_prompt(
        self, prompt_type, sys_prompt, user_prompt, ai_response, model,
        user_id=None, novel_id=None, chapter_fk=None, character_id=None, metadata=None
    ):
        """记录 prompt 调用历史到数据库，并异步触发 self-eval"""
        if not self.db:
            return
        try:
            record_id = self.db.create_prompt_history(
                prompt_type=prompt_type,
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                ai_response=ai_response,
                model=model,
                user_id=user_id,
                novel_id=novel_id,
                chapter_fk=chapter_fk,
                character_id=character_id,
                metadata=metadata,
            )
            # 异步触发 self-eval（不阻塞主流程）
            threading.Thread(
                target=self._self_eval_prompt,
                args=(record_id, sys_prompt, user_prompt),
                daemon=True,
            ).start()
        except Exception as e:
            print(f"记录 prompt 历史失败: {e}")

    def _self_eval_prompt(self, record_id, sys_prompt, user_prompt):
        """对已记录的 prompt 进行自我评估"""
        if not self.client:
            return
        eval_prompt = PROMPT_SELF_EVAL_USER_TEMPLATE.format(
            system_prompt=sys_prompt, user_prompt=user_prompt
        )
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": PROMPT_SELF_EVAL_SYSTEM},
                    {"role": "user", "content": eval_prompt}
                ],
                temperature=0.3, max_tokens=200, timeout=30.0
            )
            text = self._extract_json(response.choices[0].message.content)
            eval_data = json.loads(text)
            self.db.update_prompt_history_eval(record_id, json.dumps(eval_data, ensure_ascii=False))
            print(f"Self-eval 完成 (record {record_id}): score={eval_data.get('score')}")
        except Exception as e:
            print(f"Self-eval 失败: {e}")
