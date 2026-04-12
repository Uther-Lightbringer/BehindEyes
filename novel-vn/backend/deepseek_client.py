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

只输出JSON，不要其他内容。注意：不要生成id字段，系统会自动生成。"""

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
- 每个场景至少要有2条以上玩家角色的对话/独白

【分支生成核心原则】
- 分支是视觉小说的核心玩法，必须认真设计
- 每个分支都应该让玩家面临有意义的选择困境
- 选项之间要有明显的差异和后果
- 分支应该影响角色关系、剧情走向或角色成长"""

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

【玩家角色详细信息】
姓名: {char_name}
性别: {char_gender}
年龄段: {char_age_range}
性格: {char_personality}
说话风格: {char_speaking_style}
外貌: {char_appearance}
典型服装: {char_clothing}
显著特征: {char_distinctive_features}

【角色关系】
{char_relations}

{other_chars_info}

【选择分支设计指南】
一、分支类型（根据剧情需要选择）：
1. 道德抉择(moral)：不同道德立场的冲突，如"救人 vs 追敌"、"诚实 vs 善意谎言"
2. 策略选择(strategy)：不同行动方式，如"正面强攻 vs 暗中潜入"、"独自行动 vs 寻求帮助"
3. 情感回应(emotion)：不同情感表达，如"表白 vs 沉默"、"原谅 vs 记恨"
4. 探索分支(exploration)：不同探索方向，如"调查东厢房 vs 检查密室"
5. 社交选择(social)：不同社交策略，如"说服 vs 威胁"、"赞美 vs 批评"

二、分支密度：
- 每3-5个场景生成1个分支点
- 每个分支点2-4个选项
- 在剧情高潮、冲突点、重要对话后设置分支

三、选项设计原则：
- 每个选项都应有意义，不要"假选择"
- 选项应体现玩家角色的性格特点
- 选项文本要简洁有力（10-20字）
- 不同选项应有明显不同的后果导向

四、effect字段格式（重要！）：
每个选项的effect必须具体描述选择的影响：
{{
  "relationship_change": {{"角色名": 数值}},  // 好感度变化，如 {{"张三": 10, "李四": -5}}
  "flags_set": ["标记名"],      // 设置的剧情标记，如 ["救了村民", "获得信任"]
  "flags_clear": ["标记名"],    // 清除的标记
  "items_gained": ["物品名"],   // 获得物品
  "items_lost": ["物品名"],     // 失去物品
  "stat_change": {{"属性": 数值}}  // 角色属性变化，如 {{"勇气": 5, "谨慎": -2}}
}}

五、route命名规范：
- 使用简洁的中文标签，如"正义路线"、"智谋路线"、"感情路线"、"独行路线"
- 同一类型的选项使用相似的路线标签

输出JSON格式:
{{
  "scenes": [
    {{
      "scene_id": 0,
      "title": "场景标题",
      "location": "地点名称（要具体，如：城主府书房、夕阳下的河堤）",
      "description": "场景描述（1-2句，包含视觉元素：光影、氛围、关键物品）",
      "characters": ["出场的角色名列表，按出场顺序"],
      "dialogues": [
        {{
          "speaker": "旁白/{char_name}/{{NPC名}}",
          "content": "对话/旁白内容",
          "emotion": "normal/excited/angry/sad/surprised/calm/shy/worried",
          "is_narration": true/false,
          "is_player": true/false
        }}
      ]
    }}
  ],
  "choices": [
    {{
      "at_scene": 场景ID,
      "prompt": "选择提示语（描述玩家面临的困境）",
      "choice_type": "moral/strategy/emotion/exploration/social",
      "options": [
        {{
          "text": "选项文字（10-20字，体现角色性格）",
          "next_scene": 下一个场景ID,
          "route": "路线标签",
          "effect": {{
            "relationship_change": {{}},
            "flags_set": [],
            "stat_change": {{}}
          }}
        }}
      ]
    }}
  ]
}}

章节内容:
{chunk_content}

只输出JSON，不要其他内容。记住：对话占70%以上，分支要有意义，effect要具体！"""

PROMPT_REVIEW_SYSTEM = "你是一个对话审阅助手，输出规范JSON。"
PROMPT_REVIEW_USER_TEMPLATE = """你是一个对话审阅助手。请检查以下角色视角场景数据中的问题。

【审阅标准】

一、对话检查：
1. 检查每个dialogue的speaker是否正确
2. 旁白（is_narration=true）应该是描述动作、环境、事件的内容
3. NPC说的话应该speaker是NPC的名字
4. 玩家角色（{player_char_name}）的对话is_player应该为true
5. 对话占比应达到70%以上

