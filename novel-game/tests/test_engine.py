"""测试解析器和引擎"""

import sys
sys.path.insert(0, 'src')

from parser import NovelParser, parse_novel_file
from engine import StoryEngine, GameState

# 测试解析器
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

def test_parser():
    print("=== 测试解析器 ===")
    parser = NovelParser(sample_text)
    result = parser.parse()

    print(f"[OK] 解析完成")
    print(f"  - 角色数: {len(result['characters'])}")
    print(f"  - 事件数: {len(result['events'])}")
    print(f"  - 剧情节点: {len(result['plot_nodes'])}")

    for char in result['characters']:
        print(f"  角色: {char['name']} (出现{char['mentions']}次)")

    return result

def test_engine(plot_data):
    print("\n=== 测试引擎 ===")
    engine = StoryEngine(plot_data)

    # 开始游戏
    node = engine.start("张三")
    print(f"✓ 游戏开始")
    print(f"  当前节点: {node['node_id']}")
    print(f"  内容: {node['content'][:50]}...")

    # 做个选择
    node = engine.make_choice(0)
    print(f"✓ 选择后")
    print(f"  当前节点: {node['node_id']}")
    print(f"  出场角色: {node['characters_on_stage']}")

    # 再做选择直到结束
    while engine.status.state == GameState.PLAYING:
        node = engine.make_choice(0)

    print(f"✓ 到达结局 (节点 {node['node_id'] if node['node_id'] != -1 else 'END'})")

    print(f"\n=== 所有测试通过 ===")


if __name__ == "__main__":
    result = test_parser()
    test_engine(result)
