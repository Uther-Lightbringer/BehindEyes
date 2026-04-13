"""
管理后台 API
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from typing import Optional
import json

from db import db
from auth import admin_required

router = APIRouter(prefix="/api/admin", tags=["管理"])


@router.get("/users")
async def admin_list_users(user: dict = Depends(admin_required)):
    """获取用户列表"""
    users = db.get_all_users()
    return {"users": users}


@router.post("/users/{user_id}/role")
async def admin_update_role(user_id: str, request: Request, user: dict = Depends(admin_required)):
    """更新用户角色"""
    data = await request.json()
    new_role = data.get("role")
    if new_role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="无效的角色")
    db.update_user_role(user_id, new_role)
    return {"success": True, "message": f"用户 {user_id} 角色已更新为 {new_role}"}


@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: str, user: dict = Depends(admin_required)):
    """删除用户"""
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    db.delete_user(user_id)
    return {"success": True, "message": "用户已删除"}


@router.get("/novels")
async def admin_list_novels(user: dict = Depends(admin_required)):
    """获取所有小说列表"""
    novels = db.get_all_novels(include_private=True)
    return {"novels": novels}


@router.get("/stats")
async def admin_stats(user: dict = Depends(admin_required)):
    """获取统计数据"""
    users = db.get_all_users()
    novels = db.get_all_novels(include_private=True)
    return {
        "total_users": len(users),
        "total_novels": len(novels),
        "public_novels": len([n for n in novels if n.get("visibility") == "public"]),
        "private_novels": len([n for n in novels if n.get("visibility") == "private"]),
    }


# ========== Prompt 历史 ==========

@router.get("/prompts")
async def admin_list_prompt_history(
    user: dict = Depends(admin_required),
    prompt_type: Optional[str] = None,
    novel_id: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    """分页查询 prompt 历史记录"""
    offset = (page - 1) * limit
    records = db.list_prompt_history(
        offset=offset, limit=limit, prompt_type=prompt_type, novel_id=novel_id
    )
    total = db.count_prompt_history(prompt_type=prompt_type, novel_id=novel_id)

    for r in records:
        if r.get("self_eval"):
            try:
                r["self_eval"] = json.loads(r["self_eval"])
            except:
                pass

    return {"records": records, "total": total, "page": page, "limit": limit}


@router.get("/prompts/stats")
async def admin_prompt_stats(user: dict = Depends(admin_required)):
    """Prompt 统计"""
    conn = db._get_conn()

    type_rows = conn.execute(
        "SELECT prompt_type, COUNT(*) as cnt FROM prompt_history GROUP BY prompt_type"
    ).fetchall()
    type_dist = {r["prompt_type"]: r["cnt"] for r in type_rows}

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
        except:
            pass

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
        except:
            pass
    for pt in avg_by_type:
        avg_by_type[pt]["avg"] = round(avg_by_type[pt]["total"] / avg_by_type[pt]["count"], 2)

    conn.close()

    return {
        "type_distribution": type_dist,
        "score_distribution": score_dist,
        "avg_score_by_type": avg_by_type,
    }


@router.get("/prompts/{record_id}")
async def admin_get_prompt_detail(record_id: int, user: dict = Depends(admin_required)):
    """获取单条 prompt 记录详情"""
    record = db.get_prompt_history_by_id(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if record.get("self_eval"):
        try:
            record["self_eval"] = json.loads(record["self_eval"])
        except:
            pass
    return record
