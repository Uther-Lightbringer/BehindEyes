"""
FastAPI 后端入口 - 多用户持久化版本
支持: 注册/登录/登出 → 上传小说(公开/私有) → 解析角色卡 → 选择角色 → AI生成视角场景 → 审阅 → 游戏
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import uuid
import threading

from deepseek_client import DeepSeekClient, generate_id
from image_client import EvolinkImageClient
from image_storage import download_and_save, image_url_for_char, mount_static_images, get_location_image_path, location_image_url, location_image_exists, get_existing_location_image_url
from db import db
from auth import (
    register_user, login_user, logout_user,
    get_current_user, login_required, admin_required,
)

app = FastAPI(title="Novel Visual Novel API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mount_static_images(app)

deepseek = DeepSeekClient(db=db)
image_client = EvolinkImageClient()

# 启动时自动创建默认管理员
db.ensure_admin_exists()


# ============================================================
# Pydantic 模型
# ============================================================
class ChapterData(BaseModel):
    chapter_id: int
    title: str
    content: str


class ParseRequest(BaseModel):
    novel_title: str
    chapters: List[ChapterData]
    visibility: Optional[str] = "public"
    art_style: Optional[str] = "anime"
    style_keywords: Optional[str] = ""


class AuthRequest(BaseModel):
    username: str
    password: str


# ============================================================
# Auth API
# ============================================================
@app.post("/api/auth/register")
async def api_register(req: AuthRequest):
    if not req.username or len(req.username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="密码至少 4 个字符")
    return await register_user(req.username, req.password)


@app.post("/api/auth/login")
async def api_login(req: AuthRequest):
    return await login_user(req.username, req.password)


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    return await logout_user(request)


@app.get("/api/auth/me")
async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"logged_in": False}
    return {"logged_in": True, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}


# ============================================================
# 小说列表 API（首页）
# ============================================================
@app.get("/api/novels")
async def list_novels(request: Request):
    """获取小说列表（游客：仅公开；登录用户：公开 + 自己的私有）"""
    user = get_current_user(request)
    novels = db.get_all_novels(include_private=bool(user and user.get("role") == "admin"))

    # 如果用户已登录，添加自己的私有小说
    if user:
        user_novels = db.get_user_novels(user["id"])
        # 添加尚未在列表中的私有小说
        existing_ids = {n["id"] for n in novels}
        for n in user_novels:
            if n["id"] not in existing_ids or n["visibility"] == "private":
                pass  # 已在 novels 中的不重复
        # 合并用户所有小说(包含私有)
        all_user_novels = db.get_user_novels(user["id"])
        for n in all_user_novels:
            if n["id"] not in existing_ids:
                novels.append(n)
                existing_ids.add(n["id"])

    return {"novels": novels}


# ============================================================
# API 1: 解析小说，生成角色卡
# ============================================================
@app.post("/api/parse")
async def start_parse(request_body: ParseRequest, request: Request, background_tasks: BackgroundTasks):
    """发起异步解析任务，只生成角色卡（支持任意长度章节自动拆分）"""
    user = await login_required(get_current_user(request))

    task_id = str(uuid.uuid4())
    novel_id = str(uuid.uuid4())

    db.create_novel(
        novel_id,
        request_body.novel_title,
        user["id"],
        request_body.visibility or "public",
        request_body.art_style or "anime",
        request_body.style_keywords or "",
    )
    db.create_task(task_id, novel_id, request_body.novel_title, len(request_body.chapters))

    def run_task():
        try:
            asyncio.run(run_parse_task(task_id, request_body, novel_id, user["id"]))
        except Exception as e:
            print(f"[{task_id}] 解析任务异常: {e}")
            import traceback
            traceback.print_exc()
            db.update_task(
                task_id,
                status="failed",
                message=f"解析异常: {e}",
                error=str(e),
            )

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    return {
        "task_id": task_id,
        "status": "pending",
        "message": "等待开始..."
    }


async def run_parse_task(task_id: str, request: ParseRequest, novel_id: str, user_id: str):
    """异步执行角色卡解析任务（支持片段化处理）"""
    settings = db.get_user_settings(user_id)
    chunk_size = settings.get("chunk_size", 5000)
    chunk_overlap = settings.get("chunk_overlap", 300)

    total_chapters = len(request.chapters)

    try:
        all_chapters_data = []
        all_segments_characters = []  # 收集所有片段的角色

        # ==================== 阶段1: 拆分片段 + 提取角色/摘要 ====================
        for i, chapter in enumerate(request.chapters):
            db.update_task(
                task_id,
                status="parsing_characters",
                progress=i / total_chapters,
                current_step=f"解析章节 {i + 1}/{total_chapters}",
                current_step_num=i + 1,
                message=f"正在解析章节 {i + 1}...",
            )
            print(f"[{task_id}] 正在解析章节 {i + 1}/{total_chapters}: {chapter.title}")

            # 创建章节记录
            chapter_key = str(uuid.uuid4())
            db.create_chapter(
                chapter_key, novel_id, chapter.chapter_id, chapter.title, chapter.content
            )

            # 拆分片段
            segments_data = deepseek._chunk_content(chapter.content, chunk_size, chunk_overlap)
            print(f"[{task_id}]   拆分为 {len(segments_data)} 个片段")

            # 为每个片段并行提取角色和摘要
            segment_records = []
            for seg in segments_data:
                segment_id = str(uuid.uuid4())
                db.create_segment(segment_id, chapter_key, seg["index"], seg["content"])
                segment_records.append({
                    "id": segment_id,
                    "index": seg["index"],
                    "content": seg["content"]
                })

            # 并行提取所有片段的角色和摘要
            print(f"[{task_id}]   并行提取角色和摘要...")
            extract_tasks = []
            for seg_record in segment_records:
                extract_tasks.append(
                    extract_segment_data(seg_record["content"], seg_record["id"], user_id, novel_id)
                )

            segment_results = await asyncio.gather(*extract_tasks, return_exceptions=True)

            # 收集结果
            chapter_characters = []
            for idx, result in enumerate(segment_results):
                if isinstance(result, Exception):
                    print(f"[{task_id}]   片段 {idx} 提取失败: {result}")
                    continue

                seg_id = segment_records[idx]["id"]
                characters = result.get("characters", [])
                summary = result.get("summary", "")

                # 更新片段摘要
                if summary:
                    db.update_segment_summary(seg_id, summary)

                # 收集角色
                chapter_characters.extend(characters)
                all_segments_characters.append(characters)

                print(f"[{task_id}]   片段 {idx}: 提取到 {len(characters)} 个角色")

            # 存储章节数据
            all_chapters_data.append({
                "chapter_id": chapter.chapter_id,
                "chapter_key": chapter_key,
                "title": chapter.title,
                "raw_content": chapter.content,
                "characters": chapter_characters,
                "segments": segment_records,
                "generated_scenes": None
            })

        # ==================== 阶段2: 合并角色卡 ====================
        db.update_task(
            task_id,
            status="merging_characters",
            progress=0.7,
            current_step="合并角色卡",
            message="正在合并所有片段的角色信息...",
        )
        print(f"[{task_id}] 合并角色卡...")

        # 合并所有片段的角色
        merged_characters = deepseek.merge_characters(all_segments_characters)
        print(f"[{task_id}] 合并后共 {len(merged_characters)} 个角色")

        # 存储合并后的角色
        db.create_characters(novel_id, merged_characters)

        # 关联角色到章节和片段
        for chapter_data in all_chapters_data:
            chapter_key = chapter_data["chapter_key"]

            # 找出本章节出现的角色
            chapter_char_names = set()
            for char in chapter_data["characters"]:
                chapter_char_names.add(char.get("name", ""))

            for merged_char in merged_characters:
                if merged_char.get("name") in chapter_char_names:
                    db.link_chapter_character(chapter_key, merged_char["id"])

                    # 关联到片段
                    for seg_record in chapter_data.get("segments", []):
                        seg_content = seg_record.get("content", "")
                        if merged_char.get("name", "") in seg_content:
                            db.link_segment_character(seg_record["id"], merged_char["id"])

        # ==================== 阶段3: 生成角色头像 ====================
        if image_client.is_configured():
            db.update_task(
                task_id,
                current_step="生成角色头像...",
                message="正在生成角色头像...",
            )
            print(f"[{task_id}] 开始生成角色头像...")
            await generate_character_avatars(novel_id, [{
                "chapter_id": ch["chapter_id"],
                "characters": merged_characters
            } for ch in all_chapters_data])

        # 构建返回结果
        result = {
            "novel_id": novel_id,
            "title": request.novel_title,
            "chapters": [{
                "chapter_id": ch["chapter_id"],
                "title": ch["title"],
                "raw_content": ch["raw_content"],
                "characters": [c for c in merged_characters if c.get("name") in [
                    cc.get("name") for cc in ch["characters"]
                ]],
                "generated_scenes": None
            } for ch in all_chapters_data]
        }

        db.update_task(
            task_id,
            status="completed",
            progress=1.0,
            message="角色解析完成",
            result=result,
        )
        print(f"[{task_id}] 角色解析完成，共 {len(all_chapters_data)} 章，{len(merged_characters)} 个角色")

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[{task_id}] 解析失败: {e}\n{error_detail}")
        db.update_task(
            task_id,
            status="failed",
            message=f"解析失败: {e}",
            error=str(e),
        )


async def extract_segment_data(segment_content: str, segment_id: str, user_id: str, novel_id: str) -> Dict[str, Any]:
    """并行提取片段的角色和摘要"""
    try:
        # 并行执行角色提取和摘要生成
        characters_task = deepseek.generate_character_cards(segment_content, user_id=user_id, novel_id=novel_id)
        summary_task = deepseek.generate_segment_summary(segment_content, user_id=user_id, novel_id=novel_id)

        characters, summary = await asyncio.gather(characters_task, summary_task)

        return {
            "segment_id": segment_id,
            "characters": characters or [],
            "summary": summary or ""
        }
    except Exception as e:
        print(f"片段 {segment_id} 提取失败: {e}")
        return {
            "segment_id": segment_id,
            "characters": [],
            "summary": ""
        }


# ============================================================
# API 2: 生成角色视角场景
# ============================================================
@app.post("/api/generate/{novel_id}/{chapter_index}/{character_id}")
async def start_generate_scenes(
    novel_id: str,
    chapter_index: int,
    character_id: str,
    request: Request,
):
    user = await login_required(get_current_user(request))

    # 检查novel存在且用户有权限
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    if novel_db["visibility"] == "private" and novel_db["owner_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问此小说")

    chapters = db.get_chapters_by_novel(novel_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="章节不存在")

    if chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter = chapters[chapter_index]

    chapter_char_ids = db.get_characters_for_chapter(chapter["id"])
    if character_id not in chapter_char_ids:
        all_chars = db.get_characters_by_novel(novel_id)
        if not any(c["id"] == character_id for c in all_chars):
            raise HTTPException(status_code=404, detail="角色不存在")

    task_id = str(uuid.uuid4())
    db.create_generate_task(task_id)

    def run_task():
        try:
            asyncio.run(run_generate_task(task_id, novel_id, chapter_index, character_id, user_id=user["id"]))
        except Exception as e:
            print(f"[Thread] 任务异常: {e}")
            import traceback
            traceback.print_exc()

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    return {
        "task_id": task_id,
        "status": "pending",
        "message": "开始生成场景..."
    }


async def run_generate_task(task_id: str, novel_id: str, chapter_index: int, character_id: str, user_id: str = None):
    """异步执行场景生成任务（支持片段模式）"""
    chapters = db.get_chapters_by_novel(novel_id)
    chapter = chapters[chapter_index]
    characters = db.get_characters_by_novel(novel_id)

    try:
        db.update_task(task_id, status="generating", progress=0.1, message="正在以角色视角生成场景...")
        char_name = get_character_name(characters, character_id)
        db.update_task(task_id, progress=0.15, message=f"正在以{char_name}视角生成场景...")
        print(f"[{task_id}] 正在以{char_name}视角生成场景...")

        # 获取章节的片段列表
        segments = db.get_segments_by_chapter(chapter["id"])

        if segments:
            # 使用片段模式生成（支持摘要传递）
            print(f"[{task_id}] 使用片段模式: {len(segments)} 个片段")
            segment_data = [
                {
                    "index": seg["segment_index"],
                    "content": seg["content"],
                    "summary": seg.get("summary", "")
                }
                for seg in segments
            ]

            generated = await deepseek.generate_scenes_from_perspective(
                chapter["raw_content"],
                characters,
                character_id,
                segments=segment_data,
                user_id=user_id,
                novel_id=novel_id,
            )
        else:
            # 无片段（旧数据），使用原始模式
            print(f"[{task_id}] 使用原始模式生成")
            generated = await deepseek.generate_scenes_from_perspective(
                chapter["raw_content"],
                characters,
                character_id,
                segments=None,
                user_id=user_id,
                novel_id=novel_id,
            )

        db.update_task(task_id, status="reviewing", progress=0.6, message="AI审阅中...")

        # AI审阅（最多3次）
        review_count = 0
        while review_count < 3:
            review_result = await deepseek.review_and_fix(
                generated,
                chapter["raw_content"],
                generated["player_character_name"],
                user_id=user_id,
                novel_id=novel_id,
            )

            if review_result["fixed"]:
                review_count += 1
                db.update_task(task_id, progress=0.6 + review_count * 0.1, message=f"AI审阅修复 {review_count}/3...")
                generated = review_result["data"]
            else:
                print(f"[{task_id}] 审阅通过")
                break

        # 持久化生成数据
        db.update_task(task_id, progress=0.9, message="保存结果...")
        run_id = str(uuid.uuid4())
        db.create_generated_run(
            run_id,
            chapter["id"],
            character_id,
            generated["player_character_name"],
            generated.get("scenes", []),
            generated.get("choices", []),
        )

        db.update_task(
            task_id,
            status="completed",
            progress=1.0,
            message="生成完成",
            result=generated,
        )
        print(f"[{task_id}] 场景生成完成")

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[{task_id}] 生成失败: {e}")
        db.update_task(
            task_id,
            status="failed",
            message=f"生成失败: {e}",
            error=str(e),
        )


def get_character_name(characters: List[dict], char_id: str) -> str:
    for c in characters:
        if c["id"] == char_id:
            return c["name"]
    return "未知"


# ============================================================
# 角色头像生成
# ============================================================
async def generate_character_avatars(novel_id: str, chapters_data: list):
    """并行生成所有角色的头像"""
    if not image_client.is_configured():
        return

    # 获取小说的艺术风格设置
    novel = db.get_novel(novel_id)
    art_style = novel.get("art_style", "anime") if novel else "anime"
    style_keywords = novel.get("style_keywords", "") if novel else ""

    seen_chars = {}
    for chapter in chapters_data:
        for char in chapter.get("characters", []):
            cid = char["id"]
            if cid not in seen_chars:
                seen_chars[cid] = char

    if not seen_chars:
        return

    print(f"开始为 {len(seen_chars)} 个角色生成头像... (风格: {art_style})")

    tasks = []
    for char in seen_chars.values():
        positive_prompt, negative_prompt = EvolinkImageClient.build_avatar_prompt(
            char, art_style, style_keywords
        )
        tasks.append(_generate_single_avatar(novel_id, char, positive_prompt, negative_prompt))

    await asyncio.gather(*tasks)
    print(f"角色头像生成完成")


import os


async def _generate_single_avatar(
    novel_id: str, char: dict, positive_prompt: str, negative_prompt: str
):
    """为单个角色生成头像并保存到本地"""
    char_name = char.get("name", "unknown")
    char_id = char["id"]
    print(f"  生成角色头像: {char_name}")

    url = await image_client.generate_image(positive_prompt, negative_prompt)
    if url:
        image_path = await download_and_save(url, novel_id, char_id)
        if image_path:
            db.update_character_image_path(char_id, os.path.relpath(image_path, os.path.dirname(__file__)))
            char["image_url"] = image_url_for_char(novel_id, char_id)
            print(f"    本地路径: {image_path}")
        else:
            char["image_url"] = url
    else:
        char["image_url"] = None

    # 记录图片生成 prompt 历史
    db.create_prompt_history(
        prompt_type="image_avatar",
        system_prompt=f"风格: {char.get('art_style', 'anime')}, 负面提示词: {negative_prompt[:100]}...",
        user_prompt=positive_prompt,
        ai_response=url,
        model="z-image-turbo",
        novel_id=novel_id,
        character_id=char_id,
    )


# ============================================================
# API 3: 获取任务状态
# ============================================================
@app.get("/api/parse/{task_id}/status")
async def get_parse_status(task_id: str):
    """获取解析/生成任务状态"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


