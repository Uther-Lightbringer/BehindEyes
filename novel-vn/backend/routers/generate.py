"""
场景生成 API (v3.0 - 状态机驱动)
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
from image_storage import download_and_save, get_location_image_path, get_existing_location_image_url
from state_machine import EventExtractor, NodeBuilder
from knowledge_graph import KnowledgeGraphBuilder, HierarchicalSummaryTree

router = APIRouter(tags=["生成"])

# 初始化客户端
deepseek = DeepSeekClient(db=db)
image_client = EvolinkImageClient()
event_extractor = EventExtractor(deepseek)
node_builder = NodeBuilder(deepseek)

# 树生成任务缓存
pending_trees: Dict[str, Dict[str, Any]] = {}


# ==================== 请求模型 ====================

class ChapterData(BaseModel):
    chapter_id: int
    title: str
    content: str


class ParseRequest(BaseModel):
    """解析请求 - 统一使用状态机驱动"""
    novel_title: str
    chapters: List[ChapterData]
    visibility: Optional[str] = "public"
    art_style: Optional[str] = "anime"
    style_keywords: Optional[str] = ""
    enable_review: Optional[bool] = False
    enable_image_generation: Optional[bool] = False
    event_extraction_mode: Optional[str] = "auto"  # auto/manual/hybrid


class GenerateTreeRequest(BaseModel):
    generation_mode: Optional[str] = "pregenerate"


# ==================== 解析 API ====================

@router.post("/api/parse")
async def start_parse(request_body: ParseRequest, request: Request, background_tasks: BackgroundTasks):
    """
    解析小说 - 生成角色卡 + 事件 + 节点模板

    流程：
    1. 拆分章节片段
    2. 提取角色信息
    3. 合并角色卡
    4. 关联角色到章节
    5. 提取事件定义
    6. 生成角色头像（可选）
    """
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
            asyncio.run(_run_parse_task(task_id, request_body, novel_id, user["id"]))
        except Exception as e:
            import traceback
            traceback.print_exc()
            db.update_task(task_id, status="failed", error=str(e))

    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    return {"task_id": task_id, "novel_id": novel_id, "status": "pending"}


async def _run_parse_task(task_id: str, request: ParseRequest, novel_id: str, user_id: str):
    """解析任务执行"""
    settings = db.get_user_settings(user_id)
    chunk_size = settings.get("chunk_size", 5000)
    chunk_overlap = settings.get("chunk_overlap", 300)

    PARSE_STAGES = [
        {"id": "split_segments", "name": "拆分章节片段", "weight": 0.08},
        {"id": "extract_characters", "name": "提取角色信息", "weight": 0.2},
        {"id": "merge_characters", "name": "合并角色卡", "weight": 0.08},
        {"id": "link_characters", "name": "关联角色到章节", "weight": 0.04},
        {"id": "extract_events", "name": "提取事件定义", "weight": 0.15},
        {"id": "build_knowledge_graph", "name": "构建知识图谱", "weight": 0.15},
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
        # 阶段0: 拆分章节片段
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
                all_segments.append({
                    "id": segment_id, "chapter_key": chapter_key,
                    "content": seg["content"], "index": seg["index"]
                })

            update_stage_progress(0, (i + 1) / len(request.chapters))

        # 阶段1: 提取角色（并发控制）
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
        update_stage_progress(2, 1.0, f"已合并 {len(merged_characters)} 个角色")

        # 阶段3: 关联角色到章节
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
                segments=all_segments, characters=merged_characters,
                novel_id=novel_id, mode=request.event_extraction_mode
            )
            for event in events:
                db.create_story_event(event["id"], novel_id, event)
            update_stage_progress(4, 1.0, f"已提取 {len(events)} 个事件")
        else:
            update_stage_progress(4, 1.0, "跳过事件提取（手动模式）")

        # 阶段5: 构建知识图谱
        update_stage_progress(5, 0, "正在构建知识图谱...")
        try:
            kg_builder = KnowledgeGraphBuilder(llm_client=deepseek, db=db)
            chapters_data = [
                {
                    "chapter_id": ch.chapter_id,
                    "title": ch.title,
                    "content": ch.content
                }
                for ch in request.chapters
            ]

            def kg_progress_callback(step, total, message):
                kg_progress = step / total if total > 0 else 0
                update_stage_progress(5, kg_progress, message)

            kg_stats = await kg_builder.build_from_novel(
                novel_id=novel_id,
                chapters=chapters_data,
                characters=merged_characters,
                progress_callback=kg_progress_callback
            )

            # 构建层级摘要树
            summary_tree = HierarchicalSummaryTree(llm_client=deepseek, db=db)
            segments_with_summary = [
                {
                    "id": seg["id"],
                    "content": seg["content"],
                    "chapter_id": seg["chapter_key"],
                    "segment_index": seg["index"],
                    "summary": "",
                    "characters": []
                }
                for seg in all_segments
            ]
            await summary_tree.build_tree(
                novel_id=novel_id,
                segments=segments_with_summary,
                novel_title=request.novel_title
            )

            update_stage_progress(5, 1.0, f"知识图谱构建完成: {kg_stats}")
        except Exception as e:
            print(f"知识图谱构建失败: {e}")
            update_stage_progress(5, 1.0, f"知识图谱构建跳过: {e}")

        # 阶段6: 生成角色头像
        if request.enable_image_generation and image_client.is_configured():
            update_stage_progress(6, 0, "正在生成角色头像...")
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
                    except Exception as e:
                        print(f"生成头像失败: {e}")
                    return False

            results = await asyncio.gather(*[gen_avatar(c, semaphore) for c in merged_characters])
            update_stage_progress(6, 1.0, f"已生成 {sum(results)}/{len(merged_characters)} 个头像")
        else:
            update_stage_progress(6, 1.0, "跳过头像生成")

        # 获取最终数据
        final_characters = db.get_characters_by_novel(novel_id)
        final_chapters = db.get_chapters_by_novel(novel_id)

        # 构建返回数据
        chapters_with_chars = []
        for ch in final_chapters:
            chapter_char_ids = db.get_characters_for_chapter(ch["id"])
            chapter_chars = [c for c in final_characters if c["id"] in chapter_char_ids]
            chapters_with_chars.append({
                "id": ch["id"],
                "chapter_index": ch.get("chapter_id", 0),
                "title": ch.get("title", "未命名章节"),
                "characters": chapter_chars
            })

        db.update_task(
            task_id, status="completed", progress=1.0, current_step="完成",
            current_step_num=total_stages, total_steps=total_stages, message="解析完成",
            result={
                "novel_id": novel_id,
                "title": request.novel_title,
                "character_count": len(merged_characters),
                "chapters": chapters_with_chars,
                "characters": final_characters
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        db.update_task(task_id, status="failed", error=str(e))


# ==================== 任务状态 API ====================

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


# ==================== 兼容旧数据 API ====================

@router.get("/api/generated-run/{run_id}")
async def get_generated_run(run_id: str):
    """获取单条生成记录（兼容旧数据）"""
    conn = db._get_conn()
    row = conn.execute("SELECT * FROM generated_runs WHERE id = ?", (run_id,)).fetchone()
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
        "created_at": d["created_at"]
    }


# ==================== 地点背景图 API ====================

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

    positive_prompt, negative_prompt = EvolinkImageClient.build_location_prompt(
        location, "", art_style, style_keywords
    )
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


# ==================== 树生成 API ====================

@router.post("/api/novel/{novel_id}/generate-tree/{chapter_index}/{character_id}")
async def generate_tree_api(
    novel_id: str, chapter_index: int, character_id: str,
    request: Request, body: Optional[GenerateTreeRequest] = None
):
    """生成节点树结构（不含场景内容）"""
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


async def _generate_tree_task(
    task_id: str, novel_id: str, chapter: Dict, characters: List[Dict], player_char: Dict
):
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
    from knowledge_graph import DynamicContextManager

    db.update_task(task_id, status="generating", progress=0.0, message="正在生成场景内容...")

    nodes = tree_data["nodes"]
    characters = db.get_characters_by_novel(novel_id)
    player_char_id = tree_data.get("player_character_id")
    player_char = next((c for c in characters if c["id"] == player_char_id), characters[0] if characters else None)
    characters_map = {c["name"]: c for c in characters}

    # 初始化动态上下文管理器
    context_manager = DynamicContextManager(db=db, token_limit=2000)

    total = len(nodes)
    context = {}

    for i, node in enumerate(nodes):
        if node.get("needs_generation"):
            # 获取当前节点涉及的章节和角色
            chapter_index = 0
            if tree_data.get("chapter_id"):
                chapters = db.get_chapters_by_novel(novel_id)
                for idx, ch in enumerate(chapters):
                    if ch["id"] == tree_data["chapter_id"]:
                        chapter_index = idx
                        break

            # 加载知识图谱上下文
            involved_chars = node.get("characters_involved", [])
            kg_context = context_manager.load_context_for_scene(
                novel_id=novel_id,
                current_chapter=chapter_index,
                involved_characters=involved_chars
            )

            # 格式化上下文
            kg_context_text = context_manager.format_for_prompt(kg_context)

            # 传递知识图谱上下文到场景生成
            scene = await node_builder.generate_node_scene(
                node=node, player_character=player_char, context=context,
                characters_map=characters_map, knowledge_context=kg_context_text
            )
            db.update_story_node_scene(node["id"], scene)
            context = {
                "last_location": scene.get("location", ""),
                "last_characters": scene.get("characters", [])
            }

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

    return {
        "tree_id": tree_id,
        "tree_data": _build_tree_preview(tree_data["nodes"]),
        "node_count": len(tree_data["nodes"])
    }
