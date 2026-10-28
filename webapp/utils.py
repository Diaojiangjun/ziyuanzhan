"""通用工具：slug 生成与展示格式化。"""

import re
from datetime import datetime, timedelta

from pypinyin import lazy_pinyin


def generate_slug(name: str) -> str:
    """把资源站名称转成拼音 slug（按词组转写，避免多音字错误）。"""
    slug = "".join(lazy_pinyin(name)).lower()
    slug = re.sub(r"[^a-z0-9\-]+", "", slug)
    return slug or "source"


def fmt_number(value) -> str:
    """把数量格式化为 万/亿。"""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return "-"
    if number >= 100000000:
        return f"{number / 100000000:.1f}亿"
    if number >= 10000:
        return f"{number / 10000:.1f}万"
    return str(number)


def fmt_percent(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    return f"{text}%"


def fmt_ms(value) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return "-"
    return f"{number}ms" if number else "-"


def parse_datetime(value: str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def recent_dates(days: int) -> list[str]:
    today = datetime.now().date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def domain_of(url: str) -> str:
    from urllib.parse import urlparse

    try:
        host = urlparse(url).netloc
    except ValueError:
        return ""
    return host or url
