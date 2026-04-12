"""
v0.2 状态机模块
提供游戏状态管理、事件系统、节点导航等功能
"""

from .models import (
    GameState, CharacterState, GlobalState, ChoiceRecord,
    StoryEvent, TriggerConditions, EventEffects,
    StoryNode, StoryChoice, ChoiceOption,
    GameStateManager, EventManager, NodeNavigator, SaveManager
)
from .event_extractor import EventExtractor
from .node_builder import NodeBuilder

__all__ = [
    "GameState", "CharacterState", "GlobalState", "ChoiceRecord",
    "StoryEvent", "TriggerConditions", "EventEffects",
    "StoryNode", "StoryChoice", "ChoiceOption",
    "GameStateManager", "EventManager", "NodeNavigator", "SaveManager",
    "EventExtractor", "NodeBuilder"
]
