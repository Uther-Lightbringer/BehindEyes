"""
小说管理 API
"""
from fastapi import APIRouter, Request, HTTPException
from typing import Optional, List

from db import db
from auth import get_current_user, login_required
from knowledge_graph import DynamicContextManager

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


# ==================== 知识图谱 API ====================

@router.get("/api/novel/{novel_id}/knowledge-graph/relations")
async def get_character_relations(novel_id: str, request: Request, character: Optional[str] = None):
    """
    获取角色关系网络

    Args:
        novel_id: 小说 ID
        character: 可选，指定角色名称，只返回与该角色相关的关系
    """
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    user = get_current_user(request)
    if novel_db["visibility"] == "private":
        if not user or (novel_db["owner_id"] != user["id"] and user.get("role") != "admin"):
            raise HTTPException(status_code=403, detail="无权访问此小说")

    relations = db.get_character_relations(novel_id, character)

    # 构建关系图数据（用于前端可视化）
    nodes = set()
    edges = []

    for rel in relations:
        nodes.add(rel["char_a"])
        nodes.add(rel["char_b"])
        edges.append({
            "source": rel["char_a"],
            "target": rel["char_b"],
            "type": rel["relation_type"],
            "affection": rel["current_affection"],
            "source_chapter": rel.get("source_chapter")
        })

    return {
        "novel_id": novel_id,
        "nodes": [{"id": n, "name": n} for n in nodes],
        "edges": edges,
        "total_relations": len(relations)
    }


@router.get("/api/novel/{novel_id}/knowledge-graph/summary")
async def get_summary_tree(novel_id: str, request: Request, level: Optional[str] = None):
    """
    获取层级摘要树

    Args:
        novel_id: 小说 ID
        level: 可选，筛选层级 (novel/volume/chapter/section/segment)
    """
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    user = get_current_user(request)
    if novel_db["visibility"] == "private":
        if not user or (novel_db["owner_id"] != user["id"] and user.get("role") != "admin"):
            raise HTTPException(status_code=403, detail="无权访问此小说")

    summaries = db.get_summary_tree_by_novel(novel_id, level)

    # 构建树形结构
    tree = _build_summary_tree(summaries)

    return {
        "novel_id": novel_id,
        "summaries": summaries,
        "tree": tree,
        "total_nodes": len(summaries)
    }


def _build_summary_tree(summaries: List[dict]) -> dict:
    """构建摘要树形结构"""
    if not summaries:
        return {"root": None}

    # 按层级分组
    by_level = {}
    for s in summaries:
        level = s.get("level", "segment")
        if level not in by_level:
            by_level[level] = []
        by_level[level].append(s)

    # 找到根节点（novel 级别）
    novel_summaries = by_level.get("novel", [])
    if not novel_summaries:
        # 如果没有 novel 级别，使用第一个 chapter 级别
        novel_summaries = by_level.get("chapter", [])[:1]

    if not novel_summaries:
        return {"root": None}

    root = novel_summaries[0]

    # 递归构建子树
    def build_children(parent_id: str, target_level: str):
        children = []
        for s in summaries:
            if s.get("parent_id") == parent_id:
                child = {
                    "id": s["id"],
                    "level": s["level"],
                    "summary": s.get("summary", ""),
                    "key_characters": s.get("key_characters", []),
                    "key_events": s.get("key_events", []),
                    "children": build_children(s["id"], _get_child_level(s["level"]))
                }
                children.append(child)
        return children

    return {
        "root": {
            "id": root["id"],
            "level": root["level"],
            "summary": root.get("summary", ""),
            "key_characters": root.get("key_characters", []),
            "key_events": root.get("key_events", []),
            "children": build_children(root["id"], _get_child_level(root["level"]))
        }
    }


def _get_child_level(level: str) -> str:
    """获取子层级"""
    level_order = ["novel", "volume", "chapter", "section", "segment"]
    try:
        idx = level_order.index(level)
        if idx < len(level_order) - 1:
            return level_order[idx + 1]
    except ValueError:
        pass
    return ""


@router.get("/api/novel/{novel_id}/knowledge-graph/world-settings")
async def get_world_settings(novel_id: str, request: Request, category: Optional[str] = None):
    """
    获取世界设定

    Args:
        novel_id: 小说 ID
        category: 可选，筛选类别 (location/item/concept/ability)
    """
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    user = get_current_user(request)
    if novel_db["visibility"] == "private":
        if not user or (novel_db["owner_id"] != user["id"] and user.get("role") != "admin"):
            raise HTTPException(status_code=403, detail="无权访问此小说")

    settings = db.get_world_settings_by_novel(novel_id, category)

    # 按类别分组
    by_category = {}
    for s in settings:
        cat = s.get("category", "other")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(s)

    return {
        "novel_id": novel_id,
        "settings": settings,
        "by_category": by_category,
        "total_settings": len(settings)
    }


@router.get("/api/novel/{novel_id}/knowledge-graph/context")
async def get_knowledge_context(
    novel_id: str,
    request: Request,
    chapter: int = 0,
    segment: int = 0,
    characters: Optional[str] = None
):
    """
    获取动态知识上下文（用于预览 AI 将收到的上下文）

    Args:
        novel_id: 小说 ID
        chapter: 当前章节编号
        segment: 当前片段编号
        characters: 逗号分隔的角色名称列表
    """
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    user = get_current_user(request)
    if novel_db["visibility"] == "private":
        if not user or (novel_db["owner_id"] != user["id"] and user.get("role") != "admin"):
            raise HTTPException(status_code=403, detail="无权访问此小说")

    # 解析角色列表
    char_list = []
    if characters:
        char_list = [c.strip() for c in characters.split(",") if c.strip()]

    # 使用动态上下文管理器
    context_manager = DynamicContextManager(db=db, token_limit=2000)
    context = context_manager.load_context_for_scene(
        novel_id=novel_id,
        current_chapter=chapter,
        current_segment=segment,
        involved_characters=char_list
    )

    # 返回格式化的上下文
    return {
        "novel_id": novel_id,
        "chapter": chapter,
        "segment": segment,
        "characters": char_list,
        "context": {
            "related_characters": context.related_characters[:5],
            "character_relations": [r.to_dict() for r in context.character_relations[:5]],
            "related_events": context.related_events[:3],
            "world_settings": [s.to_dict() for s in context.world_settings[:5]],
            "parent_summaries": context.parent_summaries[:2],
            "keywords": context.keywords[:10],
            "estimated_tokens": context.estimate_tokens()
        },
        "formatted": context_manager.format_for_prompt(context)
    }


@router.get("/api/novel/{novel_id}/knowledge-graph/event-chains")
async def get_event_chains(novel_id: str, request: Request):
    """获取事件因果链"""
    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    user = get_current_user(request)
    if novel_db["visibility"] == "private":
        if not user or (novel_db["owner_id"] != user["id"] and user.get("role") != "admin"):
            raise HTTPException(status_code=403, detail="无权访问此小说")

    chains = db.get_event_chains_by_novel(novel_id)

    return {
        "novel_id": novel_id,
        "chains": chains,
        "total_chains": len(chains)
    }
