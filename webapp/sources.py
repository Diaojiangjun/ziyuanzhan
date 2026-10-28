"""资源站数据同步与可用性探测。"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from . import db

SOURCE_API = os.getenv("SOURCE_API", "https://www.ziyuanzu.com/api/v1")
TIMEOUT = int(os.getenv("CHECK_TIMEOUT", "15"))
WORKERS = int(os.getenv("CHECK_WORKERS", "12"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}


def sync_sources() -> int:
    """从 ziyuanzu API 同步资源站，失败时保留本地数据。"""
    try:
        response = requests.get(
            f"{SOURCE_API}/sources",
            params={"limit": 200},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"[WARN] 资源站同步失败，继续使用本地数据: {exc}")
        return 0

    if not payload.get("success"):
        print("[WARN] 资源站同步返回 success=false")
        return 0

    records = {}
    for record in payload.get("data", []):
        name = record.get("name")
        if not name:
            continue
        existing = records.get(name)
        # 同名记录优先保留在线且可用率更高的
        if existing is None or (
            record.get("status") == "ok" and existing.get("status") != "ok"
        ) or (
            record.get("status") == existing.get("status")
            and float(record.get("uptime") or 0) > float(existing.get("uptime") or 0)
        ):
            records[name] = record

    count = 0
    for record in records.values():
        db.upsert_source(record)
        count += 1
    db.set_meta("last_sync", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"[INFO] 已同步 {count} 个资源站")
    return count


def check_one(source: dict) -> dict:
    """探测单个资源站，优先测采集接口，其次测站点首页。"""
    target = source.get("api") or source.get("url")
    result = {
        "source": source,
        "status_code": None,
        "response_time_ms": None,
        "is_alive": False,
        "error": "",
    }
    if not target:
        result["error"] = "未配置地址"
        return result
    try:
        start = time.time()
        response = requests.get(target, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        elapsed = round((time.time() - start) * 1000)
        result["status_code"] = response.status_code
        result["response_time_ms"] = elapsed
        # 401/403 说明服务器有响应，可能只是 WAF 拦截
        result["is_alive"] = response.status_code < 400 or response.status_code in (401, 403)
        if response.status_code in (401, 403):
            result["error"] = f"HTTP {response.status_code} 在线但受限"
    except requests.exceptions.Timeout:
        result["error"] = "请求超时"
    except requests.exceptions.ConnectionError:
        result["error"] = "连接失败"
    except Exception as exc:
        result["error"] = str(exc)[:120]
    return result


def run_health_checks() -> dict:
    """并发探测全部资源站并写入历史记录。"""
    sources = db.all_active_sources()
    if not sources:
        print("[WARN] 没有可探测的资源站")
        return {"total": 0, "alive": 0}

    alive = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(check_one, source): source for source in sources}
        for future in as_completed(futures):
            result = future.result()
            source = result["source"]
            is_alive = result["is_alive"]
            api_status = source.get("api_status") or ""
            # 以同步接口的状态为兜底：本地单机探测容易受网络出口影响
            if api_status == "ok" and not is_alive:
                is_alive = True
                result["error"] = f"在线（同步状态正常，本地检测失败：{result['error'] or result['status_code']}）"
            elif api_status == "down" and is_alive:
                result["error"] = "在线（本地检测已恢复，同步状态仍为 down）"
            alive += 1 if is_alive else 0
            db.save_check(
                source["id"],
                result["status_code"],
                result["response_time_ms"],
                is_alive,
                result["error"],
            )
            db.update_source_after_check(
                source["id"],
                is_alive,
                result["response_time_ms"],
                result["status_code"],
                result["error"],
            )
            print(
                f"  [{'在线' if is_alive else '离线'}] {source['name']}: "
                f"{result['status_code'] or result['error']}"
            )

    db.set_meta("last_check", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"[INFO] 探测完成：{alive}/{len(sources)} 在线")
    return {"total": len(sources), "alive": alive}


def run_cycle() -> None:
    sync_sources()
    run_health_checks()
    db.prune_checks(90)
