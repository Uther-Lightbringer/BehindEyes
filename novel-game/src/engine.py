"""
剧情引擎 - 驱动游戏运行
"""

import json
import random
from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum


class GameState(Enum):
    PLAYING = "playing"
    ENDED = "ended"
    PAUSED = "paused"


@dataclass
class GameStatus:
    current_node: int
    state: GameState
    player_character: Optional[str] = None
    flags: Dict = None

    def __post_init__(self):
        if self.flags is None:
            self.flags = {}


class StoryEngine:
    def __init__(self, plot_data: Dict):
        self.nodes = plot_data['plot_nodes']
        self.characters = {c['name']: c for c in plot_data['characters']}
        self.status = GameStatus(current_node=0, state=GameState.PLAYING)
        self.history: List[int] = []

    def start(self, player_character: str = None):
        """开始游戏"""
        self.status.player_character = player_character
        self.status.state = GameState.PLAYING
        self.history = [0]
        return self.get_current_node()

    def get_current_node(self) -> Dict:
        """获取当前剧情节点"""
        node = self.nodes[self.status.current_node]
        return {
            "node_id": node['id'],
            "content": node['content'],
            "choices": node['choices'],
            "characters_on_stage": node['characters'],
            "player_character": self.status.player_character
        }

    def make_choice(self, choice_index: int) -> Dict:
        """玩家做出选择"""
        current_node = self.nodes[self.status.current_node]

        if choice_index >= len(current_node['choices']):
            return {"error": "无效选择"}

        choice = current_node['choices'][choice_index]
        next_node_id = choice['next_node']

        # 更新状态
        self.status.current_node = next_node_id
        self.history.append(next_node_id)

        # 应用选择效果
        if choice.get('effect'):
            self.status.flags.update(choice['effect'])

        # 检查是否结束
        if next_node_id == -1 or next_node_id >= len(self.nodes):
            self.status.state = GameState.ENDED

        return self.get_current_node()

    def get_available_characters(self) -> List[Dict]:
        """获取可扮演的角色列表"""
        return [
            {"name": c['name'], "description": c['description']}
            for c in self.characters.values()
        ]

    def get_story_summary(self) -> str:
        """获取当前剧情摘要"""
        visited_contents = [self.nodes[n]['content'] for n in self.history]
        return f"你已经经历了 {len(self.history)} 个剧情节点"


class SimpleUI:
    """简单命令行界面"""

    @staticmethod
    def print_node(node_data: Dict):
        print("\n" + "="*50)
        print(f"\n【剧情】\n{node_data['content']}")
        print(f"\n出场角色: {', '.join(node_data['characters_on_stage'])}")
        if node_data['player_character']:
            print(f"你扮演: {node_data['player_character']}")

    @staticmethod
    def print_choices(choices: List[Dict]):
        print("\n【选择】")
        for i, choice in enumerate(choices):
            print(f"  {i+1}. {choice['text']}")

    @staticmethod
    def print_ending():
        print("\n" + "="*50)
        print("【结局】故事到此结束，感谢游玩！")
        print("="*50)


def run_game(novel_json_path: str):
    """运行游戏"""
    with open(novel_json_path, 'r', encoding='utf-8') as f:
        plot_data = json.load(f)

    engine = StoryEngine(plot_data)
    ui = SimpleUI()

    # 选择角色
    print("\n欢迎来到文字冒险游戏！")
    print("\n可扮演角色:")
    chars = engine.get_available_characters()
    for i, char in enumerate(chars):
        print(f"  {i+1}. {char['name']}")

    choice = input("\n选择角色编号（直接回车跳过）: ").strip()
    player_char = chars[int(choice)-1]['name'] if choice else None

    # 开始游戏
    current = engine.start(player_char)
    ui.print_node(current)

    # 游戏循环
    while engine.status.state == GameState.PLAYING:
        ui.print_choices(current['choices'])
        user_input = input("\n你的选择: ").strip()

        try:
            choice_idx = int(user_input) - 1
            current = engine.make_choice(choice_idx)
            if engine.status.state == GameState.ENDED:
                ui.print_ending()
            else:
                ui.print_node(current)
        except (ValueError, IndexError):
            print("无效输入，请重新选择")


if __name__ == "__main__":
    # 测试
    import tempfile
    from src.parser import NovelParser

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

    engine = StoryEngine(result)
    print("可扮演角色:", engine.get_available_characters())
    print("初始节点:", engine.start("张三"))
