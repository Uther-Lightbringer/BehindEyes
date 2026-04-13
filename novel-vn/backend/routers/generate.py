"""
场景生成 API
"""
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import uuid
import threading
import os

from db import db
from auth import get_current_user, login_required
from deepseek_client import DeepSeekClient
from image_client import EvolinkImageClient
from image_storage import download_and_save, image_url_for_char, get_location_image_path, get_existing_location_image_url
from state_machine import EventExtractor, NodeBuilder

router = APIRouter(tags=["生成"])

# 初始化客户端
deepseek = DeepSeekClient(db=db)
image_client = EvolinkImageClient()
event_extractor = EventExtractor(deepseek)
node_builder = NodeBuilder(deepseek)

# 树生成任务缓存
pending_trees: Dict[str, Dict[str, Any]] = {}


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
    enable_review: Optional[bool] = True


class ParseRequestV02(BaseModel):
    novel_title: str
    chapters: List[ChapterData]
    visibility: Optional[str] = "public"
    art_style: Optional[str] = "anime"
    style_keywords: Optional[str] = ""
    enable_review: Optional[bool] = False
    enable_image_generation: Optional[bool] = False
    event_extraction_mode: Optional[str] = "auto"


class GenerateTreeRequest(BaseModel):
    generation_mode: Optional[str] = "pregenerate"


@router.post("/api/parse")
async def start_parse(request_body: ParseRequest, request: Request, background_tasks: BackgroundTasks):
    """发起异步解析任务，生成角色卡"""
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
        request_body.enable_review if request_body.enable_review is not None else True,
    )
    db.create_task(task_id, novel_id, request_body.novel_title, len(request_body.chapters))

    def run_task():
        try:
            asyncio.run(_run_parse_task(task_id, request_body, novel_id, user["id"]))
        except Exception as e:
            print(f"[{task_id}] 解析任务异常: {e}")
            import traceback
            traceback.print_exc()
            db.update_task(task_id, status="failed", message=f"解析异常: {e}", error=str(e))

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "pending", "message": "等待开始..."}


