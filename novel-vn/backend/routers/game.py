"""
游戏引擎 API
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import json

from db import db
from auth import get_current_user, login_required
from state_machine import GameStateManager, EventManager, NodeNavigator, SaveManager

router = APIRouter(tags=["游戏"])

# 初始化管理器
state_manager = GameStateManager()
event_manager = EventManager(state_manager)
node_navigator = NodeNavigator(state_manager, event_manager)
save_manager = SaveManager(state_manager)


class StartGameRequest(BaseModel):
    novel_id: str
    chapter_index: Optional[int] = 0
    character_id: str


class ChooseRequest(BaseModel):
    choice_id: str
    option_index: int


class NavigateRequest(BaseModel):
    node_id: str


class SaveRequest(BaseModel):
    game_state_id: str
    save_name: Optional[str] = "存档"
    save_slot: Optional[int] = 0
    play_time: Optional[int] = 0


@router.post("/api/game/start")
async def start_game_api(request: Request):
    """开始游戏 - 创建 GameState 并返回起始节点"""
    user = await login_required(get_current_user(request))
    body = await request.json()

    novel_id = body.get("novel_id")
    chapter_index = body.get("chapter_index", 0)
    character_id = body.get("character_id")

    if not all([novel_id, character_id]):
        raise HTTPException(status_code=400, detail="缺少参数")

    nodes = db.get_story_nodes_by_novel(novel_id)
    if not nodes:
        raise HTTPException(status_code=404, detail="节点数据不存在，请先生成")

    start_node = nodes[0]

    state = state_manager.create_state(
        novel_id=novel_id, user_id=user["id"], character_id=character_id, initial_node=start_node["node_id"]
    )

    choices = json.loads(start_node.get("choices", "[]")) if isinstance(start_node.get("choices"), str) else start_node.get("choices", [])

    return {
        "state_id": state.id,
        "current_node": {
            "node_id": start_node["node_id"],
            "scene_data": start_node.get("scene_data"),
            "choices": choices
        },
        "state": state.to_dict()
    }


@router.get("/api/game/{state_id}/node")
async def get_current_node_api(state_id: str, request: Request):
    """获取当前节点和可用选择"""
    user = get_current_user(request)
    state = state_manager.get_state(state_id)

    if not state:
        raise HTTPException(status_code=404, detail="游戏状态不存在")

    if user and state.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问")

    node = db.get_story_node_by_node_id(state.novel_id, state.current_node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    triggered_events = event_manager.check_and_trigger_events(state, state.current_node_id)
    choices = json.loads(node.get("choices", "[]")) if isinstance(node.get("choices"), str) else node.get("choices", [])

    return {
        "node": {
            "node_id": node["node_id"],
            "route": node.get("route", "main"),
            "scene_data": node.get("scene_data"),
            "choices": choices
        },
        "state": state.to_dict(),
        "triggered_events": [{"id": e[0].id, "name": e[0].name} for e in triggered_events] if triggered_events else []
    }


@router.post("/api/game/{state_id}/navigate")
async def navigate_to_node_api(state_id: str, request: Request, body: NavigateRequest):
    """直接导航到指定节点"""
    user = await login_required(get_current_user(request))

    state = state_manager.get_state(state_id)
    if not state:
        raise HTTPException(status_code=404, detail="游戏状态不存在")

    if state.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权操作")

    try:
        state.current_node_id = body.node_id
        state_manager.update_state(state)

        next_node = db.get_story_node_by_node_id(state.novel_id, body.node_id)

        if next_node and next_node.get("needs_generation"):
            characters = db.get_characters_by_novel(state.novel_id)
            player_char = next((c for c in characters if c["id"] == state.character_id), None)
            if player_char:
                from state_machine import NodeBuilder
                from deepseek_client import DeepSeekClient
                node_builder = NodeBuilder(DeepSeekClient(db=db))
                scene = await node_builder.generate_node_scene(
                    node=next_node, player_character=player_char, context={"last_route": state.current_route}
                )
                db.update_story_node_scene(next_node["id"], scene)
                next_node = db.get_story_node_by_node_id(state.novel_id, body.node_id)

        choices = json.loads(next_node.get("choices", "[]")) if next_node and isinstance(next_node.get("choices"), str) else (next_node.get("choices", []) if next_node else [])

        return {
            "success": True,
            "state": state.to_dict(),
            "next_node": {
                "node_id": next_node["node_id"],
                "route": next_node.get("route", "main"),
                "scene_data": json.loads(next_node["scene_data"]) if isinstance(next_node.get("scene_data"), str) else next_node.get("scene_data"),
                "choices": choices,
                "auto_next": next_node.get("auto_next")
            } if next_node else None
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/game/{state_id}/choose")
async def make_choice_api(state_id: str, request: Request, body: ChooseRequest):
    """做出选择 - 导航到下一节点"""
    user = await login_required(get_current_user(request))

    state = state_manager.get_state(state_id)
    if not state:
        raise HTTPException(status_code=404, detail="游戏状态不存在")

    if state.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权操作")

    try:
        new_state = node_navigator.navigate_to(state, body.choice_id, body.option_index)
        next_node = db.get_story_node_by_node_id(state.novel_id, new_state.current_node_id)

        if next_node and next_node.get("needs_generation"):
            characters = db.get_characters_by_novel(state.novel_id)
            player_char = next((c for c in characters if c["id"] == state.character_id), None)
            if player_char:
                from state_machine import NodeBuilder
                from deepseek_client import DeepSeekClient
                node_builder = NodeBuilder(DeepSeekClient(db=db))
                scene = await node_builder.generate_node_scene(
                    node=next_node, player_character=player_char, context={"last_route": new_state.current_route}
                )
                db.update_story_node_scene(next_node["id"], scene)
                next_node = db.get_story_node_by_node_id(state.novel_id, new_state.current_node_id)

        choices = json.loads(next_node.get("choices", "[]")) if next_node and isinstance(next_node.get("choices"), str) else (next_node.get("choices", []) if next_node else [])

        return {
            "success": True,
            "state": new_state.to_dict(),
            "next_node": {
                "node_id": next_node["node_id"] if next_node else None,
                "scene_data": next_node.get("scene_data") if next_node else None,
                "choices": choices
            } if next_node else None
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/game/{state_id}/relationships")
async def get_relationships_api(state_id: str, request: Request):
    """获取游戏中的角色关系状态"""
    user = await login_required(get_current_user(request))

    state = state_manager.get_state(state_id)
    if not state:
        raise HTTPException(status_code=404, detail="游戏状态不存在")

    if state.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问")

    player_char_name = ""
    characters = db.get_characters_by_novel(state.novel_id)
    for c in characters:
        if c["id"] == state.character_id:
            player_char_name = c.get("name", "")
            break

    is_admin = user.get("role") == "admin"

    relationships = []
    for char_name, targets in state.relationships.items():
        for target_name, rel_state in targets.items():
            rel_data = {
                "from": char_name, "to": target_name,
                "affection": rel_state.apparent_affection,
                "flags": rel_state.flags,
                "changes": rel_state.changes[-5:] if rel_state.changes else []
            }
            if is_admin:
                rel_data["true_affection"] = rel_state.true_affection
                rel_data["difference"] = rel_state.true_affection - rel_state.apparent_affection
            relationships.append(rel_data)

    return {"player_character": player_char_name, "relationships": relationships}


# ========== 存档 API ==========

@router.post("/api/save")
async def create_save_api(request: Request):
    """创建存档"""
    user = await login_required(get_current_user(request))
    body = await request.json()

    game_state_id = body.get("game_state_id")
    save_name = body.get("save_name", "存档")
    save_slot = body.get("save_slot", 0)
    play_time = body.get("play_time", 0)

    state = state_manager.get_state(game_state_id)
    if not state:
        raise HTTPException(status_code=404, detail="游戏状态不存在")

    if state.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权操作")

    try:
        save_id = save_manager.create_save(
            game_state_id=game_state_id, save_name=save_name, save_slot=save_slot, play_time=play_time
        )
        return {"success": True, "save_id": save_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/saves/{novel_id}")
async def list_saves_api(novel_id: str, request: Request):
    """获取存档列表"""
    user = await login_required(get_current_user(request))

    states = db.get_game_states_by_user(user["id"], novel_id)

    saves = []
    for state in states:
        state_saves = db.get_game_saves_by_state(state["id"])
        saves.extend(state_saves)

    return {"saves": saves}


@router.get("/api/save/{save_id}")
async def load_save_api(save_id: str, request: Request):
    """加载存档"""
    user = await login_required(get_current_user(request))

    save_data = db.get_game_save(save_id)
    if not save_data:
        raise HTTPException(status_code=404, detail="存档不存在")

    state = db.get_game_state(save_data["game_state_id"])
    if not state or (state["user_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=403, detail="无权访问")

    state_obj = save_manager.load_save(save_id)
    if not state_obj:
        raise HTTPException(status_code=404, detail="存档数据损坏")

    node = db.get_story_node_by_node_id(state_obj.novel_id, state_obj.current_node_id)

    return {
        "success": True,
        "state": state_obj.to_dict(),
        "current_node": {
            "node_id": node["node_id"] if node else None,
            "scene_data": node.get("scene_data") if node else None
        } if node else None
    }


@router.delete("/api/save/{save_id}")
async def delete_save_api(save_id: str, request: Request):
    """删除存档"""
    user = await login_required(get_current_user(request))

    save_data = db.get_game_save(save_id)
    if not save_data:
        raise HTTPException(status_code=404, detail="存档不存在")

    state = db.get_game_state(save_data["game_state_id"])
    if not state or (state["user_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=403, detail="无权操作")

    save_manager.delete_save(save_id)
    return {"success": True}


@router.post("/api/save-progress")
async def save_progress(novel_id: str, chapter_id: int, node_id: int, flags: dict, request: Request):
    """保存进度"""
    await login_required(get_current_user(request))
    db.save_progress(novel_id, chapter_id, node_id, flags)
    return {"success": True}


@router.get("/api/load-progress/{novel_id}")
async def load_progress(novel_id: str):
    """加载进度"""
    save = db.load_progress(novel_id)
    if not save:
        return {"has_save": False}
    return {"has_save": True, "data": save}