二、分支检查：
1. 分支密度：每3-5个场景应有1个分支点
2. 分支选项数量：每个分支应有2-4个选项
3. 选项差异：不同选项应有明显区别，不能是"假选择"
4. effect字段：每个选项应有具体的effect描述，不能全为空
5. next_scene有效性：检查choices中的next_scene是否指向有效场景
6. 路线标签：route字段应有意义的命名

三、场景检查：
1. location应具体，不能是"某地"、"某处"等模糊描述
2. description应包含视觉元素
3. 场景之间应有逻辑连贯性

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
      "dialogue_index": 对话索引（可选）,
      "choice_index": 分支索引（可选）,
      "issue_type": "speaker_error/missing_choice/invalid_next/empty_effect/fake_choice/low_dialogue_ratio等",
      "description": "问题描述"
    }}
  ],
  "fixed_scenes": [
    {{
      "scene_id": 场景ID,
      "dialogues": 修复后的dialogues数组
    }}
  ],
  "fixed_choices": [
    {{
      "at_scene": 场景ID,
      "choices": 修复后的choices数组
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

    async def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
        timeout: float = 120.0
    ) -> str:
        """
        通用 API 调用方法

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            max_tokens: 最大 token 数
            temperature: 温度参数
            timeout: 超时时间（秒）

        Returns:
            AI 响应文本
        """
        if not self.client:
            raise ValueError("AI API 未配置")

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                response_format={"type": "json_object"}
            )

            result = response.choices[0].message.content
            if not result or not result.strip():
                raise ValueError("AI 返回空响应")

            result = result.strip()
            print(f"[_call_api] Response length: {len(result)}, starts with: {result[:50]}")
            return result

        except Exception as e:
            print(f"[_call_api] API call failed: {type(e).__name__}: {e}")
            raise

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
                    # 始终使用系统生成的雪花ID，忽略AI返回的ID
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
        2. 合并所有字段信息（包括外貌）
        3. 去重并保留统一的ID

        Args:
            char_lists: 多个片段的角色列表

        Returns:
            合并后的角色列表
        """
        merged = {}

        def merge_text_field(existing_val: str, new_val: str) -> str:
            """合并文本字段，避免重复"""
            if not new_val:
                return existing_val
            if not existing_val:
                return new_val
            if new_val in existing_val:
                return existing_val
            return f"{existing_val}；{new_val}".strip("；")

        for chars in char_lists:
            for char in chars:
                name = char.get("name", "")
                if not name:
                    continue

                if name in merged:
                    # 合并信息
                    existing = merged[name]

                    # 合并文本字段
                    for field in ["personality", "speaking_style", "gender", "age_range"]:
                        if char.get(field):
                            existing[field] = merge_text_field(existing.get(field, ""), char[field])

                    # 合并外貌相关字段（优先保留非空值，或合并）
                    for field in ["appearance", "clothing", "distinctive_features"]:
                        new_val = char.get(field, "")
                        existing_val = existing.get(field, "")
                        if new_val and not existing_val:
                            existing[field] = new_val
                        elif new_val and existing_val and new_val not in existing_val:
                            # 外貌描写可以合并（不同片段可能有不同角度的描写）
                            existing[field] = f"{existing_val}。{new_val}"

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
                    # 始终使用系统生成的雪花ID
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
    async def generate_segment_summary(self, content: str, user_id: str = None, novel_id: str = None) -> Dict[str, Any]:
        """生成片段的结构化上下文信息

        Returns:
            {
                "summary": "剧情摘要",
                "key_events": ["事件列表"],
                "character_states": {"角色名": {"location": "", "emotion": "", "status": ""}},
                "relationship_changes": {},
                "unresolved_threads": ["未解决线索"],
                "flags_set": ["剧情标记"]
            }
        """
        if not self.client:
            return {"summary": "", "key_events": [], "character_states": {}, "unresolved_threads": []}

        prompt = f"""分析以下小说片段，提取结构化上下文信息。

【输出格式】(JSON)
{{
  "summary": "100字以内的剧情摘要",
  "key_events": ["发生的关键事件1", "发生的关键事件2"],
  "character_states": {{
    "角色名": {{
      "location": "当前所在位置",
      "emotion": "当前情绪状态",
      "status": "特殊状态（受伤、中毒等，无则为空字符串）"
    }}
  }},
  "relationship_changes": {{
    "角色A": {{"角色B": "关系变化描述"}}
  }},
  "unresolved_threads": ["未解决的伏笔或问题"],
  "flags_set": ["已触发的重要剧情标记"]
}}

小说片段：
{content[:3000]}

只输出JSON，不要其他内容。"""

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=800,
                timeout=30.0,
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content.strip()
            result_text = self._extract_json(result_text)
            context_data = json.loads(result_text)

            # 确保必要字段存在
            context_data.setdefault("summary", "")
            context_data.setdefault("key_events", [])
            context_data.setdefault("character_states", {})
            context_data.setdefault("relationship_changes", {})
            context_data.setdefault("unresolved_threads", [])
            context_data.setdefault("flags_set", [])

            self._record_prompt(
                prompt_type="segment_context",
                sys_prompt="",
                user_prompt=prompt,
                ai_response=result_text,
                model="deepseek-chat",
                user_id=user_id,
                novel_id=novel_id,
            )

            return context_data

        except Exception as e:
            print(f"上下文生成失败: {e}")
            return {"summary": "", "key_events": [], "character_states": {}, "unresolved_threads": []}

    def format_context_for_prompt(self, context_data: Dict[str, Any], player_char_name: str = "") -> str:
        """将结构化上下文格式化为 Prompt 文本

        Args:
            context_data: 结构化上下文数据
            player_char_name: 玩家角色名（用于过滤显示）

        Returns:
            格式化后的上下文文本
        """
        if not context_data:
            return ""

        lines = []

        # 摘要
        summary = context_data.get("summary", "")
        if summary:
            lines.append(f"剧情摘要：{summary}")

        # 关键事件
        key_events = context_data.get("key_events", [])
        if key_events:
            lines.append("\n关键事件：")
            for event in key_events[:5]:  # 最多显示5个
                lines.append(f"- {event}")

        # 角色状态（只显示重要角色的状态变化）
        character_states = context_data.get("character_states", {})
        if character_states:
            lines.append("\n角色当前状态：")
            for char_name, state in list(character_states.items())[:5]:  # 最多显示5个角色
                location = state.get("location", "")
                emotion = state.get("emotion", "")
                status = state.get("status", "")
                state_text = ""
                if location:
                    state_text += f"位于「{location}」"
                if emotion:
                    state_text += f"，情绪{emotion}"
                if status:
                    state_text += f"，{status}"
                if state_text:
                    lines.append(f"- {char_name}：{state_text}")

        # 未解决的线索
        unresolved_threads = context_data.get("unresolved_threads", [])
        if unresolved_threads:
            lines.append("\n未解决的线索：")
            for thread in unresolved_threads[:3]:  # 最多显示3个
                lines.append(f"- {thread}")

        # 已设置的剧情标记
        flags_set = context_data.get("flags_set", [])
        if flags_set:
            lines.append(f"\n已触发剧情：{', '.join(flags_set[:5])}")

        return "\n".join(lines)

    def extract_dynamic_context(self, scenes: List[Dict[str, Any]], player_char_name: str) -> Dict[str, Any]:
        """
        G2.4阶段：从生成的场景中提取动态上下文

        与P3阶段的静态上下文不同，这是基于实际生成的场景内容提取的，
        能更准确地反映当前剧情状态。

        Args:
            scenes: 生成的场景列表
            player_char_name: 玩家角色名

        Returns:
            动态上下文字典
        """
        if not scenes:
            return {}

        # 最后一个场景
        last_scene = scenes[-1]

        # 提取最后场景的地点
        last_location = last_scene.get("location", "")

        # 提取最后出现的角色列表
        last_characters = last_scene.get("characters", [])

        # 从最后几段对话提取玩家角色的情绪
        last_emotion = self._extract_last_emotion(last_scene, player_char_name)

        # 生成场景摘要（基于最后一个场景）
        scene_summary = self._generate_scene_summary(scenes)

        # 提取场景中提到的关键物品/地点
        key_elements = self._extract_key_elements(scenes)

        return {
            "last_location": last_location,
            "last_characters": last_characters,
            "last_emotion": last_emotion,
            "scene_count": len(scenes),
            "generated_summary": scene_summary,
            "key_elements": key_elements,
            "player_char_name": player_char_name,
        }

    def _extract_last_emotion(self, scene: Dict[str, Any], player_char_name: str) -> str:
        """从场景的最后几段对话中提取玩家角色的情绪"""
        dialogues = scene.get("dialogues", [])
        if not dialogues:
            return ""

        # 从后往前找玩家角色的对话
        for d in reversed(dialogues[-5:]):
            if d.get("speaker") == player_char_name and d.get("emotion"):
                return d.get("emotion", "")

        return ""

    def _generate_scene_summary(self, scenes: List[Dict[str, Any]]) -> str:
        """基于场景生成简短摘要"""
        if not scenes:
            return ""

        summaries = []
        for scene in scenes:
            title = scene.get("title", "")
            location = scene.get("location", "")
            description = scene.get("description", "")

            # 简单拼接关键信息
            if title and location:
                summaries.append(f"{title}({location})")
            elif description:
                summaries.append(description[:50])

        return " → ".join(summaries[:3])  # 最多3个场景

    def _extract_key_elements(self, scenes: List[Dict[str, Any]]) -> List[str]:
        """从场景中提取关键元素（地点、物品等）"""
        elements = set()

        for scene in scenes:
            location = scene.get("location", "")
            if location:
                elements.add(location)

        return list(elements)[:5]  # 最多5个

    def merge_static_and_dynamic_context(
        self,
        static_context: Dict[str, Any],
        dynamic_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        合并P3静态上下文和G2.4动态上下文

        策略：
        - 摘要：优先使用动态上下文（实际生成的）
        - 关键事件：使用静态上下文（原文剧情走向）
        - 角色状态：动态更新位置和情绪
        - 未解决线索：使用静态上下文

        Args:
            static_context: P3阶段生成的静态上下文
            dynamic_context: G2.4阶段提取的动态上下文

        Returns:
            合并后的上下文
        """
        if not static_context:
            return dynamic_context
        if not dynamic_context:
            return static_context

        merged = {
            "summary": dynamic_context.get("generated_summary", "") or static_context.get("summary", ""),
            "key_events": static_context.get("key_events", []),
            "character_states": dict(static_context.get("character_states", {})),
            "relationship_changes": static_context.get("relationship_changes", {}),
            "unresolved_threads": static_context.get("unresolved_threads", []),
            "flags_set": static_context.get("flags_set", []),
            "last_location": dynamic_context.get("last_location", ""),
            "last_emotion": dynamic_context.get("last_emotion", ""),
        }

        # 动态更新玩家角色的状态
        player_name = dynamic_context.get("player_char_name", "")
        last_location = dynamic_context.get("last_location", "")
        last_emotion = dynamic_context.get("last_emotion", "")

        if player_name:
            if player_name in merged["character_states"]:
                # 更新现有状态
                if last_location:
                    merged["character_states"][player_name]["location"] = last_location
                if last_emotion:
                    merged["character_states"][player_name]["emotion"] = last_emotion
            else:
                # 创建新状态
                merged["character_states"][player_name] = {
                    "location": last_location,
                    "emotion": last_emotion,
                    "status": ""
                }

        return merged

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

        # 构建玩家角色关系字符串
        relations = player_char.get("relations", {})
        relations_text = ""
        if relations:
            relations_lines = []
            for other_name, relation_desc in relations.items():
                relations_lines.append(f"- 与{other_name}: {relation_desc}")
            relations_text = "\n".join(relations_lines)
        else:
            relations_text = "（暂无已知关系）"

        # 构建其他角色信息字符串（包含关系）
        other_chars_info_lines = ["【其他出场角色】"]
        for char in characters:
            if char["id"] != player_character_id and char["name"] in all_char_names:
                char_info = f"- {char['name']}"
                details = []
                if char.get("personality"):
                    details.append(f"性格: {char['personality']}")
                if char.get("speaking_style"):
                    details.append(f"说话风格: {char['speaking_style']}")
                if char.get("appearance"):
                    details.append(f"外貌: {char['appearance']}")
                # 添加与玩家角色的关系
                char_relations = char.get("relations", {})
                if player_char["name"] in char_relations:
                    details.append(f"与你的关系: {char_relations[player_char['name']]}")
                if details:
                    char_info += "（" + "；".join(details) + "）"
                other_chars_info_lines.append(char_info)

        other_chars_info = "\n".join(other_chars_info_lines)

        def _build_prompt(chunk_text: str, context_data: Dict[str, Any] = None) -> str:
            """构建场景生成 Prompt，支持结构化上下文"""
            base_prompt = PROMPT_SCENE_USER_TEMPLATE.format(
                char_name=player_char["name"],
                char_gender=player_char.get("gender", "未知"),
                char_age_range=player_char.get("age_range", "未知"),
                char_personality=player_char.get("personality", "未知"),
                char_speaking_style=player_char.get("speaking_style", "未知"),
                char_appearance=player_char.get("appearance", "未描述"),
                char_clothing=player_char.get("clothing", "未描述"),
                char_distinctive_features=player_char.get("distinctive_features", "无"),
                char_relations=relations_text,
                other_chars_info=other_chars_info,
                chunk_content=chunk_text[:6000],
            )

            # 如果有结构化上下文，格式化并注入
            if context_data:
                context_text = self.format_context_for_prompt(context_data, player_char["name"])
                if context_text:
                    context_prompt = f"""

【前文上下文】
{context_text}

请根据以上上下文，将当前片段改编为视觉小说场景，注意保持与前文的连贯性。"""
                    return base_prompt + context_prompt

            return base_prompt

        async def _generate_single_segment(
            segment_content: str,
            segment_index: int,
            context_data: Dict[str, Any] = None
        ) -> Optional[Dict[str, Any]]:
            """对单个片段调用 AI 生成场景"""
            prompt = _build_prompt(segment_content, context_data)
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
            accumulated_context = None  # 累积的上下文（用于传递给下一个片段）

            for seg in segments:
                seg_content = seg.get("content", "")
                seg_static_context = seg.get("context", {})  # P3阶段生成的静态上下文
                seg_index = seg.get("index", 0)

                print(f"  生成第 {seg_index + 1}/{len(segments)} 段...")

                # G2.1: 使用累积的上下文生成当前片段
                chunk_result = await _generate_single_segment(seg_content, seg_index, accumulated_context)

                if chunk_result:
                    results.append(chunk_result)

                    # G2.4: 从生成的场景中提取动态上下文
                    scenes = chunk_result.get("scenes", [])
                    dynamic_context = self.extract_dynamic_context(scenes, player_char["name"])

                    print(f"    动态上下文: location={dynamic_context.get('last_location', '')}, "
                          f"emotion={dynamic_context.get('last_emotion', '')}")

                    # 合并静态上下文和动态上下文
                    if seg_static_context or dynamic_context:
                        merged_segment_context = self.merge_static_and_dynamic_context(
                            seg_static_context, dynamic_context
                        )

                        # 更新累积上下文（传递给下一个片段）
                        if accumulated_context is None:
                            accumulated_context = merged_segment_context
                        else:
                            # 合并之前的累积上下文和当前片段的上下文
                            accumulated_context = self._merge_context(accumulated_context, merged_segment_context)

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

    def _merge_context(self, prev_context: Dict[str, Any], new_context: Dict[str, Any]) -> Dict[str, Any]:
        """合并两个片段的上下文信息

        规则：
        - summary: 使用新的摘要（因为要传给下一段）
        - key_events: 合并并保留最近的事件
        - character_states: 更新为新状态
        - unresolved_threads: 合并未解决的线索
        - flags_set: 合并
        """
        merged = {
            "summary": new_context.get("summary", prev_context.get("summary", "")),
            "key_events": [],
            "character_states": {},
            "relationship_changes": {},
            "unresolved_threads": [],
            "flags_set": [],
        }

        # 合并关键事件（保留最近10个）
        prev_events = prev_context.get("key_events", [])
        new_events = new_context.get("key_events", [])
        merged["key_events"] = (prev_events + new_events)[-10:]

        # 合并角色状态（新状态覆盖旧状态）
        prev_states = prev_context.get("character_states", {})
        new_states = new_context.get("character_states", {})
        merged["character_states"] = {**prev_states, **new_states}

        # 合并关系变化
        prev_rel = prev_context.get("relationship_changes", {})
        new_rel = new_context.get("relationship_changes", {})
        for char, relations in new_rel.items():
            if char not in prev_rel:
                prev_rel[char] = {}
            prev_rel[char].update(relations)
        merged["relationship_changes"] = prev_rel

        # 合并未解决线索（去重）
        prev_threads = prev_context.get("unresolved_threads", [])
        new_threads = new_context.get("unresolved_threads", [])
        merged["unresolved_threads"] = list(set(prev_threads + new_threads))[-5:]

        # 合并标记
        prev_flags = prev_context.get("flags_set", [])
        new_flags = new_context.get("flags_set", [])
        merged["flags_set"] = list(set(prev_flags + new_flags))

        return merged

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

                # 修复分支选择
                fixed_choices = review_result.get("fixed_choices", [])
                if fixed_choices:
                    for fixed_choice in fixed_choices:
                        at_scene = fixed_choice.get("at_scene")
                        new_choices = fixed_choice.get("choices", [])
                        # 找到并替换对应场景的分支
                        for i, choice in enumerate(choices):
                            if choice.get("at_scene") == at_scene:
                                choices[i] = new_choices[0] if new_choices else choice
                                break
                        else:
                            # 如果没找到，添加新的分支
                            if new_choices:
                                choices.extend(new_choices)

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

        # 如果不是以 { 或 [ 开头，尝试找到 JSON 对象
        if not text.startswith('{') and not text.startswith('['):
            if '{' in text:
                text = text[text.find('{'):]
            elif '[' in text:
                text = text[text.find('['):]

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
