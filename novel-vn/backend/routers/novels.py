"""
小说管理 API
"""
from fastapi import APIRouter, Request, HTTPException
from typing import Optional

from db import db
from auth import get_current_user, login_required

router = APIRouter(tags=["小说"])


@router.get("/api/novels")
async def list_novels(request: Request):
    """获取小说列表（游客：仅公开；登录用户：公开 + 自己的私有）"""
    user = get_current_user(request)
    novels = db.get_all_novels(include_private=bool(user and user.get("role") == "admin"))

    if user:
        user_novels = db.get_user_novels(user["id"])
        existing_ids = {n["id"] for n in novels}
        for n in user_novels:
            if n["id"] not in existing_ids:
                novels.append(n)
                existing_ids.add(n["id"])

    return {"novels": novels}


@router.get("/api/novel/{novel_id}")
async def get_novel(novel_id: str, request: Request):
    """获取小说数据（角色卡）"""
    import json

    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

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


@router.get("/api/novel/{novel_id}/events")
async def get_novel_events(novel_id: str, request: Request):
    """获取小说的所有事件"""
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    events = db.get_story_events_by_novel(novel_id)
    return {"events": events, "count": len(events)}


@router.get("/api/novel/{novel_id}/chapter/{chapter_index}")
async def get_chapter(novel_id: str, chapter_index: int, request: Request):
    """获取章节详情"""
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


@router.get("/api/novel/{novel_id}/chapter/{chapter_index}/segments")
async def get_chapter_segments(novel_id: str, chapter_index: int, request: Request):
    """获取章节的片段列表"""
    chapters = db.get_chapters_by_novel(novel_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="小说不存在")

    if chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter = chapters[chapter_index]
    segments = db.get_segments_by_chapter(chapter["id"])

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


@router.post("/api/novel/{novel_id}/visibility")
async def update_visibility(novel_id: str, request: Request):
    """切换小说可见性"""
    user = await login_required(get_current_user(request))

    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    if user["role"] != "admin" and novel_db["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权修改")

    new_vis = "private" if novel_db["visibility"] == "public" else "public"
    if user["role"] == "admin":
        db.update_novel_visibility(novel_id, new_vis)
    else:
        db.update_novel_visibility(novel_id, new_vis, owner_id=user["id"])

    return {"success": True, "visibility": new_vis}


@router.delete("/api/novel/{novel_id}")
async def delete_novel(novel_id: str, request: Request):
    """删除小说"""
    user = await login_required(get_current_user(request))
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    if user["role"] != "admin" and novel_db["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权删除")

    owner_id = user["id"] if user["role"] != "admin" else None
    db.delete_novel(novel_id, owner_id)
    return {"success": True, "message": "小说已删除"}