async def _run_parse_task(task_id: str, request: ParseRequest, novel_id: str, user_id: str):
    """异步执行角色卡解析任务"""
    from deepseek_client import generate_id
    from image_client import EvolinkImageClient

    settings = db.get_user_settings(user_id)
    chunk_size = settings.get("chunk_size", 5000)
    chunk_overlap = settings.get("chunk_overlap", 300)
    total_chapters = len(request.chapters)

    try:
        all_chapters_data = []
        all_segments_characters = []

        for i, chapter in enumerate(request.chapters):
            db.update_task(
                task_id, status="parsing_characters", progress=i / total_chapters,
                current_step=f"解析章节 {i + 1}/{total_chapters}",
                current_step_num=i + 1, message=f"正在解析章节 {i + 1}..."
            )

            chapter_key = str(uuid.uuid4())
            db.create_chapter(chapter_key, novel_id, chapter.chapter_id, chapter.title, chapter.content)

            segments_data = deepseek._chunk_content(chapter.content, chunk_size, chunk_overlap)

            segment_records = []
            for seg in segments_data:
                segment_id = str(uuid.uuid4())
                db.create_segment(segment_id, chapter_key, seg["index"], seg["content"])
                segment_records.append({"id": segment_id, "index": seg["index"], "content": seg["content"]})

            extract_tasks = []
            for seg_record in segment_records:
                extract_tasks.append(_extract_segment_data(seg_record["content"], seg_record["id"], user_id, novel_id))

            segment_results = await asyncio.gather(*extract_tasks, return_exceptions=True)

            chapter_characters = []
            for idx, result in enumerate(segment_results):
                if isinstance(result, Exception):
                    continue
                seg_id = segment_records[idx]["id"]
                characters = result.get("characters", [])
                context_data = result.get("context_data", {})
                if context_data:
                    db.update_segment_context(seg_id, context_data)
                chapter_characters.extend(characters)
                all_segments_characters.append(characters)

            all_chapters_data.append({
                "chapter_id": chapter.chapter_id, "chapter_key": chapter_key,
                "title": chapter.title, "raw_content": chapter.content,
                "characters": chapter_characters, "segments": segment_records
            })

        db.update_task(task_id, status="merging_characters", progress=0.7, current_step="合并角色卡")
        merged_characters = deepseek.merge_characters(all_segments_characters)
        db.create_characters(novel_id, merged_characters)

        for chapter_data in all_chapters_data:
            chapter_key = chapter_data["chapter_key"]
            chapter_char_names = set()
            for char in chapter_data["characters"]:
                chapter_char_names.add(char.get("name", ""))
            for merged_char in merged_characters:
                if merged_char.get("name") in chapter_char_names:
                    db.link_chapter_character(chapter_key, merged_char["id"])
                    for seg_record in chapter_data.get("segments", []):
                        if merged_char.get("name", "") in seg_record.get("content", ""):
                            db.link_segment_character(seg_record["id"], merged_char["id"])

        if image_client.is_configured():
            await _generate_character_avatars(novel_id, [{
                "chapter_id": ch["chapter_id"], "characters": merged_characters
            } for ch in all_chapters_data])

        result = {
            "novel_id": novel_id, "title": request.novel_title,
            "chapters": [{
                "chapter_id": ch["chapter_id"], "title": ch["title"],
                "raw_content": ch["raw_content"],
                "characters": [c for c in merged_characters if c.get("name") in [cc.get("name") for cc in ch["characters"]]],
                "generated_scenes": None
            } for ch in all_chapters_data]
        }

        db.update_task(task_id, status="completed", progress=1.0, message="角色解析完成", result=result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        db.update_task(task_id, status="failed", message=f"解析失败: {e}", error=str(e))


async def _extract_segment_data(segment_content: str, segment_id: str, user_id: str, novel_id: str) -> Dict[str, Any]:
    """并行提取片段的角色和结构化上下文"""
    try:
        characters_task = deepseek.generate_character_cards(segment_content, user_id=user_id, novel_id=novel_id)
        context_task = deepseek.generate_segment_summary(segment_content, user_id=user_id, novel_id=novel_id)
        characters, context_data = await asyncio.gather(characters_task, context_task)
        return {"segment_id": segment_id, "characters": characters or [], "context_data": context_data or {"summary": ""}}
    except Exception as e:
        return {"segment_id": segment_id, "characters": [], "context_data": {"summary": ""}}


async def _generate_character_avatars(novel_id: str, chapters_data: list):
    """并行生成所有角色的头像"""
    if not image_client.is_configured():
        return

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

    tasks = []
    for char in seen_chars.values():
        positive_prompt, negative_prompt = EvolinkImageClient.build_avatar_prompt(char, art_style, style_keywords)
        tasks.append(_generate_single_avatar(novel_id, char, positive_prompt, negative_prompt))

    await asyncio.gather(*tasks)


async def _generate_single_avatar(novel_id: str, char: dict, positive_prompt: str, negative_prompt: str):
    """为单个角色生成头像"""
    char_id = char["id"]
    url = await image_client.generate_image(positive_prompt, negative_prompt)
    if url:
        image_path = await download_and_save(url, novel_id, char_id)
        if image_path:
            db.update_character_image_path(char_id, os.path.relpath(image_path, os.path.dirname(__file__)))


@router.post("/api/generate/{novel_id}/{chapter_index}/{character_id}")
async def start_generate_scenes(novel_id: str, chapter_index: int, character_id: str, request: Request):
    """生成角色视角场景"""
    user = await login_required(get_current_user(request))

    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    if novel_db["visibility"] == "private" and novel_db["owner_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问此小说")

    chapters = db.get_chapters_by_novel(novel_id)
    if not chapters or chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter = chapters[chapter_index]
    characters = db.get_characters_by_novel(novel_id)

    task_id = str(uuid.uuid4())
    db.create_generate_task(task_id)

    def run_task():
        try:
            asyncio.run(_run_generate_task(task_id, novel_id, chapter_index, character_id, user_id=user["id"]))
        except Exception as e:
            import traceback
            traceback.print_exc()
            db.update_task(task_id, status="failed", error=str(e))

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "pending", "message": "开始生成场景..."}


