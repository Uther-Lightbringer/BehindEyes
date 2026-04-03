# Novel Game - 文字冒险游戏引擎

从小说文本解析角色和剧情，让玩家扮演角色体验/改变剧情。

## 快速开始

```bash
pip install -r requirements.txt

# 解析小说
python -m src.parser your_novel.txt

# 运行游戏
python -m src.engine data/output.json
```

## 项目结构

```
novel-game/
├── src/
│   ├── parser.py    # 小说文本解析器
│   └── engine.py    # 剧情引擎
├── data/
│   └── sample.json  # 示例数据
└── tests/
    └── test_engine.py
```

## 玩法

1. 选择一个角色扮演
2. 阅读剧情片段
3. 做选择影响剧情走向
4. 不同的选择导致不同结局

## 技术验证状态

- [x] 小说解析 (parser.py)
- [x] 剧情引擎 (engine.py)
- [x] 角色选择系统
- [x] 分支剧情
- [ ] AI对话集成 (下一步)
