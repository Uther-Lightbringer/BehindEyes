"""
状态机数据模型和管理器
包含游戏状态、事件、节点、选择等核心数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Any, Optional
from datetime import datetime
import uuid
import json

from db import db


# ==================== 数据类定义 ====================

@dataclass
class CharacterState:
    """角色状态"""
    location: str = ""
    health: str = "正常"
    mood: str = ""
    inventory: List[str] = field(default_factory=list)
    relationship_with_player: int = 0
    custom_attrs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location": self.location,
            "health": self.health,
            "mood": self.mood,
            "inventory": self.inventory,
            "relationship_with_player": self.relationship_with_player,
            "custom_attrs": self.custom_attrs
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterState":
        return cls(
            location=data.get("location", ""),
            health=data.get("health", "正常"),
            mood=data.get("mood", ""),
            inventory=data.get("inventory", []),
            relationship_with_player=data.get("relationship_with_player", 0),
            custom_attrs=data.get("custom_attrs", {})
        )


@dataclass
class GlobalState:
    """全局状态"""
    current_time: str = ""
    weather: str = ""
    main_quest_stage: str = ""
    custom_attrs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_time": self.current_time,
            "weather": self.weather,
            "main_quest_stage": self.main_quest_stage,
            "custom_attrs": self.custom_attrs
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalState":
        return cls(
            current_time=data.get("current_time", ""),
            weather=data.get("weather", ""),
            main_quest_stage=data.get("main_quest_stage", ""),
            custom_attrs=data.get("custom_attrs", {})
        )


@dataclass
class ChoiceRecord:
    """选择记录"""
    node_id: str
    choice_id: str
    option_index: int
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "choice_id": self.choice_id,
            "option_index": self.option_index,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChoiceRecord":
        return cls(
            node_id=data["node_id"],
            choice_id=data["choice_id"],
            option_index=data["option_index"],
            timestamp=data.get("timestamp", datetime.utcnow().isoformat())
        )


@dataclass
class GameState:
    """游戏状态快照"""
    novel_id: str
    user_id: str
    character_id: str  # 玩家角色ID
    characters: Dict[str, CharacterState] = field(default_factory=dict)
    global_state: GlobalState = field(default_factory=GlobalState)
    flags: Set[str] = field(default_factory=set)
    current_route: str = "main"
    current_node_id: str = "start"
    visited_nodes: List[str] = field(default_factory=list)
    choice_history: List[ChoiceRecord] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "novel_id": self.novel_id,
            "user_id": self.user_id,
            "character_id": self.character_id,
            "characters": {k: v.to_dict() for k, v in self.characters.items()},
            "global_state": self.global_state.to_dict(),
            "flags": list(self.flags),
            "current_route": self.current_route,
            "current_node_id": self.current_node_id,
            "visited_nodes": self.visited_nodes,
            "choice_history": [c.to_dict() for c in self.choice_history]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GameState":
        characters = {}
        for k, v in data.get("characters", {}).items():
            characters[k] = CharacterState.from_dict(v)

        choice_history = []
        for c in data.get("choice_history", []):
            choice_history.append(ChoiceRecord.from_dict(c))

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            novel_id=data["novel_id"],
            user_id=data["user_id"],
            character_id=data["character_id"],
            characters=characters,
            global_state=GlobalState.from_dict(data.get("global_state", {})),
            flags=set(data.get("flags", [])),
            current_route=data.get("current_route", "main"),
            current_node_id=data.get("current_node_id", "start"),
            visited_nodes=data.get("visited_nodes", []),
            choice_history=choice_history
        )


@dataclass
class TriggerConditions:
    """触发条件"""
    required_flags: List[str] = field(default_factory=list)
    forbidden_flags: List[str] = field(default_factory=list)
    player_location: Optional[str] = None
    custom_conditions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_flags": self.required_flags,
            "forbidden_flags": self.forbidden_flags,
            "player_location": self.player_location,
            "custom_conditions": self.custom_conditions
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerConditions":
        if isinstance(data, cls):
            return data
        return cls(
            required_flags=data.get("required_flags", []),
            forbidden_flags=data.get("forbidden_flags", []),
            player_location=data.get("player_location"),
            custom_conditions=data.get("custom_conditions", {})
        )


@dataclass
class EventEffects:
    """事件效果"""
    set_flags: List[str] = field(default_factory=list)
    clear_flags: List[str] = field(default_factory=list)
    character_updates: Dict[str, Dict] = field(default_factory=dict)
    global_updates: Dict[str, Any] = field(default_factory=dict)
    unlock_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "set_flags": self.set_flags,
            "clear_flags": self.clear_flags,
            "character_updates": self.character_updates,
            "global_updates": self.global_updates,
            "unlock_events": self.unlock_events
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventEffects":
        if isinstance(data, cls):
            return data
        return cls(
            set_flags=data.get("set_flags", []),
            clear_flags=data.get("clear_flags", []),
            character_updates=data.get("character_updates", {}),
            global_updates=data.get("global_updates", {}),
            unlock_events=data.get("unlock_events", [])
        )


@dataclass
class StoryEvent:
    """剧情事件"""
    id: str
    novel_id: str
    name: str
    description: str = ""
    trigger_conditions: TriggerConditions = field(default_factory=TriggerConditions)
    effects: EventEffects = field(default_factory=EventEffects)
    scene_data: Optional[Dict] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "novel_id": self.novel_id,
            "name": self.name,
            "description": self.description,
            "trigger_conditions": self.trigger_conditions.to_dict(),
            "effects": self.effects.to_dict(),
            "scene_data": self.scene_data
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoryEvent":
        return cls(
            id=data["id"],
            novel_id=data["novel_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            trigger_conditions=TriggerConditions.from_dict(data.get("trigger_conditions", {})),
            effects=EventEffects.from_dict(data.get("effects", {})),
            scene_data=data.get("scene_data")
        )


@dataclass
class StoryNode:
    """剧情节点"""
    id: str
    novel_id: str
    node_id: str  # 业务ID
    route: str = "main"
    parent_node: Optional[str] = None
    scene_data: Optional[Dict] = None
    possible_events: List[str] = field(default_factory=list)
    choices: List[str] = field(default_factory=list)
    prerequisites: Dict[str, Any] = field(default_factory=dict)
    needs_generation: bool = False
    generation_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "novel_id": self.novel_id,
            "node_id": self.node_id,
            "route": self.route,
            "parent_node": self.parent_node,
            "scene_data": self.scene_data,
            "possible_events": self.possible_events,
            "choices": self.choices,
            "prerequisites": self.prerequisites,
            "needs_generation": self.needs_generation,
            "generation_hint": self.generation_hint
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoryNode":
        return cls(
            id=data["id"],
            novel_id=data["novel_id"],
            node_id=data["node_id"],
            route=data.get("route", "main"),
            parent_node=data.get("parent_node"),
            scene_data=data.get("scene_data"),
            possible_events=data.get("possible_events", []),
            choices=data.get("choices", []),
            prerequisites=data.get("prerequisites", {}),
            needs_generation=data.get("needs_generation", False),
            generation_hint=data.get("generation_hint", "")
        )


@dataclass
class ChoiceOption:
    """选择选项"""
    text: str
    effects: Dict[str, Any] = field(default_factory=dict)
    next_node: Optional[str] = None
    route: str = "main"
    show_condition: Optional[Dict] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "effects": self.effects,
            "next_node": self.next_node,
            "route": self.route,
            "show_condition": self.show_condition
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChoiceOption":
        return cls(
            text=data["text"],
            effects=data.get("effects", {}),
            next_node=data.get("next_node"),
            route=data.get("route", "main"),
            show_condition=data.get("show_condition")
        )


@dataclass
class StoryChoice:
    """剧情选择"""
    id: str
    novel_id: str
    choice_id: str  # 业务ID
    prompt: str
    at_node: str
    options: List[ChoiceOption] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "novel_id": self.novel_id,
            "choice_id": self.choice_id,
            "prompt": self.prompt,
            "at_node": self.at_node,
            "options": [o.to_dict() for o in self.options]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoryChoice":
        options = []
        for o in data.get("options", []):
            options.append(ChoiceOption.from_dict(o))
        return cls(
            id=data["id"],
            novel_id=data["novel_id"],
            choice_id=data["choice_id"],
            prompt=data.get("prompt", ""),
            at_node=data["at_node"],
            options=options
        )


# ==================== 管理器类 ====================

class GameStateManager:
    """游戏状态管理器"""

    def __init__(self):
        pass

    def create_state(self, novel_id: str, user_id: str, character_id: str,
                     initial_node: str = "start") -> GameState:
        """创建初始游戏状态"""
        state = GameState(
            novel_id=novel_id,
            user_id=user_id,
            character_id=character_id,
            current_node_id=initial_node,
            visited_nodes=[initial_node]
        )
        # 保存到数据库
        db.create_game_state(
            state_id=state.id,
            novel_id=novel_id,
            user_id=user_id,
            character_id=character_id,
            state_data=state.to_dict(),
            current_node=initial_node,
            current_route="main",
            visited_nodes=[initial_node],
            choice_history=[]
        )
        return state

    def get_state(self, state_id: str) -> Optional[GameState]:
        """获取游戏状态"""
        data = db.get_game_state(state_id)
        if not data:
            return None
        return GameState.from_dict(data["state_data"])

    def update_state(self, state: GameState) -> None:
        """更新游戏状态到数据库"""
        db.update_game_state(
            state_id=state.id,
            state_data=state.to_dict(),
            current_node=state.current_node_id,
            current_route=state.current_route,
            visited_nodes=state.visited_nodes,
            choice_history=[c.to_dict() for c in state.choice_history]
        )

    def apply_effects(self, state: GameState, effects: EventEffects) -> GameState:
        """应用事件/选择效果"""
        # 设置标记
        for flag in effects.set_flags:
            state.flags.add(flag)

        # 清除标记
        for flag in effects.clear_flags:
            state.flags.discard(flag)

        # 更新角色状态
        for char_name, updates in effects.character_updates.items():
            if char_name not in state.characters:
                state.characters[char_name] = CharacterState()
            char_state = state.characters[char_name]
            for key, value in updates.items():
                if hasattr(char_state, key):
                    setattr(char_state, key, value)
                else:
                    char_state.custom_attrs[key] = value

        # 更新全局状态
        for key, value in effects.global_updates.items():
            if hasattr(state.global_state, key):
                setattr(state.global_state, key, value)
            else:
                state.global_state.custom_attrs[key] = value

        return state

    def check_conditions(self, state: GameState, conditions: TriggerConditions) -> bool:
        """检查触发条件"""
        # 检查必需标记
        for flag in conditions.required_flags:
            if flag not in state.flags:
                return False

        # 检查禁止标记
        for flag in conditions.forbidden_flags:
            if flag in state.flags:
                return False

        # 检查玩家位置
        if conditions.player_location:
            player_char = state.characters.get(state.character_id)
            if not player_char or player_char.location != conditions.player_location:
                return False

        # 可以扩展检查自定义条件
        return True

    def record_choice(self, state: GameState, node_id: str,
                      choice_id: str, option_index: int) -> None:
        """记录选择"""
        record = ChoiceRecord(
            node_id=node_id,
            choice_id=choice_id,
            option_index=option_index
        )
        state.choice_history.append(record)


class EventManager:
    """事件管理器"""

    def __init__(self, state_manager: GameStateManager):
        self.state_manager = state_manager

    def get_events_for_node(self, novel_id: str, node_id: str) -> List[StoryEvent]:
        """获取节点可能触发的事件"""
        node_data = db.get_story_node_by_node_id(novel_id, node_id)
        if not node_data:
            return []

        event_ids = node_data.get("possible_events", [])
        events = []
        for eid in event_ids:
            event_data = db.get_story_event(eid)
            if event_data:
                events.append(StoryEvent.from_dict(event_data))
        return events

    def check_and_trigger_events(
        self,
        state: GameState,
        node_id: str
    ) -> List[tuple]:
        """检查并触发事件，返回 (事件, 新状态) 列表"""
        triggered = []
        events = self.get_events_for_node(state.novel_id, node_id)

        for event in events:
            if self.state_manager.check_conditions(state, event.trigger_conditions):
                new_state = self.state_manager.apply_effects(state, event.effects)
                triggered.append((event, new_state))
                state = new_state  # 累积效果

        return triggered


class NodeNavigator:
    """节点导航器"""

    def __init__(self, state_manager: GameStateManager, event_manager: EventManager):
        self.state_manager = state_manager
        self.event_manager = event_manager

    def get_current_node(self, state: GameState) -> Optional[StoryNode]:
        """获取当前节点"""
        node_data = db.get_story_node_by_node_id(state.novel_id, state.current_node_id)
        if not node_data:
            return None
        return StoryNode.from_dict(node_data)

    def get_available_choices(self, state: GameState) -> List[Dict]:
        """获取可用选择"""
        # 从 story_nodes 表获取当前节点的 choices
        node_data = db.get_story_node_by_node_id(state.novel_id, state.current_node_id)
        if not node_data:
            return []

        # 获取 choices（可能是 JSON 字符串或列表）
        choices_raw = node_data.get("choices", "[]")
        if isinstance(choices_raw, str):
            choices = json.loads(choices_raw)
        else:
            choices = choices_raw

        # 过滤显示条件
        result = []
        for choice in choices:
            visible_options = []
            for opt in choice.get("options", []):
                show_condition = opt.get("show_condition")
                if show_condition:
                    if self._check_show_condition(state, show_condition):
                        visible_options.append(opt)
                else:
                    visible_options.append(opt)

            if visible_options:
                choice_copy = dict(choice)
                choice_copy["options"] = visible_options
                result.append(choice_copy)

        return result

    def _check_show_condition(self, state: GameState, condition: Dict) -> bool:
        """检查选项显示条件"""
        # 简单实现：检查标记
        required_flags = condition.get("required_flags", [])
        for flag in required_flags:
            if flag not in state.flags:
                return False
        forbidden_flags = condition.get("forbidden_flags", [])
        for flag in forbidden_flags:
            if flag in state.flags:
                return False
        return True

    def navigate_to(
        self,
        state: GameState,
        choice_id: str,
        option_index: int
    ) -> GameState:
        """导航到下一个节点"""
        # 从 story_nodes 表获取当前节点的 choices
        node_data = db.get_story_node_by_node_id(state.novel_id, state.current_node_id)
        if not node_data:
            raise ValueError(f"Node {state.current_node_id} not found")

        # 获取 choices（可能是 JSON 字符串或列表）
        choices_raw = node_data.get("choices", "[]")
        if isinstance(choices_raw, str):
            choices = json.loads(choices_raw)
        else:
            choices = choices_raw

        # 找到指定的 choice
        choice_data = None
        for c in choices:
            if c.get("choice_id") == choice_id:
                choice_data = c
                break

        if not choice_data:
            # 如果没有找到 choice_id，尝试用索引
            if choices and len(choices) > 0:
                choice_data = choices[0]
            else:
                raise ValueError(f"Choice {choice_id} not found at node {state.current_node_id}")

        options = choice_data.get("options", [])
        if option_index >= len(options):
            raise ValueError(f"Option index {option_index} out of range")

        option = options[option_index]

        # 记录选择
        self.state_manager.record_choice(
            state, state.current_node_id, choice_id, option_index
        )

        # 应用选项效果
        effects = option.get("effects", {})
        if effects:
            event_effects = EventEffects(
                set_flags=effects.get("set_flags", []),
                clear_flags=effects.get("clear_flags", []),
                character_updates=effects.get("character_updates", {}),
                global_updates=effects.get("global_updates", {})
            )
            self.state_manager.apply_effects(state, event_effects)

        # 更新路线
        if option.get("route"):
            state.current_route = option["route"]

        # 移动到下一个节点
        next_node = option.get("next_node")
        if next_node:
            state.current_node_id = next_node
            if next_node not in state.visited_nodes:
                state.visited_nodes.append(next_node)

        # 检查并触发事件
        self.event_manager.check_and_trigger_events(state, state.current_node_id)

        # 保存状态
        self.state_manager.update_state(state)

        return state


class SaveManager:
    """存档管理器"""

    def __init__(self, state_manager: GameStateManager):
        self.state_manager = state_manager

    def create_save(
        self,
        game_state_id: str,
        save_name: str,
        save_slot: int,
        play_time: int = 0
    ) -> str:
        """创建存档"""
        import uuid
        state = self.state_manager.get_state(game_state_id)
        if not state:
            raise ValueError(f"Game state {game_state_id} not found")

        save_id = str(uuid.uuid4())
        db.create_game_save(
            save_id=save_id,
            game_state_id=game_state_id,
            save_name=save_name,
            save_slot=save_slot,
            state_snapshot=state.to_dict(),
            node_id=state.current_node_id,
            route=state.current_route,
            play_time=play_time
        )
        return save_id

    def load_save(self, save_id: str) -> Optional[GameState]:
        """加载存档"""
        save_data = db.get_game_save(save_id)
        if not save_data:
            return None
        return GameState.from_dict(save_data["state_snapshot"])

    def get_saves(self, game_state_id: str) -> List[Dict[str, Any]]:
        """获取存档列表"""
        saves = db.get_game_saves_by_state(game_state_id)
        return saves

    def delete_save(self, save_id: str) -> bool:
        """删除存档"""
        save = db.get_game_save(save_id)
        if save:
            db.delete_game_save(save_id)
            return True
        return False
