# BehindEyes

> *See the story through their eyes*

Transform text novels into interactive visual novels. Experience stories from any character's perspective.

**[中文文档](#中文说明)**

---

## Features

- **Multi-perspective Experience** - Choose any character and experience the story through their eyes
- **AI-Powered Generation** - Automatic character extraction and scene generation using LLM
- **Branching Storylines** - Your choices affect the narrative and relationships
- **Visual Novel Format** - Character sprites, backgrounds, and dialogue system
- **Multiple LLM Support** - DeepSeek, OpenAI, MiniMax, Qwen, Zhipu AI

## Quick Start

### Docker Compose (Recommended)

```bash
cd novel-vn
docker compose up -d --build
```

Access the application:
- **Frontend**: http://localhost:4558
- **API**: http://localhost:4557/api
- **Admin Panel**: http://localhost:4558/admin.html

Default credentials: `admin` / `admin` (please change after first login)

### Local Development

```bash
# Backend
cd novel-vn/backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (another terminal)
cd novel-vn/frontend
python -m http.server 3000
```

## Usage

1. **Upload a novel** - Paste your novel text in the admin panel
2. **Wait for parsing** - AI extracts characters and generates character cards
3. **Select a character** - Choose whose perspective you want to experience
4. **Play the visual novel** - Read dialogues, make choices, affect the story

## Architecture

```
novel-vn/
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── llm_client.py        # Unified LLM client (litellm)
│   ├── deepseek_client.py   # Scene generation logic
│   ├── db.py                # SQLite persistence
│   ├── auth.py              # Session authentication
│   └── image_client.py      # AI image generation
├── frontend/
│   ├── index.html           # Player interface
│   ├── admin.html           # Admin panel
│   └── login.html           # Authentication
└── docker-compose.yml
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AI_DEEPSEEK_API_KEY` | DeepSeek API Key | Yes (or other LLM) |
| `EVOLINK_API_KEY` | Image generation API Key | No |
| `SESSION_SECRET` | Session signing secret | Recommended for production |

## Supported LLM Providers

| Provider | Default Model |
|----------|---------------|
| DeepSeek | deepseek-chat |
| OpenAI | gpt-3.5-turbo |
| MiniMax | abab6.5s-chat |
| Qwen (通义千问) | qwen-turbo |
| Zhipu AI (智谱) | glm-4 |

Users can configure their preferred provider and API key in the admin panel.

## License

MIT License

---

## 中文说明

将文本小说转换为可互动的视觉小说。选择任意角色，以第一人称视角体验故事。

### 功能特点

- **多视角体验** - 选择任意角色，以第一人称视角重新体验故事
- **AI 智能生成** - 自动提取角色、生成场景对话
- **分支剧情** - 你的选择会影响故事走向和角色关系
- **视觉小说格式** - 角色立绘、场景背景、对话系统
- **多模型支持** - 支持 DeepSeek、OpenAI、MiniMax、通义千问、智谱 AI

### 快速开始

```bash
cd novel-vn
docker compose up -d --build
```

访问地址：
- 前端页面：http://localhost:4558
- 管理后台：http://localhost:4558/admin.html

默认账户：`admin` / `admin`（首次登录后请修改密码）

### 使用流程

1. **上传小说** - 在管理后台粘贴小说文本
2. **等待解析** - AI 自动提取角色信息
3. **选择角色** - 选择你想扮演的角色
4. **开始游玩** - 阅读对话、做出选择、影响剧情

---

> *Every character has a story. Now it's yours.*
