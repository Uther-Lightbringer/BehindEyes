"""
FastAPI 后端入口 - 模块化版本
路由已拆分到 routers/ 目录
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import db
from image_storage import mount_static_images

# 导入路由
from routers import (
    auth_router,
    novels_router,
    generate_router,
    game_router,
    admin_router,
    llm_router,
    settings_router,
)

app = FastAPI(title="Novel Visual Novel API")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态图片服务
mount_static_images(app)

# 启动时自动创建默认管理员
db.ensure_admin_exists()

# 注册路由
app.include_router(auth_router)
app.include_router(novels_router)
app.include_router(generate_router)
app.include_router(game_router)
app.include_router(admin_router)
app.include_router(llm_router)
app.include_router(settings_router)


@app.get("/api/health")
async def health():
    """健康检查"""
    from deepseek_client import DeepSeekClient
    from image_client import EvolinkImageClient

    deepseek = DeepSeekClient(db=db)
    image_client = EvolinkImageClient()

    return {
        "status": "ok",
        "deepseek_configured": deepseek.is_configured(),
        "image_generation_configured": image_client.is_configured(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
