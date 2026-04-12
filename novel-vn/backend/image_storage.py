"""
图片存储管理：下载远程图片到本地，提供静态文件访问
"""

import os
import hashlib
import aiohttp
from typing import Optional
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

IMAGE_DIR = os.getenv(
    "IMAGE_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "images",
    ),
)
os.makedirs(IMAGE_DIR, exist_ok=True)

# URL -> 本地文件映射缓存
_char_image_cache: dict[str, str] = {}


def get_local_image_path(novel_id: str, char_id: str) -> str:
    """返回本地图片路径"""
    return os.path.join(IMAGE_DIR, f"{novel_id}_{char_id}.jpg")


def image_url_for_char(novel_id: str, char_id: str, full_url: bool = False) -> str:
    """返回前端可用的图片 URL（相对路径，由前端自行拼接完整URL）"""
    filename = f"{novel_id}_{char_id}.jpg"
    path = f"/api/images/{filename}"
    if full_url:
        return f"http://localhost:4557{path}"
    return path


async def download_and_save(
    url: str, novel_id: str, char_id: str
) -> Optional[str]:
    """从远程 URL 下载图片到本地，返回本地相对路径"""
    local_path = get_local_image_path(novel_id, char_id)
    _char_image_cache[f"{novel_id}_{char_id}"] = local_path

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(local_path, "wb") as f:
                        f.write(data)
                    return local_path
                print(f"下载图片失败 [{resp.status}]: {url}")
    except Exception as e:
        print(f"下载图片异常: {e}")

    return None


def mount_static_images(app: FastAPI) -> None:
    """挂载静态图片目录，提供 /api/images 访问"""
    app.mount("/api/images", StaticFiles(directory=IMAGE_DIR), name="images")


# 地点背景图缓存
_location_image_cache: dict[str, str] = {}


def get_location_image_path(novel_id: str, location: str) -> str:
    """生成本地路径，用地点名称的hash作为文件名，避免重复"""
    location_hash = hashlib.md5(location.encode()).hexdigest()[:12]
    return os.path.join(IMAGE_DIR, f"loc_{novel_id}_{location_hash}.jpg")


def location_image_url(novel_id: str, location: str, full_url: bool = False) -> str:
    """返回地点背景图的静态访问 URL（相对路径）"""
    filename = os.path.basename(get_location_image_path(novel_id, location))
    path = f"/api/images/{filename}"
    if full_url:
        return f"http://localhost:4557{path}"
    return path


def location_image_exists(novel_id: str, location: str) -> bool:
    """检查地点背景图是否已存在"""
    local_path = get_location_image_path(novel_id, location)
    return os.path.exists(local_path)


def get_existing_location_image_url(novel_id: str, location: str, full_url: bool = True) -> Optional[str]:
    """如果地点背景图已存在，返回 URL"""
    if location_image_exists(novel_id, location):
        return location_image_url(novel_id, location, full_url)
    return None