async def _run_generate_task(task_id: str, novel_id: str, chapter_index: int, character_id: str, user_id: str = None):
    """异步执行场景生成任务"""
    chapters = db.get_chapters_by_novel(novel_id)
    chapter = chapters[chapter_index]
    characters = db.get_characters_by_novel(novel_id)

    db.update_task(task_id, status="generating", progress=0.1, message="正在以角色视角生成场景...")

    char_name = _get_character_name(characters, character_id)
    segments = db.get_segments_by_chapter(chapter["id"])

    if segments:
        segment_data = []
        for seg in segments:
            context_raw = seg.get("context_data", "{}")
            try:
                context_data = json.loads(context_raw) if isinstance(context_raw, str) else context_raw
            except:
                context_data = {"summary": seg.get("summary", "")}
            segment_data.append({"index": seg["segment_index"], "content": seg["content"], "context": context_data})

        generated = await deepseek.generate_scenes_from_perspective(
            chapter["raw_content"], characters, character_id, segments=segment_data, user_id=user_id, novel_id=novel_id
        )
    else:
        generated = await deepseek.generate_scenes_from_perspective(
            chapter["raw_content"], characters, character_id, segments=None, user_id=user_id, novel_id=novel_id
        )

    db.update_task(task_id, status="reviewing", progress=0.6, message="AI审阅中...")

    novel_db = db.get_novel(novel_id)
    enable_review = novel_db.get("enable_review", 1) if novel_db else 1

    if enable_review:
        review_count = 0
        while review_count < 3:
            review_result = await deepseek.review_and_fix(
                generated, chapter["raw_content"], generated["player_character_name"], user_id=user_id, novel_id=novel_id
            )
            if review_result["fixed"]:
                review_count += 1
                generated = review_result["data"]
            else:
                break

    run_id = str(uuid.uuid4())
    db.create_generated_run(
        run_id, chapter["id"], character_id, generated["player_character_name"],
        generated.get("scenes", []), generated.get("choices", [])
    )

    db.update_task(task_id, status="completed", progress=1.0, message="生成完成", result=generated)


def _get_character_name(characters: List[dict], char_id: str) -> str:
    for c in characters:
        if c["id"] == char_id:
            return c["name"]
    return "未知"


@router.get("/api/parse/{task_id}/status")
async def get_parse_status(task_id: str):
    """获取解析/生成任务状态"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/api/parse/{task_id}/result")
async def get_parse_result(task_id: str):
    """获取任务结果"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("status") == "failed":
        raise HTTPException(status_code=500, detail=task.get("error"))
    if task.get("status") != "completed":
        raise HTTPException(status_code=202, detail="任务尚未完成")
    return {"success": True, "result": task.get("result")}


