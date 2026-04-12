"""
SQLite 数据库持久化层
提供数据库初始化 + CRUD 操作，所有路径基于 DATA_DIR 环境变量
"""

import os
import json
import sqlite3
from typing import Dict, Any, List, Optional

DATA_DIR = os.getenv(
    "DATA_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
    ),
)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "novel_vn.db")

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS novels (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    visibility TEXT DEFAULT 'public',
    art_style TEXT DEFAULT 'anime',
    style_keywords TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    novel_id TEXT NOT NULL,
    name TEXT NOT NULL,
    gender TEXT DEFAULT '',
    age_range TEXT DEFAULT '',
    appearance TEXT DEFAULT '',
    clothing TEXT DEFAULT '',
    distinctive_features TEXT DEFAULT '',
    aliases TEXT DEFAULT '[]',
    personality TEXT DEFAULT '',
    speaking_style TEXT DEFAULT '',
    is_playable INTEGER DEFAULT 1,
    relations TEXT DEFAULT '{}',
    image_path TEXT DEFAULT '',
    FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    novel_id TEXT NOT NULL,
    chapter_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    summary TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS segment_characters (
    segment_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    PRIMARY KEY (segment_id, character_id),
    FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chapter_characters (
    chapter_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    PRIMARY KEY (chapter_id, character_id),
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generated_runs (
    id TEXT PRIMARY KEY,
    chapter_fk TEXT NOT NULL,
    character_id TEXT,
    player_char_name TEXT,
    scenes_data TEXT DEFAULT '{}',
    choices_data TEXT DEFAULT '[]',
    route TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chapter_fk) REFERENCES chapters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    novel_id TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    progress REAL DEFAULT 0.0,
    current_step TEXT,
    total_steps INTEGER DEFAULT 0,
    current_step_num INTEGER DEFAULT 0,
    message TEXT,
    result TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS save_points (
    novel_id TEXT PRIMARY KEY,
    chapter_id INTEGER,
    node_id INTEGER,
    flags TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT PRIMARY KEY,
    chunk_size INTEGER DEFAULT 5000,
    chunk_overlap INTEGER DEFAULT 300,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_characters_novel ON characters(novel_id);
CREATE INDEX IF NOT EXISTS idx_chapters_novel ON chapters(novel_id);
CREATE INDEX IF NOT EXISTS idx_segments_chapter ON segments(chapter_id);
CREATE INDEX IF NOT EXISTS idx_generated_chapter ON generated_runs(chapter_fk);
CREATE TABLE IF NOT EXISTS prompt_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id TEXT,
    prompt_type TEXT NOT NULL,
    system_prompt TEXT,
    user_prompt TEXT NOT NULL,
    ai_response TEXT,
    model TEXT,
    novel_id TEXT,
    chapter_fk TEXT,
    character_id TEXT,
    metadata TEXT DEFAULT '{}',
    self_eval TEXT
);
CREATE INDEX IF NOT EXISTS idx_prompt_history_type ON prompt_history(prompt_type);
CREATE INDEX IF NOT EXISTS idx_prompt_history_created ON prompt_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_history_novel ON prompt_history(novel_id);
"""


class Database:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(CREATE_TABLES)
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # ===================== Novel =====================
    def create_novel(
        self,
        novel_id: str,
        title: str,
        owner_id: str = None,
        visibility: str = "public",
        art_style: str = "anime",
        style_keywords: str = "",
    ) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO novels
                   (id, title, owner_id, visibility, art_style, style_keywords)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (novel_id, title, owner_id, visibility, art_style, style_keywords),
            )
            conn.commit()
            return self.get_novel(novel_id)
        finally:
            conn.close()

    def get_novel(self, novel_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
        conn.close()
        if row:
            return dict(row)
        return None

    def update_novel_art_style(
        self, novel_id: str, art_style: str, style_keywords: str = ""
    ) -> None:
        """更新小说的艺术风格"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE novels SET art_style = ?, style_keywords = ? WHERE id = ?",
            (art_style, style_keywords, novel_id),
        )
        conn.commit()
        conn.close()

    # ===================== Character =====================
    def create_characters(
        self, novel_id: str, characters: List[Dict[str, Any]]
    ) -> None:
        conn = self._get_conn()
        try:
            for c in characters:
                conn.execute(
                    """INSERT OR IGNORE INTO characters
                       (id, novel_id, name, gender, age_range, appearance, clothing,
                        distinctive_features, aliases, personality, speaking_style,
                        is_playable, relations)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        c["id"],
                        novel_id,
                        c["name"],
                        c.get("gender", ""),
                        c.get("age_range", ""),
                        c.get("appearance", ""),
                        c.get("clothing", ""),
                        c.get("distinctive_features", ""),
                        json.dumps(c.get("aliases", [])),
                        c.get("personality", ""),
                        c.get("speaking_style", ""),
                        1 if c.get("is_playable", True) else 0,
                        json.dumps(c.get("relations", {})),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_characters_by_novel(self, novel_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM characters WHERE novel_id = ?", (novel_id,)
        ).fetchall()
        conn.close()
        result = []
        for row in rows:
            d = dict(row)
            d["aliases"] = json.loads(d["aliases"])
            d["relations"] = json.loads(d["relations"])
            d["is_playable"] = bool(d["is_playable"])
            result.append(d)
        return result

    def update_character_image_path(
        self, char_id: str, image_path: str
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE characters SET image_path = ? WHERE id = ?",
            (image_path, char_id),
        )
        conn.commit()
        conn.close()

    # ===================== Chapter =====================
    def create_chapter(
        self,
        chapter_pk: str,
        novel_id: str,
        chapter_id: int,
        title: str,
        raw_content: str,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO chapters
               (id, novel_id, chapter_id, title, raw_content)
               VALUES (?, ?, ?, ?, ?)""",
            (chapter_pk, novel_id, chapter_id, title, raw_content),
        )
        conn.commit()
        conn.close()

    def get_chapters_by_novel(self, novel_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM chapters WHERE novel_id = ? ORDER BY chapter_id",
            (novel_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_chapter_by_id(self, chapter_fk: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM chapters WHERE id = ?", (chapter_fk,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    # ===================== Segments =====================
    def create_segment(self, segment_id: str, chapter_id: str, segment_index: int, content: str) -> None:
        """创建片段记录"""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO segments (id, chapter_id, segment_index, content, summary)
               VALUES (?, ?, ?, ?, '')""",
            (segment_id, chapter_id, segment_index, content),
        )
        conn.commit()
        conn.close()

    def get_segments_by_chapter(self, chapter_id: str) -> List[Dict[str, Any]]:
        """获取章节的所有片段，按序号排序"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM segments WHERE chapter_id = ? ORDER BY segment_index",
            (chapter_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_segment_summary(self, segment_id: str, summary: str) -> None:
        """更新片段摘要"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE segments SET summary = ? WHERE id = ?",
            (summary, segment_id),
        )
        conn.commit()
        conn.close()

    def delete_segments_by_chapter(self, chapter_id: str) -> None:
        """删除章节的所有片段"""
        conn = self._get_conn()
        conn.execute("DELETE FROM segments WHERE chapter_id = ?", (chapter_id,))
        conn.commit()
        conn.close()

    # ===================== Segment-Character association =====================
    def link_segment_character(self, segment_id: str, character_id: str) -> None:
        """关联片段和角色"""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO segment_characters (segment_id, character_id) VALUES (?, ?)",
            (segment_id, character_id),
        )
        conn.commit()
        conn.close()

    def get_characters_for_segment(self, segment_id: str) -> List[str]:
        """获取片段涉及的所有角色ID"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT character_id FROM segment_characters WHERE segment_id = ?",
            (segment_id,),
        ).fetchall()
        conn.close()
        return [r["character_id"] for r in rows]

    def get_segments_for_character(self, character_id: str) -> List[str]:
        """获取角色出现的所有片段ID"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT segment_id FROM segment_characters WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        conn.close()
        return [r["segment_id"] for r in rows]

    # ===================== Chapter-Character association =====================
    def link_chapter_character(self, chapter_fk: str, character_id: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO chapter_characters (chapter_id, character_id) VALUES (?, ?)",
            (chapter_fk, character_id),
        )
        conn.commit()
        conn.close()

    def get_characters_for_chapter(self, chapter_fk: str) -> List[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT character_id FROM chapter_characters WHERE chapter_id = ?",
            (chapter_fk,),
        ).fetchall()
        conn.close()
        return [r["character_id"] for r in rows]

    # ===================== Generated Runs =====================
    def create_generated_run(
        self,
        run_id: str,
        chapter_fk: str,
        character_id: str,
        player_char_name: str,
        scenes_data: Dict[str, Any],
        choices_data: List[Dict[str, Any]],
        route: str = "",
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO generated_runs
               (id, chapter_fk, character_id, player_char_name, scenes_data, choices_data, route)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                chapter_fk,
                character_id,
                player_char_name,
                json.dumps(scenes_data, ensure_ascii=False),
                json.dumps(choices_data, ensure_ascii=False),
                route,
            ),
        )
        conn.commit()
        conn.close()

    def get_generated_runs_for_chapter(
        self, chapter_fk: str
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM generated_runs WHERE chapter_fk = ?",
            (chapter_fk,),
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["scenes_data"] = json.loads(d["scenes_data"])
            d["choices_data"] = json.loads(d["choices_data"])
            result.append(d)
        return result

    # ===================== Task =====================
    def create_task(self, task_id: str, novel_id: str, title: str, total_steps: int) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO tasks
               (id, novel_id, title, status, progress, current_step, total_steps, current_step_num, message)
               VALUES (?, ?, ?, 'pending', 0.0, '初始化', ?, 0, '等待开始...')""",
            (task_id, novel_id, title, total_steps),
        )
        conn.commit()
        conn.close()

    def create_generate_task(self, task_id: str) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO tasks
               (id, status, message)
               VALUES (?, 'pending', '等待生成...')""",
            (task_id,),
        )
        conn.commit()
        conn.close()

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        current_step: Optional[str] = None,
        current_step_num: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        fields = []
        values: list = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if current_step is not None:
            fields.append("current_step = ?")
            values.append(current_step)
        if current_step_num is not None:
            fields.append("current_step_num = ?")
            values.append(current_step_num)
        if message is not None:
            fields.append("message = ?")
            values.append(message)
        if result is not None:
            fields.append("result = ?")
            values.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            fields.append("error = ?")
            values.append(error)

        if fields:
            values.append(task_id)
            conn = self._get_conn()
            conn.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values
            )
            conn.commit()
            conn.close()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        if d.get("result"):
            d["result"] = json.loads(d["result"])
        return d

    # ===================== Save Points =====================
    def save_progress(
        self, novel_id: str, chapter_id: int, node_id: int, flags: Dict[str, Any]
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO save_points
               (novel_id, chapter_id, node_id, flags)
               VALUES (?, ?, ?, ?)""",
            (novel_id, chapter_id, node_id, json.dumps(flags, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()

    def load_progress(self, novel_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM save_points WHERE novel_id = ?", (novel_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["flags"] = json.loads(d["flags"])
        return d

    # ===================== User =====================
    def create_user(self, user_id: str, username: str, password_hash: str, role: str = 'user') -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, role),
            )
            conn.commit()
            return self.get_user(user_id)
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute("SELECT id, username, role, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def ensure_admin_exists(self) -> None:
        """确保至少存在一个管理员账户（首次启动时自动创建 admin/admin）"""
        existing = self.get_user_by_username('admin')
        if not existing:
            from passlib.hash import bcrypt
            self.create_user('admin-001', 'admin', bcrypt.hash('admin'), role='admin')
            print("已自动创建管理员账户: admin / admin")

    def get_all_users(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY created_at"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_user_role(self, user_id: str, role: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?", (role, user_id)
        )
        conn.commit()
        conn.close()

    def delete_user(self, user_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()

    # ===================== Session =====================
    def create_session(self, session_id: str, user_id: str, expires_hours: int = 24) -> None:
        from datetime import datetime, timedelta
        expires_at = (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user_id, expires_at),
        )
        conn.commit()
        conn.close()

    def get_session_user(self, session_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            """SELECT u.id, u.username, u.role
               FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.session_id = ? AND s.expires_at > datetime('now')""",
            (session_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_session(self, session_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def cleanup_expired_sessions(self) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
        conn.commit()
        conn.close()

    # ===================== Novel (enhanced) =====================
    def create_novel(self, novel_id: str, title: str, owner_id: str, visibility: str = 'public') -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO novels (id, title, owner_id, visibility) VALUES (?, ?, ?, ?)",
                (novel_id, title, owner_id, visibility),
            )
            conn.commit()
            return self.get_novel(novel_id)
        finally:
            conn.close()

    def get_novel(self, novel_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_novels(self, include_private: bool = False) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        if include_private:
            rows = conn.execute(
                """SELECT n.*, u.username as owner_name
                   FROM novels n LEFT JOIN users u ON n.owner_id = u.id
                   ORDER BY n.created_at DESC"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT n.*, u.username as owner_name
                   FROM novels n LEFT JOIN users u ON n.owner_id = u.id
                   WHERE n.visibility = 'public'
                   ORDER BY n.created_at DESC"""
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_user_novels(self, user_id: str, include_private: bool = True) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        if include_private:
            rows = conn.execute(
                "SELECT * FROM novels WHERE owner_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM novels WHERE owner_id = ? AND visibility = 'public' ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_novel_visibility(self, novel_id: str, visibility: str, owner_id: Optional[str] = None) -> bool:
        conn = self._get_conn()
        if owner_id:
            cursor = conn.execute(
                "UPDATE novels SET visibility = ? WHERE id = ? AND owner_id = ?",
                (visibility, novel_id, owner_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE novels SET visibility = ? WHERE id = ?",
                (visibility, novel_id),
            )
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def delete_novel(self, novel_id: str, owner_id: Optional[str] = None) -> bool:
        conn = self._get_conn()
        if owner_id:
            cursor = conn.execute("DELETE FROM novels WHERE id = ? AND owner_id = ?", (novel_id, owner_id))
        else:
            cursor = conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def get_novel_owner(self, novel_id: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute("SELECT owner_id FROM novels WHERE id = ?", (novel_id,)).fetchone()
        conn.close()
        return row["owner_id"] if row else None

    # ===================== User Settings =====================
    def get_user_settings(self, user_id: str) -> Dict[str, Any]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT chunk_size, chunk_overlap FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if row:
            return {"chunk_size": row["chunk_size"], "chunk_overlap": row["chunk_overlap"]}
        return {"chunk_size": 5000, "chunk_overlap": 300}

    def update_user_settings(self, user_id: str, chunk_size: int = None, chunk_overlap: int = None) -> None:
        defaults = self.get_user_settings(user_id)
        new_chunk_size = chunk_size if chunk_size is not None else defaults["chunk_size"]
        new_overlap = chunk_overlap if chunk_overlap is not None else defaults["chunk_overlap"]
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO user_settings (user_id, chunk_size, chunk_overlap)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET chunk_size = ?, chunk_overlap = ?""",
            (user_id, new_chunk_size, new_overlap, new_chunk_size, new_overlap),
        )
        conn.commit()
        conn.close()

    # ===================== Prompt History =====================
    def create_prompt_history(
        self,
        prompt_type: str,
        user_prompt: str,
        user_id: str = None,
        system_prompt: str = None,
        ai_response: str = None,
        model: str = None,
        novel_id: str = None,
        chapter_fk: str = None,
        character_id: str = None,
        metadata: dict = None,
    ) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO prompt_history
               (user_id, prompt_type, system_prompt, user_prompt, ai_response, model, novel_id, chapter_fk, character_id, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, prompt_type, system_prompt, user_prompt, ai_response, model,
             novel_id, chapter_fk, character_id, json.dumps(metadata or {})),
        )
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return record_id

    def update_prompt_history_eval(self, record_id: int, eval_text: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE prompt_history SET self_eval = ? WHERE id = ?",
            (eval_text, record_id),
        )
        conn.commit()
        conn.close()

    def list_prompt_history(
        self, offset: int = 0, limit: int = 20,
        prompt_type: str = None, novel_id: str = None,
    ) -> List[Dict[str, Any]]:
        conditions = []
        values: list = []
        if prompt_type:
            conditions.append("prompt_type = ?")
            values.append(prompt_type)
        if novel_id:
            conditions.append("novel_id = ?")
            values.append(novel_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.extend([limit, offset])
        conn = self._get_conn()
        rows = conn.execute(
            f"SELECT * FROM prompt_history {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            values,
        ).fetchall()
        conn.close()
        result = []
        for row in rows:
            d = dict(row)
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def count_prompt_history(
        self, prompt_type: str = None, novel_id: str = None,
    ) -> int:
        conditions = []
        values: list = []
        if prompt_type:
            conditions.append("prompt_type = ?")
            values.append(prompt_type)
        if novel_id:
            conditions.append("novel_id = ?")
            values.append(novel_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM prompt_history {where}", values,
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0

    def get_prompt_history_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM prompt_history WHERE id = ?", (record_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"])
        return d

    def delete_old_prompt_history(self, days: int = 30) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM prompt_history WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.commit()
        conn.close()
        return cursor.rowcount


db = Database()