# ============================================================
# API 3.1: 地点背景图生成/获取
# ============================================================
@app.get("/api/image/location/{novel_id}/{location}")
async def get_location_image(novel_id: str, location: str):
    """获取地点背景图，如果不存在则异步生成（不阻塞返回）"""
    # 先检查是否已存在
    existing = get_existing_location_image_url(novel_id, location)
    if existing:
        return {"url": existing, "cached": True}

    # 不存在则异步生成，先返回空URL让前端显示默认背景
    asyncio.create_task(_generate_location_background(novel_id, location))
    return {"url": None, "generating": True}


async def _generate_location_background(novel_id: str, location: str):
    """异步生成地点背景图"""
    if not image_client.is_configured():
        return

    # 获取小说的艺术风格设置
    novel = db.get_novel(novel_id)
    art_style = novel.get("art_style", "anime") if novel else "anime"
    style_keywords = novel.get("style_keywords", "") if novel else ""

    positive_prompt, negative_prompt = EvolinkImageClient.build_location_prompt(
        location, "", art_style, style_keywords
    )
    print(f"  生成地点背景图: {location} (风格: {art_style})")

    import hashlib
    loc_hash = hashlib.md5(location.encode()).hexdigest()[:12]

    url = await image_client.generate_image(positive_prompt, negative_prompt)
    if url:
        # 先下载到临时路径，再重命名为地点规范文件名
        local_path = await download_and_save(url, novel_id, f"loc_tmp_{loc_hash}")
        if local_path:
            target_path = get_location_image_path(novel_id, location)
            if local_path != target_path:
                try:
                    os.rename(local_path, target_path)
                except Exception:
                    pass
            print(f"    地点背景图保存成功: {os.path.basename(target_path)}")
        else:
            print("    地点背景图下载失败")
    else:
        print("    地点背景图生成失败")

    # 记录图片生成 prompt 历史
    db.create_prompt_history(
        prompt_type="image_location",
        system_prompt=f"风格: {art_style}",
        user_prompt=positive_prompt,
        ai_response=url,
        model="z-image-turbo",
        novel_id=novel_id,
        metadata=json.dumps({"location": location}, ensure_ascii=False),
    )



