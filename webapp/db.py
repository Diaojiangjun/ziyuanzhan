"""SQLite 数据层：资源站、探测记录与统计查询。"""

import json
import os
import sqlite3
from datetime import datetime, timedelta

from .utils import fmt_number, generate_slug, parse_datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "data", "site.db"))
SEED_FILE = os.getenv("SEED_FILE", os.path.join(PROJECT_ROOT, "docs", "data", "sources.json"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    url TEXT DEFAULT '',
    api TEXT DEFAULT '',
    api_type TEXT DEFAULT '',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    rating REAL DEFAULT 0,
    status TEXT DEFAULT 'unknown',
    api_status TEXT DEFAULT '',
    is_alive INTEGER DEFAULT 0,
    uptime REAL DEFAULT 0,
    api_uptime REAL DEFAULT 0,
    speed TEXT DEFAULT 'unknown',
    response_time INTEGER DEFAULT 0,
    update_frequency TEXT DEFAULT '',
    total_resources INTEGER DEFAULT 0,
    last_update_time TEXT DEFAULT '',
    last_resource_update TEXT DEFAULT '',
    established_at TEXT DEFAULT '',
    today_updates INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    status_code INTEGER,
    response_time_ms INTEGER,
    is_alive INTEGER NOT NULL,
    error TEXT DEFAULT '',
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_source_time ON checks(source_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_sources_alive ON sources(is_alive);
"""

FIELD_MAP = {
    "name": "name",
    "url": "url",
    "api": "api",
    "apiType": "api_type",
    "description": "description",
    "rating": "rating",
    "status": "status",
    "uptime": "uptime",
    "speed": "speed",
    "responseTime": "response_time",
    "updateFrequency": "update_frequency",
    "totalResources": "total_resources",
    "lastUpdateTime": "last_update_time",
    "lastResourceUpdate": "last_resource_update",
    "establishedAt": "established_at",
    "todayUpdates": "today_updates",
}


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    tags = item.get("tags") or "[]"
    try:
        item["tags"] = json.loads(tags) if isinstance(tags, str) else tags
    except json.JSONDecodeError:
        item["tags"] = []
    item["is_alive"] = bool(item.get("is_alive"))
    return item


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
    _seed_if_empty()


def _seed_if_empty() -> None:
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    if count or not os.path.exists(SEED_FILE):
        return
    try:
        with open(SEED_FILE, "r", encoding="utf-8") as handle:
            records = json.load(handle)
    except Exception as exc:
        print(f"[WARN] 读取种子数据失败: {exc}")
        return
    for record in records:
        upsert_source(record)
    print(f"[INFO] 已从 {SEED_FILE} 导入 {len(records)} 个资源站")


def _normalize(record: dict) -> dict:
    item = {}
    for source_key, target_key in FIELD_MAP.items():
        if source_key in record:
            item[target_key] = record[source_key]
    item["name"] = str(item.get("name") or "").strip()
    item["tags"] = record.get("tags") or []
    item["api_status"] = item.get("status") or ""
    item["api_uptime"] = float(item.get("uptime") or 0)
    item["is_alive"] = 1 if item.get("status") == "ok" else 0
    if not item.get("status"):
        item["status"] = "ok" if item["is_alive"] else "unknown"
    for key in ("rating", "uptime", "response_time", "total_resources", "today_updates"):
        try:
            item[key] = float(item.get(key) or 0) if key in ("rating", "uptime") else int(item.get(key) or 0)
        except (TypeError, ValueError):
            item[key] = 0
    for key in ("url", "api", "api_type", "description", "speed", "update_frequency",
                "last_update_time", "last_resource_update", "established_at"):
        item[key] = str(item.get(key) or "").strip()
    return item


def upsert_source(record: dict) -> int:
    item = _normalize(record)
    if not item["name"]:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        existing = conn.execute("SELECT id FROM sources WHERE name = ?", (item["name"],)).fetchone()
        if existing:
            conn.execute(
                """UPDATE sources SET url=?, api=?, api_type=?, description=?, tags=?, rating=?,
                   status=?, api_status=?, is_alive=?, uptime=?, api_uptime=?, speed=?, response_time=?, update_frequency=?,
                   total_resources=?, last_update_time=?, last_resource_update=?, established_at=?,
                   today_updates=?, updated_at=? WHERE id=?""",
                (
                    item["url"], item["api"], item["api_type"], item["description"],
                    json.dumps(item["tags"], ensure_ascii=False), item["rating"], item["status"],
                    item["api_status"], item["is_alive"], item["uptime"], item["api_uptime"],
                    item["speed"], item["response_time"],
                    item["update_frequency"], item["total_resources"], item["last_update_time"],
                    item["last_resource_update"], item["established_at"], item["today_updates"],
                    now, existing["id"],
                ),
            )
            return existing["id"]

        slug = generate_slug(item["name"])
        candidate = slug
        suffix = 2
        while conn.execute("SELECT 1 FROM sources WHERE slug = ?", (candidate,)).fetchone():
            candidate = f"{slug}{suffix}"
            suffix += 1
        cursor = conn.execute(
            """INSERT INTO sources (slug, name, url, api, api_type, description, tags, rating,
               status, api_status, is_alive, uptime, api_uptime, speed, response_time, update_frequency, total_resources,
               last_update_time, last_resource_update, established_at, today_updates, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate, item["name"], item["url"], item["api"], item["api_type"],
                item["description"], json.dumps(item["tags"], ensure_ascii=False), item["rating"],
                item["status"], item["api_status"], item["is_alive"], item["uptime"],
                item["api_uptime"], item["speed"], item["response_time"],
                item["update_frequency"], item["total_resources"],
                item["last_update_time"], item["last_resource_update"], item["established_at"],
                item["today_updates"], now, now,
            ),
        )
        return int(cursor.lastrowid)


def all_active_sources() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM sources WHERE is_active = 1 ORDER BY id").fetchall()
    return [_row_to_dict(row) for row in rows]


def sources_with_api() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sources WHERE is_active = 1 AND api != '' ORDER BY is_alive DESC, uptime DESC, id"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_source_by_slug(slug: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE slug = ?", (slug,)).fetchone()
    return _row_to_dict(row) if row else None


SORT_SQL = {
    "default": "rating DESC, uptime DESC, id ASC",
    "uptime": "uptime DESC, rating DESC, id ASC",
    "resources": "total_resources DESC, rating DESC, id ASC",
    "speed": "CASE WHEN response_time > 0 THEN response_time ELSE 999999 END ASC, rating DESC",
    "latest": "last_resource_update DESC, rating DESC, id ASC",
    "name": "name ASC",
}


def list_sources(query: str = "", tag: str = "", status: str = "all", sort: str = "default",
                 page: int = 1, per_page: int = 24) -> dict:
    where = ["is_active = 1"]
    params: list = []
    if query:
        like = f"%{query}%"
        where.append("(name LIKE ? OR description LIKE ? OR tags LIKE ? OR url LIKE ?)")
        params.extend([like, like, like, like])
    if tag:
        where.append("tags LIKE ?")
        params.append(f'%"{tag}"%')
    if status == "online":
        where.append("is_alive = 1")
    elif status == "offline":
        where.append("is_alive = 0")

    clause = " WHERE " + " AND ".join(where)
    order = SORT_SQL.get(sort, SORT_SQL["default"])
    page = max(page, 1)
    per_page = min(max(per_page, 1), 96)

    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM sources{clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM sources{clause} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
    pages = max((total + per_page - 1) // per_page, 1)
    return {
        "items": [_row_to_dict(row) for row in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }


def all_tags() -> list[dict]:
    tags: dict[str, int] = {}
    with connect() as conn:
        rows = conn.execute("SELECT tags FROM sources WHERE is_active = 1").fetchall()
    for row in rows:
        try:
            for tag in json.loads(row["tags"] or "[]"):
                tags[tag] = tags.get(tag, 0) + 1
        except json.JSONDecodeError:
            continue
    return sorted(({"name": name, "count": count} for name, count in tags.items()),
                  key=lambda item: (-item["count"], item["name"]))


def global_stats() -> dict:
    with connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(is_alive) AS alive,
                      SUM(CASE WHEN is_alive = 1 THEN 1 ELSE 0 END) AS alive_count,
                      SUM(total_resources) AS total_resources,
                      SUM(today_updates) AS today_updates,
                      AVG(CASE WHEN is_alive = 1 THEN uptime END) AS avg_uptime,
                      AVG(CASE WHEN is_alive = 1 AND response_time > 0 THEN response_time END) AS avg_response,
                      MAX(updated_at) AS last_updated
               FROM sources WHERE is_active = 1"""
        ).fetchone()
        warning = conn.execute(
            """SELECT COUNT(*) FROM sources WHERE is_active = 1 AND is_alive = 1
               AND uptime < 99"""
        ).fetchone()[0]

    total = row["total"] or 0
    alive = row["alive"] or 0
    avg_response = round(row["avg_response"] or 0)
    avg_uptime = row["avg_uptime"] or 0
    online_rate = round(alive / total * 100, 3) if total else 0
    speed_score = max(0, min(100, 100 - avg_response / 20)) if avg_response else 100
    health_score = round(online_rate * 0.3 + avg_uptime * 0.4 + speed_score * 0.3)
    return {
        "total": total,
        "alive": alive,
        "offline": total - alive,
        "warning": warning,
        "online_rate": online_rate,
        "avg_response": avg_response,
        "total_resources": row["total_resources"] or 0,
        "total_resources_text": fmt_number(row["total_resources"] or 0),
        "today_updates": row["today_updates"] or 0,
        "health_score": min(health_score, 100),
        "last_updated": row["last_updated"] or "",
    }


def save_check(source_id: int, status_code, response_time_ms, is_alive: bool, error: str = "") -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        conn.execute(
            """INSERT INTO checks (source_id, checked_at, status_code, response_time_ms, is_alive, error)
               VALUES (?,?,?,?,?,?)""",
            (source_id, now, status_code, response_time_ms, 1 if is_alive else 0, error or ""),
        )


def update_source_after_check(source_id: int, is_alive: bool, response_time_ms, status_code,
                              error: str = "") -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        stats = conn.execute(
            """SELECT COUNT(*) AS total, SUM(is_alive) AS alive FROM checks
               WHERE source_id = ? AND checked_at >= ?""",
            (source_id, since),
        ).fetchone()
        row = conn.execute("SELECT uptime, speed FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            return
        total = stats["total"] or 0
        local_uptime = round((stats["alive"] or 0) / total * 100, 3) if total else row["uptime"]
        uptime = local_uptime if total >= 5 else (row["uptime"] or local_uptime)

        if is_alive and response_time_ms:
            if response_time_ms < 600:
                speed = "fast"
            elif response_time_ms < 1500:
                speed = "medium"
            else:
                speed = "slow"
        else:
            speed = row["speed"]

        conn.execute(
            """UPDATE sources SET is_alive = ?, status = ?, uptime = ?, speed = ?,
               response_time = ?, updated_at = ? WHERE id = ?""",
            (
                1 if is_alive else 0,
                "ok" if is_alive else "down",
                uptime,
                speed,
                int(response_time_ms or 0) if is_alive else 0,
                now,
                source_id,
            ),
        )


def daily_availability_map(days: int = 10) -> dict[int, dict[str, dict]]:
    start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    with connect() as conn:
        rows = conn.execute(
            """SELECT source_id, date(checked_at) AS day, COUNT(*) AS total,
                      SUM(is_alive) AS alive, AVG(response_time_ms) AS avg_response
               FROM checks WHERE checked_at >= ?
               GROUP BY source_id, day""",
            (start,),
        ).fetchall()
    result: dict[int, dict[str, dict]] = {}
    for row in rows:
        result.setdefault(row["source_id"], {})[row["day"]] = {
            "total": row["total"],
            "alive": row["alive"] or 0,
            "avg_response": round(row["avg_response"] or 0),
        }
    return result


def source_history(source_id: int, days: int = 10) -> list[dict]:
    start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    with connect() as conn:
        rows = conn.execute(
            """SELECT date(checked_at) AS day, COUNT(*) AS total, SUM(is_alive) AS alive,
                      AVG(response_time_ms) AS avg_response, MAX(response_time_ms) AS max_response
               FROM checks WHERE source_id = ? AND checked_at >= ?
               GROUP BY day ORDER BY day DESC""",
            (source_id, start),
        ).fetchall()
    return [
        {
            "day": row["day"],
            "total": row["total"],
            "alive": row["alive"] or 0,
            "avg_response": round(row["avg_response"] or 0),
            "max_response": row["max_response"] or 0,
            "ok": (row["alive"] or 0) == row["total"],
        }
        for row in rows
    ]


def source_check_summary(source_id: int, days: int = 30) -> dict:
    start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    with connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total, SUM(is_alive) AS alive,
                      AVG(CASE WHEN is_alive = 1 THEN response_time_ms END) AS avg_response
               FROM checks WHERE source_id = ? AND checked_at >= ?""",
            (source_id, start),
        ).fetchone()
    total = row["total"] or 0
    alive = row["alive"] or 0
    return {
        "days": days,
        "checks": total,
        "alive": alive,
        "uptime": round(alive / total * 100, 3) if total else None,
        "avg_response": round(row["avg_response"] or 0),
    }


def recent_checks(source_id: int, limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT checked_at, status_code, response_time_ms, is_alive, error
               FROM checks WHERE source_id = ? ORDER BY checked_at DESC LIMIT ?""",
            (source_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def related_sources(source: dict, limit: int = 8) -> list[dict]:
    tags = [tag for tag in source.get("tags", []) if tag][:4]
    with connect() as conn:
        rows = conn.execute("SELECT * FROM sources WHERE is_active = 1 AND id != ?", (source["id"],)).fetchall()
    items = [_row_to_dict(row) for row in rows]
    scored = []
    for item in items:
        score = len(set(tags) & set(item.get("tags", []))) * 3
        if item.get("is_alive"):
            score += 1
        score += (item.get("rating") or 0) / 10
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], -float(pair[1].get("rating") or 0)))
    return [item for _, item in scored[:limit]]


def estimate_founded_year(source: dict) -> int | None:
    parsed = parse_datetime(source.get("established_at", ""))
    return parsed.year if parsed else None


def set_meta(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_meta(key: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def prune_checks(days: int = 90) -> None:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        conn.execute("DELETE FROM checks WHERE checked_at < ?", (cutoff,))