@router.get("/api/generated-run/{run_id}")
async def get_generated_run(run_id: str):
    """获取单条生成记录"""
    import sqlite3
    conn = db._get_conn()
    row = conn.execute("SELECT * FROM generated_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="生成记录不存在")
    d = dict(row)
    return {
        "run_id": d["id"], "character_id": d["character_id"],
        "player_char_name": d["player_char_name"],
        "scenes": json.loads(d["scenes_data"]), "choices": json.loads(d["choices_data"]),
        "created_at": d["created_at"]
    }


# ========== 地点背景图 ==========

@router.get("/api/image/location/{novel_id}/{location}")
async def get_location_image(novel_id: str, location: str):
    """获取地点背景图"""
    existing = get_existing_location_image_url(novel_id, location)
    if existing:
        return {"url": existing, "cached": True}
    asyncio.create_task(_generate_location_background(novel_id, location))
    return {"url": None, "generating": True}


async def _generate_location_background(novel_id: str, location: str):
    """异步生成地点背景图"""
    import hashlib
    if not image_client.is_configured():
        return

    novel = db.get_novel(novel_id)
    art_style = novel.get("art_style", "anime") if novel else "anime"
    style_keywords = novel.get("style_keywords", "") if novel else ""

    positive_prompt, negative_prompt = EvolinkImageClient.build_location_prompt(location, "", art_style, style_keywords)
    loc_hash = hashlib.md5(location.encode()).hexdigest()[:12]

    url = await image_client.generate_image(positive_prompt, negative_prompt)
    if url:
        local_path = await download_and_save(url, novel_id, f"loc_tmp_{loc_hash}")
        if local_path:
            target_path = get_location_image_path(novel_id, location)
            if local_path != target_path:
                try:
                    os.rename(local_path, target_path)
                except:
                    pass


# ========== v0.2 解析 API ==========

@router.post("/api/parse-v2")
async def start_parse_v2(request_body: ParseRequestV02, request: Request, background_tasks: BackgroundTasks):
    """v0.2 版本解析，生成角色卡 + 事件 + 节点模板"""
    user = await login_required(get_current_user(request))

    task_id = str(uuid.uuid4())
    novel_id = str(uuid.uuid4())

    db.create_novel(
        novel_id, request_body.novel_title, user["id"],
        request_body.visibility or "public", request_body.art_style or "anime",
        request_body.style_keywords or "",
        request_body.enable_review if request_body.enable_review is not None else True
    )
    db.update_novel_mode_settings(novel_id, event_extraction_mode=request_body.event_extraction_mode or "auto")
    db.create_task(task_id, novel_id, request_body.novel_title, len(request_body.chapters))

    def run_task():
        try:
            asyncio.run(_run_parse_task_v2(task_id, request_body, novel_id, user["id"]))
        except Exception as e:
            import traceback
            traceback.print_exc()
            db.update_task(task_id, status="failed", error=str(e))

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    return {"task_id": task_id, "novel_id": novel_id, "status": "pending"}


async def _run_parse_task_v2(task_id: str, request: ParseRequestV02, novel_id: str, user_id: str):
    """v0.2 解析任务"""
    from datetime import datetime

    settings = db.get_user_settings(user_id)
    chunk_size = settings.get("chunk_size", 5000)
    chunk_overlap = settings.get("chunk_overlap", 300)

    PARSE_STAGES = [
        {"id": "split_segments", "name": "拆分章节片段", "weight": 0.1},
        {"id": "extract_characters", "name": "提取角色信息", "weight": 0.25},
        {"id": "merge_characters", "name": "合并角色卡", "weight": 0.1},
        {"id": "link_characters", "name": "关联角色到章节", "weight": 0.05},
        {"id": "extract_events", "name": "提取事件定义", "weight": 0.2},
        {"id": "generate_avatars", "name": "生成角色头像", "weight": 0.3},
    ]
    total_stages = len(PARSE_STAGES)

    def update_stage_progress(stage_index, stage_progress=0, message=None):
        total_weight = sum(s["weight"] for s in PARSE_STAGES[:stage_index])
        current_weight = PARSE_STAGES[stage_index]["weight"] * stage_progress
        progress = total_weight + current_weight
        stage_name = PARSE_STAGES[stage_index]["name"]
        db.update_task(
            task_id, progress=progress, current_step=stage_name,
            current_step_num=stage_index + 1, total_steps=total_stages, message=message or f"正在{stage_name}..."
        )

    try:
        # 阶段0: 拆分
        update_stage_progress(0, 0, "正在拆分章节...")
        all_characters = []
        all_segments = []

        for i, chapter in enumerate(request.chapters):
            chapter_key = str(uuid.uuid4())
            db.create_chapter(chapter_key, novel_id, chapter.chapter_id, chapter.title, chapter.content)
            segments_data = deepseek._chunk_content(chapter.content, chunk_size, chunk_overlap)

            for seg in segments_data:
                segment_id = str(uuid.uuid4())
                db.create_segment(segment_id, chapter_key, seg["index"], seg["content"])
                all_segments.append({"id": segment_id, "chapter_key": chapter_key, "content": seg["content"], "index": seg["index"]})

            update_stage_progress(0, (i + 1) / len(request.chapters))

        # 阶段1: 提取角色
        update_stage_progress(1, 0, "正在提取角色信息...")
        semaphore = asyncio.Semaphore(5)

        async def extract_chars_with_limit(seg, sem):
            async with sem:
                return await deepseek.generate_character_cards(seg["content"], user_id=user_id, novel_id=novel_id)

        tasks = [extract_chars_with_limit(seg, semaphore) for seg in all_segments]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if not isinstance(r, Exception):
                all_characters.extend(r)
        update_stage_progress(1, 1.0)

        # 阶段2: 合并角色
        update_stage_progress(2, 0, "正在合并角色卡...")
        merged_characters = deepseek.merge_characters([all_characters])
        db.create_characters(novel_id, merged_characters)
        update_stage_progress(2, 1.0)

        # 阶段3: 关联角色
        update_stage_progress(3, 0, "正在关联角色到章节...")
        chapters = db.get_chapters_by_novel(novel_id)
        for chapter_idx, chapter in enumerate(request.chapters):
            if chapter_idx < len(chapters):
                ch = chapters[chapter_idx]
                for seg in all_segments:
                    if seg["chapter_key"] == ch["id"]:
                        for char in merged_characters:
                            if char.get("name", "") in seg["content"]:
                                db.link_segment_character(seg["id"], char["id"])
            update_stage_progress(3, (chapter_idx + 1) / len(request.chapters))

        # 阶段4: 事件提取
        if request.event_extraction_mode != "manual":
            update_stage_progress(4, 0, "正在提取事件定义...")
            events = await event_extractor.extract_events_from_segments(
                segments=all_segments, characters=merged_characters, novel_id=novel_id, mode=request.event_extraction_mode
            )
            for event in events:
                db.create_story_event(event["id"], novel_id, event)
            update_stage_progress(4, 1.0)
        else:
            update_stage_progress(4, 1.0, "跳过事件提取")

        # 阶段5: 头像生成
        if request.enable_image_generation and image_client.is_configured():
            update_stage_progress(5, 0, "正在生成角色头像...")
            semaphore = asyncio.Semaphore(5)

            async def gen_avatar(char, sem):
                async with sem:
                    try:
                        positive_prompt, negative_prompt = EvolinkImageClient.build_avatar_prompt(
                            char, request.art_style or "anime", request.style_keywords or ""
                        )
                        url = await image_client.generate_image(positive_prompt, negative_prompt)
                        if url:
                            path = await download_and_save(url, novel_id, char["id"])
                            if path:
                                db.update_character_image_path(char["id"], os.path.relpath(path, os.path.dirname(__file__)))
                                return True
                    except:
                        pass
                    return False

            results = await asyncio.gather(*[gen_avatar(c, semaphore) for c in merged_characters])
            update_stage_progress(5, 1.0, f"已生成 {sum(results)} 个头像")
        else:
            update_stage_progress(5, 1.0, "跳过头像生成")

        final_characters = db.get_characters_by_novel(novel_id)
        db.update_task(
            task_id, status="completed", progress=1.0, current_step="完成",
            current_step_num=total_stages, total_steps=total_stages, message="解析完成",
            result={"novel_id": novel_id, "title": request.novel_title, "character_count": len(merged_characters), "characters": final_characters}
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        db.update_task(task_id, status="failed", error=str(e))


# ========== 树生成 API ==========

@router.post("/api/novel/{novel_id}/generate-tree/{chapter_index}/{character_id}")
async def generate_tree_api(novel_id: str, chapter_index: int, character_id: str, request: Request, body: Optional[GenerateTreeRequest] = None):
    """生成节点树结构"""
    user = await login_required(get_current_user(request))

    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapters = db.get_chapters_by_novel(novel_id)
    if chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter = chapters[chapter_index]
    characters = db.get_characters_by_novel(novel_id)
    player_char = next((c for c in characters if c["id"] == character_id), None)
    if not player_char:
        raise HTTPException(status_code=404, detail="角色不存在")

    task_id = str(uuid.uuid4())
    db.create_generate_task(task_id)

    def run_task():
        try:
            asyncio.run(_generate_tree_task(task_id, novel_id, chapter, characters, player_char))
        except Exception as e:
            import traceback
            traceback.print_exc()
            db.update_task(task_id, status="failed", error=str(e))

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "pending"}


async def _generate_tree_task(task_id: str, novel_id: str, chapter: Dict, characters: List[Dict], player_char: Dict):
    """生成节点树任务"""
    from datetime import datetime

    db.update_task(task_id, status="generating", progress=0.1, message="正在生成剧情树结构...")

    segments = db.get_segments_by_chapter(chapter["id"])
    nodes = await node_builder.build_tree_from_segments(
        segments=segments if segments else [{"content": chapter["raw_content"], "index": 0}],
        novel_id=novel_id, player_character=player_char, all_characters=characters
    )

    if not nodes:
        db.update_task(task_id, status="failed", error="AI 未返回有效节点")
        return

    db.delete_story_nodes_by_novel(novel_id)

    for node in nodes:
        db.create_story_node(
            node_pk=node["id"], novel_id=novel_id, node_id=node["node_id"],
            route=node.get("route", "main"), parent_node=node.get("parent_node"),
            scene_data=None, possible_events=node.get("possible_events", []),
            choices=node.get("choices", []), auto_next=node.get("auto_next"),
            prerequisites=node.get("prerequisites", {}), needs_generation=True,
            generation_hint=node.get("scene_preview", "")
        )

    events = db.get_story_events_by_novel(novel_id)
    for node in nodes:
        node_events = _match_events_to_node(node, events)
        if node_events:
            db.update_story_node_events(node["id"], node_events)

    tree_data = _build_tree_preview(nodes)
    tree_id = str(uuid.uuid4())
    pending_trees[tree_id] = {
        "novel_id": novel_id, "chapter_id": chapter["id"], "nodes": nodes,
        "player_character_id": player_char["id"], "created_at": datetime.utcnow().isoformat()
    }

    db.update_task(
        task_id, status="completed", progress=1.0, message="树结构生成完成",
        result={"tree_id": tree_id, "node_count": len(nodes), "tree_data": tree_data}
    )


def _match_events_to_node(node: Dict, events: List[Dict]) -> List[str]:
    matched = []
    chars_involved = set(node.get("characters_involved", []))
    for event in events:
        conditions = event.get("trigger_conditions", {})
        if isinstance(conditions, str):
            conditions = json.loads(conditions)
        event_chars = set(conditions.get("characters_involved", []))
        if chars_involved & event_chars:
            matched.append(event["id"])
    return matched


def _build_tree_preview(nodes: List[Dict]) -> Dict:
    if not nodes:
        return {"root": None}

    node_map = {n["node_id"]: n for n in nodes}

    def build_subtree(node_id: str, depth: int = 0) -> Dict:
        if depth > 20 or node_id not in node_map:
            return None
        node = node_map[node_id]
        choices = json.loads(node.get("choices", "[]")) if isinstance(node.get("choices"), str) else node.get("choices", [])
        tree_node = {
            "node_id": node_id, "route": node.get("route", "main"),
            "preview": node.get("generation_hint", node.get("scene_preview", "")),
            "characters": node.get("characters_involved", []),
            "needs_generation": node.get("needs_generation", True), "choices": []
        }
        for choice in choices:
            choice_node = {"prompt": choice.get("prompt", ""), "options": []}
            for opt in choice.get("options", []):
                opt_node = {"text": opt.get("text", ""), "route": opt.get("route", "main"), "effects": opt.get("effects", {})}
                next_node = opt.get("next_node")
                if next_node and next_node in node_map:
                    opt_node["child"] = build_subtree(next_node, depth + 1)
                choice_node["options"].append(opt_node)
            tree_node["choices"].append(choice_node)
        return tree_node

    return {"root": build_subtree(nodes[0]["node_id"]) if nodes else None}


@router.post("/api/novel/{novel_id}/confirm-tree/{tree_id}")
async def confirm_tree_api(novel_id: str, tree_id: str, request: Request):
    """确认树结构，开始生成场景内容"""
    user = await login_required(get_current_user(request))

    if tree_id not in pending_trees:
        raise HTTPException(status_code=404, detail="树结构不存在或已过期")

    tree_data = pending_trees[tree_id]
    if tree_data["novel_id"] != novel_id:
        raise HTTPException(status_code=400, detail="树结构与小说不匹配")

    task_id = str(uuid.uuid4())
    db.create_generate_task(task_id)

    def run_task():
        try:
            asyncio.run(_generate_all_scenes_task(task_id, novel_id, tree_data))
        except Exception as e:
            import traceback
            traceback.print_exc()
            db.update_task(task_id, status="failed", error=str(e))

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    del pending_trees[tree_id]
    return {"task_id": task_id, "status": "pending"}


async def _generate_all_scenes_task(task_id: str, novel_id: str, tree_data: Dict):
    """为所有节点生成场景内容"""
    db.update_task(task_id, status="generating", progress=0.0, message="正在生成场景内容...")

    nodes = tree_data["nodes"]
    characters = db.get_characters_by_novel(novel_id)
    player_char_id = tree_data.get("player_character_id")
    player_char = next((c for c in characters if c["id"] == player_char_id), characters[0] if characters else None)
    characters_map = {c["name"]: c for c in characters}

    total = len(nodes)
    context = {}

    for i, node in enumerate(nodes):
        if node.get("needs_generation"):
            scene = await node_builder.generate_node_scene(node=node, player_character=player_char, context=context, characters_map=characters_map)
            db.update_story_node_scene(node["id"], scene)
            context = {"last_location": scene.get("location", ""), "last_characters": scene.get("characters", [])}

        db.update_task(task_id, progress=(i + 1) / total, message=f"生成场景 {i+1}/{total}...")

    db.update_task(task_id, status="completed", progress=1.0, message="场景生成完成", result={"node_count": total})


@router.post("/api/novel/{novel_id}/reject-tree/{tree_id}")
async def reject_tree_api(novel_id: str, tree_id: str, request: Request):
    """拒绝树结构"""
    user = await login_required(get_current_user(request))

    if tree_id not in pending_trees:
        raise HTTPException(status_code=404, detail="树结构不存在或已过期")

    tree_data = pending_trees[tree_id]
    for node in tree_data.get("nodes", []):
        try:
            db.delete_story_node(node["id"])
        except:
            pass

    del pending_trees[tree_id]
    return {"success": True, "message": "已删除"}


@router.get("/api/novel/{novel_id}/tree-preview/{tree_id}")
async def get_tree_preview_api(novel_id: str, tree_id: str, request: Request):
    """获取树预览数据"""
    if tree_id not in pending_trees:
        raise HTTPException(status_code=404, detail="树结构不存在或已过期")

    tree_data = pending_trees[tree_id]
    if tree_data["novel_id"] != novel_id:
        raise HTTPException(status_code=400, detail="树结构与小说不匹配")

    return {"tree_id": tree_id, "tree_data": _build_tree_preview(tree_data["nodes"]), "node_count": len(tree_data["nodes"])}