@app.get("/api/parse/{task_id}/result")
async def get_parse_result(task_id: str):
    """获取任务结果"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.get("status") == "failed":
        raise HTTPException(status_code=500, detail=task.get("error"))

    if task.get("status") != "completed":
        raise HTTPException(status_code=202, detail="任务尚未完成")

    return {
        "success": True,
        "result": task.get("result")
    }


# ============================================================
# API 4: 获取小说数据
# ============================================================
@app.get("/api/novel/{novel_id}")
async def get_novel(novel_id: str, request: Request):
    """获取小说数据（角色卡）— 需要权限检查"""
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 权限检查
    user = get_current_user(request)
    if novel_db["visibility"] == "private":
        if not user or (novel_db["owner_id"] != user["id"] and user.get("role") != "admin"):
            raise HTTPException(status_code=403, detail="无权访问此小说")

    chapters = db.get_chapters_by_novel(novel_id)
    characters = db.get_characters_by_novel(novel_id)

    chapters_data = []
    for ch in chapters:
        ch_chars = [c for c in characters
                    if c["id"] in db.get_characters_for_chapter(ch["id"])]

        for c in ch_chars:
            if c.get("image_path"):
                c["image_url"] = f"/api/images/{novel_id}_{c['id']}.jpg"

        runs = db.get_generated_runs_for_chapter(ch["id"])
        generated_scenes = None
        player_character_id = None
        generated_runs_meta = []
        if runs:
            run = runs[-1]
            generated_scenes = {
                "scenes": run["scenes_data"],
                "choices": run["choices_data"],
                "player_character_name": run["player_char_name"],
            }
            player_character_id = run["character_id"]
            # 返回所有 run 的元数据（不含完整场景数据）
            for r in runs:
                generated_runs_meta.append({
                    "run_id": r["id"],
                    "character_id": r["character_id"],
                    "player_char_name": r["player_char_name"],
                    "created_at": r["created_at"],
                })

        chapters_data.append({
            "chapter_id": ch["chapter_id"],
            "title": ch["title"],
            "raw_content": ch["raw_content"],
            "characters": ch_chars,
            "generated_scenes": generated_scenes,
            "player_character_id": player_character_id,
            "generated_runs": generated_runs_meta,
        })

    owner = db.get_user(novel_db["owner_id"])

    return {
        "novel_id": novel_id,
        "title": novel_db["title"],
        "owner_id": novel_db["owner_id"],
        "owner_name": owner["username"] if owner else "未知",
        "visibility": novel_db["visibility"],
        "created_at": novel_db["created_at"],
        "chapters": chapters_data,
    }


@app.get("/api/novel/{novel_id}/chapter/{chapter_index}")
async def get_chapter(novel_id: str, chapter_index: int, request: Request):
    chapters = db.get_chapters_by_novel(novel_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="小说不存在")

    if chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter = chapters[chapter_index]
    characters = db.get_characters_by_novel(novel_id)
    ch_chars = [c for c in characters
                if c["id"] in db.get_characters_for_chapter(chapter["id"])]

    for c in ch_chars:
        if c.get("image_path"):
            c["image_url"] = f"/api/images/{novel_id}_{c['id']}.jpg"

    return {
        "chapter_id": chapter["chapter_id"],
        "title": chapter["title"],
        "raw_content": chapter["raw_content"],
        "characters": ch_chars,
    }


@app.get("/api/novel/{novel_id}/chapter/{chapter_index}/segments")
async def get_chapter_segments(novel_id: str, chapter_index: int, request: Request):
    """获取章节的片段列表"""
    chapters = db.get_chapters_by_novel(novel_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="小说不存在")

    if chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter = chapters[chapter_index]
    segments = db.get_segments_by_chapter(chapter["id"])

    # 获取每个片段涉及的角色
    segments_data = []
    for seg in segments:
        char_ids = db.get_characters_for_segment(seg["id"])
        characters = db.get_characters_by_novel(novel_id)
        seg_chars = [c["name"] for c in characters if c["id"] in char_ids]

        segments_data.append({
            "id": seg["id"],
            "index": seg["segment_index"],
            "content_preview": seg["content"][:200] + "..." if len(seg["content"]) > 200 else seg["content"],
            "summary": seg.get("summary", ""),
            "char_count": len(seg["content"]),
            "characters": seg_chars,
        })

    return {
        "chapter_id": chapter["chapter_id"],
        "chapter_title": chapter["title"],
        "total_segments": len(segments),
        "segments": segments_data,
    }


# ============================================================
# API 5: 可见性切换
# ============================================================
@app.post("/api/novel/{novel_id}/visibility")
async def update_visibility(novel_id: str, request: Request):
    """切换小说可见性（Owner 或 Admin）"""
    user = await login_required(get_current_user(request))

    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    # Admin 可以修改任意小说，Owner 可以修改自己的
    if user["role"] != "admin" and novel_db["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权修改")

    new_vis = "private" if novel_db["visibility"] == "public" else "public"
    if user["role"] == "admin":
        db.update_novel_visibility(novel_id, new_vis)
    else:
        db.update_novel_visibility(novel_id, new_vis, owner_id=user["id"])

    return {"success": True, "visibility": new_vis}


# ============================================================
# API 6: 删除小说
# ============================================================
@app.delete("/api/novel/{novel_id}")
async def delete_novel(novel_id: str, request: Request):
    user = await login_required(get_current_user(request))
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    if user["role"] != "admin" and novel_db["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权删除")

    owner_id = user["id"] if user["role"] != "admin" else None
    db.delete_novel(novel_id, owner_id)
    return {"success": True, "message": "小说已删除"}


# ============================================================
# API 7: 获取单条生成记录
# ============================================================
@app.get("/api/generated-run/{run_id}")
async def get_generated_run(run_id: str):
    """获取单条生成记录的完整场景数据（用于缓存复用）"""
    import sqlite3
    conn = db._get_conn()
    row = conn.execute(
        "SELECT * FROM generated_runs WHERE id = ?", (run_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    d = dict(row)
    return {
        "run_id": d["id"],
        "character_id": d["character_id"],
        "player_char_name": d["player_char_name"],
        "scenes": json.loads(d["scenes_data"]),
        "choices": json.loads(d["choices_data"]),
        "created_at": d["created_at"],
    }


# ============================================================
# API 8: 保存/加载进度
# ============================================================
@app.post("/api/save-progress")
async def save_progress(novel_id: str, chapter_id: int, node_id: int, flags: dict, request: Request):
    """需要登录"""
    await login_required(get_current_user(request))
    db.save_progress(novel_id, chapter_id, node_id, flags)
    return {"success": True}


@app.get("/api/load-progress/{novel_id}")
async def load_progress(novel_id: str):
    save = db.load_progress(novel_id)
    if not save:
        return {"has_save": False}
    return {"has_save": True, "data": save}


# ============================================================
# Admin API
# ============================================================
@app.get("/api/admin/users")
async def admin_list_users(user: dict = Depends(admin_required)):
    users = db.get_all_users()
    return {"users": users}


@app.post("/api/admin/users/{user_id}/role")
async def admin_update_role(user_id: str, request: Request, user: dict = Depends(admin_required)):
    data = await request.json()
    new_role = data.get("role")
    if new_role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="无效的角色")
    db.update_user_role(user_id, new_role)
    return {"success": True, "message": f"用户 {user_id} 角色已更新为 {new_role}"}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, user: dict = Depends(admin_required)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    db.delete_user(user_id)
    return {"success": True, "message": "用户已删除"}


@app.get("/api/admin/novels")
async def admin_list_novels(user: dict = Depends(admin_required)):
    novels = db.get_all_novels(include_private=True)
    return {"novels": novels}


@app.get("/api/admin/stats")
async def admin_stats(user: dict = Depends(admin_required)):
    users = db.get_all_users()
    novels = db.get_all_novels(include_private=True)
    return {
        "total_users": len(users),
        "total_novels": len(novels),
        "public_novels": len([n for n in novels if n.get("visibility") == "public"]),
        "private_novels": len([n for n in novels if n.get("visibility") == "private"]),
    }


# ============================================================
# Admin Prompt History API
# ============================================================
@app.get("/api/admin/prompts")
async def admin_list_prompt_history(
    user: dict = Depends(admin_required),
    prompt_type: Optional[str] = None,
    novel_id: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    """分页查询 prompt 历史记录（admin 可见）"""
    offset = (page - 1) * limit
    records = db.list_prompt_history(
        offset=offset, limit=limit,
        prompt_type=prompt_type, novel_id=novel_id,
    )
    total = db.count_prompt_history(prompt_type=prompt_type, novel_id=novel_id)

    # 解析 self_eval
    for r in records:
        if r.get("self_eval"):
            try:
                r["self_eval"] = json.loads(r["self_eval"])
            except Exception:
                pass

    return {"records": records, "total": total, "page": page, "limit": limit}


@app.get("/api/admin/prompts/stats")
async def admin_prompt_stats(user: dict = Depends(admin_required)):
    """Prompt 统计（按类型分布、评分分布）"""
    conn = db._get_conn()

    # 按 prompt_type 分布
    type_rows = conn.execute(
        "SELECT prompt_type, COUNT(*) as cnt FROM prompt_history GROUP BY prompt_type"
    ).fetchall()
    type_dist = {r["prompt_type"]: r["cnt"] for r in type_rows}

    # self-eval 评分分布
    score_rows = conn.execute(
        """SELECT self_eval, COUNT(*) as cnt
           FROM prompt_history
           WHERE self_eval IS NOT NULL AND self_eval != ''
           GROUP BY self_eval"""
    ).fetchall()
    score_dist = []
    for r in score_rows:
        try:
            ev = json.loads(r["self_eval"])
            score = ev.get("score", 0)
            score_dist.append({"score": score, "count": r["cnt"], "suggestion": ev.get("suggestion", "")})
        except Exception:
            pass

    # 平均评分 by type
    avg_score_rows = conn.execute(
        """SELECT prompt_type, self_eval FROM prompt_history
           WHERE self_eval IS NOT NULL AND self_eval != ''"""
    ).fetchall()
    avg_by_type = {}
    for r in avg_score_rows:
        try:
            ev = json.loads(r["self_eval"])
            score = ev.get("score", 0)
            pt = r["prompt_type"]
            if pt not in avg_by_type:
                avg_by_type[pt] = {"total": 0, "count": 0}
            avg_by_type[pt]["total"] += score
            avg_by_type[pt]["count"] += 1
        except Exception:
            pass
    for pt in avg_by_type:
        avg_by_type[pt]["avg"] = round(avg_by_type[pt]["total"] / avg_by_type[pt]["count"], 2)

    conn.close()

    return {
        "type_distribution": type_dist,
        "score_distribution": score_dist,
        "avg_score_by_type": avg_by_type,
    }


@app.get("/api/admin/prompts/{record_id}")
async def admin_get_prompt_detail(record_id: int, user: dict = Depends(admin_required)):
    """获取单条 prompt 记录详情"""
    record = db.get_prompt_history_by_id(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if record.get("self_eval"):
        try:
            record["self_eval"] = json.loads(record["self_eval"])
        except Exception:
            pass
    return record


# ============================================================
# User Settings API (生成配置)
# ============================================================
@app.get("/api/settings")
async def get_user_settings_endpoint(request: Request):
    """获取当前用户的生成配置"""
    user = get_current_user(request)
    if not user:
        # 游客返回默认值
        return {"chunk_size": 5000, "chunk_overlap": 300, "max_total_chars": 25000}
    settings = db.get_user_settings(user["id"])
    settings["max_total_chars"] = settings.get("chunk_size", 5000) * 5  # 最多5段
    return settings


@app.post("/api/settings")
async def update_user_settings_endpoint(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
):
    """更新当前用户的生成配置"""
    user = await login_required(get_current_user(request))
    if not body:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    chunk_size = body.get("chunk_size")
    chunk_overlap = body.get("chunk_overlap")

    if chunk_size is not None and (not isinstance(chunk_size, int) or chunk_size < 2000 or chunk_size > 10000):
        raise HTTPException(status_code=400, detail="分段字数需在 2000-10000 之间")
    if chunk_overlap is not None and (not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap >= 1000):
        raise HTTPException(status_code=400, detail="重叠字数需在 0-999 之间")

    db.update_user_settings(user["id"], chunk_size, chunk_overlap)
    settings = db.get_user_settings(user["id"])
    settings["max_total_chars"] = settings.get("chunk_size", 5000) * 5
    return settings


# ============================================================
# 艺术风格 API
# ============================================================
@app.get("/api/art-styles")
async def get_art_styles():
    """获取支持的艺术风格列表"""
    return {
        "styles": image_client.get_supported_styles()
    }


@app.post("/api/novel/{novel_id}/art-style")
async def update_novel_art_style(novel_id: str, request: Request):
    """更新小说的艺术风格"""
    user = await login_required(get_current_user(request))

    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    # Admin 可以修改任意小说，Owner 可以修改自己的
    if user["role"] != "admin" and novel_db["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权修改")

    body = await request.json()
    art_style = body.get("art_style", "anime")
    style_keywords = body.get("style_keywords", "")

    if art_style not in ["anime", "realistic", "watercolor", "chinese_ink"]:
        raise HTTPException(status_code=400, detail="不支持的艺术风格")

    db.update_novel_art_style(novel_id, art_style, style_keywords)

    return {
        "success": True,
        "art_style": art_style,
        "style_keywords": style_keywords
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "deepseek_configured": deepseek.is_configured(),
        "image_generation_configured": image_client.is_configured(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
