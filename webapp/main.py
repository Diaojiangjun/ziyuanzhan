"""资源组复刻站点：FastAPI 入口。"""

import os
import threading
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import content, db, sources
from .utils import domain_of, fmt_ms, fmt_number, fmt_percent, recent_dates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENABLE_MONITOR = os.getenv("ENABLE_MONITOR", "1") != "0"
MONITOR_INTERVAL = max(int(os.getenv("MONITOR_INTERVAL_MINUTES", "120")), 5)
SITE_NAME = os.getenv("SITE_NAME", "资源组")


def _monitor_loop() -> None:
    while True:
        try:
            sources.run_cycle()
        except Exception:
            print("[ERROR] 监控周期执行失败:")
            traceback.print_exc()
        time.sleep(MONITOR_INTERVAL * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if ENABLE_MONITOR:
        threading.Thread(target=_monitor_loop, daemon=True).start()
    yield


app = FastAPI(title=SITE_NAME, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters.update(number=fmt_number, percent=fmt_percent, ms=fmt_ms, domain=domain_of)
templates.env.globals.update(
    site_name=SITE_NAME,
    current_year=time.strftime("%Y"),
    monitor_interval=MONITOR_INTERVAL,
)


def _base_context(request: Request, active: str) -> dict:
    stats = db.global_stats()
    return {
        "request": request,
        "active": active,
        "stats": stats,
        "maintenance": db.get_meta("last_check") or stats["last_updated"],
    }


def _decorate(source: dict) -> dict:
    item = dict(source)
    item["domain"] = domain_of(item.get("url", ""))
    item["resources_text"] = fmt_number(item.get("total_resources") or 0)
    item["uptime_text"] = fmt_percent(item.get("uptime") or 0)
    item["response_text"] = fmt_ms(item.get("response_time"))
    item["status_label"] = "正常" if item.get("is_alive") else "故障"
    item["status_class"] = "ok" if item.get("is_alive") else "bad"
    if item.get("is_alive") and (item.get("uptime") or 0) < 99:
        item["status_label"] = "警告"
        item["status_class"] = "warn"
    item["api_type_label"] = (item.get("api_type") or "json").upper()
    return item


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    context = _base_context(request, "home")
    hot = [_decorate(item) for item in db.list_sources(sort="default", per_page=8)["items"]]
    stable = [_decorate(item) for item in db.list_sources(status="online", sort="uptime", per_page=8)["items"]]
    biggest = [_decorate(item) for item in db.list_sources(status="online", sort="resources", per_page=4)["items"]]
    context.update(
        hot=hot,
        stable=stable,
        biggest=biggest,
        tags=db.all_tags()[:16],
    )
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/discover", response_class=HTMLResponse)
def discover(
    request: Request,
    q: str = "",
    tag: str = "",
    status: str = Query("all", pattern="^(all|online|offline)$"),
    sort: str = Query("default", pattern="^(default|uptime|resources|speed|latest)$"),
    page: int = Query(1, ge=1),
):
    context = _base_context(request, "discover")
    result = db.list_sources(query=q.strip(), tag=tag, status=status, sort=sort, page=page, per_page=24)
    context.update(
        items=[_decorate(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        pages=result["pages"],
        q=q,
        tag=tag,
        status=status,
        sort=sort,
        tags=db.all_tags(),
    )
    return templates.TemplateResponse(request, "discover.html", context)


@app.get("/monitor", response_class=HTMLResponse)
def monitor(request: Request):
    context = _base_context(request, "monitor")
    items = [_decorate(item) for item in db.list_sources(sort="uptime", per_page=96)["items"]]
    daily = db.daily_availability_map(10)
    dates = recent_dates(10)

    trend = []
    for day in dates:
        total = alive = 0
        response_total = response_count = 0
        for source_days in daily.values():
            entry = source_days.get(day)
            if not entry:
                continue
            total += entry["total"]
            alive += entry["alive"]
            if entry["avg_response"]:
                response_total += entry["avg_response"]
                response_count += 1
        trend.append({
            "day": day,
            "label": day[5:],
            "rate": round(alive / total * 100, 1) if total else None,
            "avg_response": round(response_total / response_count) if response_count else None,
        })

    rows = []
    for item in items:
        days = []
        for day in dates:
            entry = daily.get(item["id"], {}).get(day)
            if not entry:
                days.append({"day": day, "state": "empty", "title": f"{day} 无记录"})
                continue
            rate = entry["alive"] / entry["total"] * 100 if entry["total"] else 0
            state = "ok" if rate >= 99 else ("warn" if rate >= 90 else "bad")
            label = {"ok": "正常", "warn": "警告", "bad": "故障"}[state]
            days.append({
                "day": day,
                "state": state,
                "title": f"{day} · {label} · {entry['alive']}/{entry['total']} 次成功 · {entry['avg_response']}ms",
            })
        item["days"] = days
        rows.append(item)

    context.update(items=rows, dates=dates, trend=trend)
    return templates.TemplateResponse(request, "monitor.html", context)


@app.get("/source/{slug}", response_class=HTMLResponse)
def source_detail(request: Request, slug: str):
    source = db.get_source_by_slug(slug)
    if not source:
        raise HTTPException(status_code=404, detail="资源站不存在")
    item = _decorate(source)
    summary = db.source_check_summary(item["id"], 30)
    history = db.source_history(item["id"], 10)
    recent = db.recent_checks(item["id"], 8)
    uptime = summary["uptime"] if summary["checks"] >= 5 and summary["uptime"] is not None else item.get("uptime")
    fault_days = sum(1 for day in history if not day["ok"])
    context = _base_context(request, "source")
    context.update(
        item=item,
        summary=summary,
        history=history,
        recent=recent,
        related=[_decorate(related) for related in db.related_sources(item, 8)],
        uptime_text=fmt_percent(uptime or 0),
        uptime_value=round(float(uptime or 0), 3),
        fault_days=fault_days,
        founded_year=db.estimate_founded_year(item),
        check_days=summary["days"] if summary["checks"] else 0,
    )
    return templates.TemplateResponse(request, "source.html", context)


@app.get("/top", response_class=HTMLResponse)
def top(
    request: Request,
    sort: str = Query("uptime", pattern="^(uptime|resources|speed|latest)$"),
):
    context = _base_context(request, "discover")
    result = db.list_sources(status="online", sort=sort, per_page=50)
    context.update(
        items=[_decorate(item) for item in result["items"]],
        sort=sort,
        total=result["total"],
    )
    return templates.TemplateResponse(request, "top.html", context)


@app.get("/tags", response_class=HTMLResponse)
def tags_page(request: Request):
    context = _base_context(request, "discover")
    context.update(tags=db.all_tags())
    return templates.TemplateResponse(request, "tags.html", context)


@app.get("/category/{tag}", response_class=HTMLResponse)
def category(
    request: Request,
    tag: str,
    status: str = Query("all", pattern="^(all|online|offline)$"),
    sort: str = Query("default", pattern="^(default|uptime|resources|speed|latest)$"),
    page: int = Query(1, ge=1),
):
    context = _base_context(request, "discover")
    result = db.list_sources(tag=tag, status=status, sort=sort, page=page, per_page=24)
    if not result["total"]:
        raise HTTPException(status_code=404, detail="该分类下暂无资源站")
    context.update(
        items=[_decorate(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        pages=result["pages"],
        q="",
        tag=tag,
        status=status,
        sort=sort,
        tags=db.all_tags(),
        category_name=tag,
    )
    return templates.TemplateResponse(request, "discover.html", context)


@app.get("/tutorial", response_class=HTMLResponse)
def tutorial_index(request: Request, level: str = ""):
    context = _base_context(request, "discover")
    items = content.TUTORIALS
    if level:
        items = [item for item in items if item["level"] == level]
    context.update(
        items=items,
        level=level,
        levels=sorted({item["level"] for item in content.TUTORIALS}),
    )
    return templates.TemplateResponse(request, "tutorial.html", context)


@app.get("/tutorial/{slug}", response_class=HTMLResponse)
def tutorial_detail(request: Request, slug: str):
    item = content.tutorial_map().get(slug)
    if not item:
        raise HTTPException(status_code=404, detail="教程不存在")
    context = _base_context(request, "discover")
    siblings = [entry for entry in content.TUTORIALS if entry["slug"] != slug][:4]
    context.update(item=item, siblings=siblings)
    return templates.TemplateResponse(request, "tutorial_detail.html", context)


@app.get("/article", response_class=HTMLResponse)
def article_index(request: Request, cat: str = ""):
    context = _base_context(request, "discover")
    items = content.articles_by_category(cat) if cat else content.ARTICLES
    context.update(
        items=items,
        cat=cat,
        categories=[
            dict(category, count=content.article_count(category["slug"]))
            for category in content.ARTICLE_CATEGORIES
        ],
        active_category=next((c for c in content.ARTICLE_CATEGORIES if c["slug"] == cat), None),
    )
    return templates.TemplateResponse(request, "article.html", context)


@app.get("/article/{slug}", response_class=HTMLResponse)
def article_detail(request: Request, slug: str):
    item = content.article_map().get(slug)
    if not item:
        raise HTTPException(status_code=404, detail="文章不存在")
    category = next((c for c in content.ARTICLE_CATEGORIES if c["slug"] == item["category"]), None)
    context = _base_context(request, "discover")
    context.update(
        item=item,
        category=category,
        related=[entry for entry in content.ARTICLES
                 if entry["category"] == item["category"] and entry["slug"] != slug][:3],
    )
    return templates.TemplateResponse(request, "article_detail.html", context)


@app.get("/compare", response_class=HTMLResponse)
def compare(
    request: Request,
    slugs: str = "",
    pick1: str = "",
    pick2: str = "",
    pick3: str = "",
    pick4: str = "",
):
    context = _base_context(request, "discover")
    picked = [slug.strip() for slug in slugs.split(",") if slug.strip()]
    for value in (pick1, pick2, pick3, pick4):
        if value and value not in picked:
            picked.append(value)
    picked = picked[:4]
    items = []
    for slug in picked:
        source = db.get_source_by_slug(slug)
        if source:
            item = _decorate(source)
            summary = db.source_check_summary(item["id"], 30)
            item["uptime_30d"] = summary["uptime"]
            item["checks_30d"] = summary["checks"]
            items.append(item)

    options = [_decorate(source) for source in db.list_sources(sort="default", per_page=96)["items"]]
    context.update(
        items=items,
        options=options,
        slugs=",".join(picked),
        slots=range(4),
    )
    return templates.TemplateResponse(request, "compare.html", context)


@app.get("/download", response_class=HTMLResponse)
def download_index(request: Request, site: str = ""):
    context = _base_context(request, "discover")
    items = [_decorate(item) for item in db.sources_with_api()]
    focus = next((item for item in items if item["slug"] == site), None)
    context.update(
        items=items,
        api_total=len(items),
        online_total=sum(1 for item in items if item["is_alive"]),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        focus=focus,
        focus_site=site,
    )
    return templates.TemplateResponse(request, "download.html", context)


def _speed_level(response_time: float | int | None) -> str:
    value = float(response_time or 0)
    if not value:
        return "unknown"
    if value <= 1500:
        return "fast"
    if value <= 3000:
        return "medium"
    return "slow"


def _pct(value) -> str:
    number = round(float(value or 0), 3)
    return "{}%".format(("%.3f" % number).rstrip("0").rstrip("."))


def _cms_entry(item: dict) -> dict:
    """生成与苹果CMS 批量导入兼容的单条采集配置。"""
    return {
        "name": item["name"],
        "api": item["api"],
        "apiType": (item.get("api_type") or "json").lower(),
        "uptime": _pct(item.get("uptime")),
        "speed": _speed_level(item.get("response_time")),
        "totalResources": item["total_resources"],
        "categories": [],
    }


@app.get("/download/cms-interfaces.json")
def download_cms_json(site: str = ""):
    items = [_decorate(item) for item in db.sources_with_api()]
    if site:
        items = [item for item in items if item["slug"] == site]
    payload = [_cms_entry(item) for item in items]
    return JSONResponse(
        payload,
        headers={"Content-Disposition": 'attachment; filename="cms-interfaces.json"'},
    )


@app.get("/download/tvbox.json")
def download_tvbox_json():
    items = [_decorate(item) for item in db.sources_with_api() if item["is_alive"]]
    payload = {
        "sites": [
            {
                "key": item["slug"],
                "name": item["name"],
                "type": 0,
                "api": item["api"],
                "searchable": 1,
                "quickSearch": 1,
                "filterable": 1,
            }
            for item in items
        ]
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": 'attachment; filename="tvbox-sites.json"'},
    )


@app.get("/download/cms-interfaces.txt", response_class=PlainTextResponse)
def download_cms_txt():
    lines = [
        "# {} 苹果CMS 一键采集接口配置".format(SITE_NAME),
        "# 生成时间：{}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "# 格式：采集站名称|API地址|接口类型|可用率",
        "",
    ]
    for item in db.sources_with_api():
        decorated = _decorate(item)
        lines.append("{}|{}|{}|{}".format(
            decorated["name"],
            decorated["api"],
            (decorated.get("api_type") or "json").lower(),
            _pct(decorated.get("uptime")),
        ))
    return PlainTextResponse(
        "\n".join(lines) + "\n",
        headers={"Content-Disposition": 'attachment; filename="cms-interfaces.txt"'},
    )


@app.get("/go/{slug}")
def go_source(slug: str):
    """跳转到资源站官网，同时保留详情页入口。"""
    source = db.get_source_by_slug(slug)
    if not source or not source.get("url"):
        raise HTTPException(status_code=404, detail="资源站不存在")
    return RedirectResponse(source["url"], status_code=307)


@app.get("/api/v1/sources")
def api_sources(limit: int = Query(100, ge=1, le=500)):
    items = [_decorate(item) for item in db.all_active_sources()[:limit]]
    return JSONResponse({"success": True, "total": len(items), "data": items})


@app.get("/api/v1/online")
def api_online():
    items = [_decorate(item) for item in db.all_active_sources() if item.get("is_alive")]
    return JSONResponse({"timestamp": db.get_meta("last_check"), "total": len(items), "data": items})


@app.get("/api/v1/offline")
def api_offline():
    items = [_decorate(item) for item in db.all_active_sources() if not item.get("is_alive")]
    return JSONResponse({"timestamp": db.get_meta("last_check"), "total": len(items), "data": items})


@app.get("/api/v1/stats")
def api_stats():
    return JSONResponse({"success": True, "stats": db.global_stats(), "tags": db.all_tags()})


@app.get("/api/v1/sources/{slug}")
def api_source(slug: str):
    source = db.get_source_by_slug(slug)
    if not source:
        raise HTTPException(status_code=404, detail="资源站不存在")
    return JSONResponse({
        "success": True,
        "data": _decorate(source),
        "summary": db.source_check_summary(source["id"], 30),
        "history": db.source_history(source["id"], 10),
    })


@app.get("/api/test/{slug}")
def api_test(slug: str):
    """测试本站收录的采集接口，避免被用来探测任意地址。"""
    source = db.get_source_by_slug(slug)
    if not source:
        raise HTTPException(status_code=404, detail="资源站不存在")
    target = source.get("api") or source.get("url")
    if not target:
        return JSONResponse({"success": False, "error": "该资源站没有配置接口地址"})
    try:
        started = time.time()
        response = requests.get(
            target,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            },
            timeout=12,
            allow_redirects=True,
        )
        elapsed = round((time.time() - started) * 1000)
        payload = None
        keys: list[str] = []
        try:
            payload = response.json()
            if isinstance(payload, dict):
                keys = list(payload.keys())[:8]
        except ValueError:
            payload = None
        return JSONResponse({
            "success": True,
            "url": target,
            "status_code": response.status_code,
            "elapsed_ms": elapsed,
            "content_type": response.headers.get("content-type", ""),
            "top_keys": keys,
            "alive": response.status_code < 400 or response.status_code in (401, 403),
            "preview": "" if payload is None else str(payload)[:300],
        })
    except Exception as exc:
        return JSONResponse({"success": False, "url": target, "error": str(exc)[:200]})


@app.get("/healthz")
def healthz():
    stats = db.global_stats()
    return {"ok": True, "sources": stats["total"], "last_check": db.get_meta("last_check")}

