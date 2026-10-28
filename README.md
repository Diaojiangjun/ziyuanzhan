# ziyuanzhan - 资源站监测

ziyuanzu.com 资源站实时监测面板。通过 [ziyuanzu API](https://www.ziyuanzu.com/api/v1) 获取资源站数据，定期检测各站点可用性，生成静态 JSON + HTML 页面。

## 工作原理

```
GitHub Actions (每6小时) → monitor.py → fetch ziyuanzu API → 健康检查 → 生成静态文件 → GitHub Pages 自动部署
```

**零服务器、零运行时、零成本。**

## 静态文件

部署到 GitHub Pages 后，可通过以下 URL 访问：

| 文件 | URL | 说明 |
|------|-----|------|
| `docs/index.html` | `https://mylazily.github.io/ziyuanzhan/` | 可视化监控面板 |
| `data/latest.json` | `https://mylazily.github.io/ziyuanzhan/data/latest.json` | 全部资源站数据 |
| `data/online.json` | `https://mylazily.github.io/ziyuanzhan/data/online.json` | 在线资源站 |
| `data/offline.json` | `https://mylazily.github.io/ziyuanzhan/data/offline.json` | 离线资源站 |
| `data/stats.json` | `https://mylazily.github.io/ziyuanzhan/data/stats.json` | 统计数据 |
| `data/fastest.json` | `https://mylazily.github.io/ziyuanzhan/data/fastest.json` | 响应最快 Top 20 |
| `data/top-rated.json` | `https://mylazily.github.io/ziyuanzhan/data/top-rated.json` | 高评分 Top 20 |

## AI Agent 使用示例

```python
import requests

# 获取所有在线资源站
resp = requests.get("https://mylazily.github.io/ziyuanzhan/data/online.json")
data = resp.json()
print(f"在线资源站: {data['total']} 个")
for r in data["data"][:5]:
    print(f"  {r['name']} - {r['link']}")

# 获取统计数据
stats = requests.get("https://mylazily.github.io/ziyuanzhan/data/stats.json").json()
print(f"在线率: {stats['overview']['onlineRate']}%")
```

## 本地运行

```bash
pip install requests beautifulsoup4 lxml
python monitor.py
```

生成的文件：
- `docs/index.html` — 监控面板
- `docs/data/*.json` — 各类 JSON 数据

## 复刻站点（自建服务器部署）

`webapp/` 是按 ziyuanzu.com 结构复刻的独立站点：FastAPI + SQLite，包含首页、发现、排行榜、标签分类、资源站详情、实时监控、采集教程、知识库、资源站对比与接口配置下载，并提供 JSON 接口。

```bash
# 方式一：Docker Compose
docker compose up -d --build
# 访问 http://服务器IP:8000

# 方式二：直接运行
pip install -r requirements.txt
uvicorn webapp.main:app --host 0.0.0.0 --port 8000
```

首次启动会把 `docs/data/sources.json` 导入数据库，随后每 2 小时自动同步 API 并探测全部接口，数据保存在 `data/site.db`。

### GitHub Actions 构建镜像 + 服务器拉取

`.github/workflows/docker.yml` 在推送到 `main` 后自动构建镜像并推送到 GitHub 容器仓库（GHCR），不需要在服务器上装 Python。

1. 推送到 `main` 分支，等待 Actions 中的 `Build and Push Image` 完成。
2. 在仓库 `Packages` 里把该镜像设为 Public，或先在服务器上登录：

```bash
echo "<你的 GitHub PAT>" | docker login ghcr.io -u <你的用户名> --password-stdin
```

3. 服务器上拉取并运行（把 `OWNER/REPO` 换成实际仓库名，小写）：

```bash
docker pull ghcr.io/owner/repo:latest
docker run -d --name ziyuanzhan --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/data:/app/webapp/data \
  -e SITE_NAME=资源组 \
  ghcr.io/owner/repo:latest
```

也可以用 Compose 拉取镜像而不在本地构建：

```bash
IMAGE=ghcr.io/owner/repo:latest docker compose up -d --no-build
```

镜像标签包含 `latest` 与提交短哈希（如 `sha-1a2b3c4`），需要回滚时指定哈希即可。GitHub Pages 只托管 `docs/` 静态监控页，`webapp/` 必须跑在容器或服务器上。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SITE_NAME` | 资源组 | 站点名称 |
| `MONITOR_INTERVAL_MINUTES` | 120 | 同步与探测间隔 |
| `ENABLE_MONITOR` | 1 | 设为 0 时关闭后台定时任务 |
| `DB_PATH` | `webapp/data/site.db` | SQLite 路径 |
| `SEED_FILE` | `docs/data/sources.json` | 首次启动的种子数据 |

页面与接口：

| 路径 | 说明 |
|------|------|
| `/` | 首页 |
| `/discover` | 资源站列表、搜索、标签与状态筛选 |
| `/top` | 排行榜（可用率 / 资源量 / 响应速度 / 最近更新） |
| `/tags` | 全部标签云 |
| `/category/{tag}` | 按标签查看资源站 |
| `/source/{slug}` | 资源站详情、接口测试、历史记录 |
| `/monitor` | 实时监控大屏 |
| `/compare` | 最多 4 个资源站并排对比 |
| `/tutorial`、`/tutorial/{slug}` | 采集教程列表与详情 |
| `/article`、`/article/{slug}` | 知识库列表与详情 |
| `/download` | 苹果CMS 一键采集配置页（支持 `?site=slug` 聚焦单个站点） |
| `/download/cms-interfaces.json` | 苹果CMS 批量导入 JSON（数组，兼容 name/api/apiType/uptime/speed/totalResources） |
| `/download/cms-interfaces.txt` | 苹果CMS / 海洋CMS 批量导入 TXT（`名称\|API\|类型\|可用率`） |
| `/download/tvbox.json` | TVBox 配置（仅在线接口） |
| `/go/{slug}` | 跳转到资源站官网 |
| `/api/v1/sources` | 全部资源站 JSON |
| `/api/v1/online`、`/api/v1/offline` | 在线/故障资源站 |
| `/api/v1/stats` | 统计数据 |

Nginx 反向代理示例：

```nginx
server {
    listen 80;
    server_name example.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 项目结构

```
ziyuanzhan/
├── monitor.py               # 监测脚本（GitHub Actions 使用）
├── webapp/                  # 自建站点（FastAPI + SQLite）
│   ├── main.py              # 路由与接口
│   ├── db.py                # 数据层
│   ├── sources.py           # API 同步与可用性探测
│   ├── content.py           # 教程与知识库静态内容
│   ├── templates/           # 页面模板
│   └── static/              # 样式与脚本
├── Dockerfile               # 站点镜像
├── docker-compose.yml       # 一键部署
├── requirements.txt         # Python 依赖
├── .github/workflows/
│   └── monitor.yml          # GitHub Actions 定时监控 + 部署
└── docs/                    # GitHub Pages 根目录
    ├── index.html           # 静态监控面板
    └── data/
        ├── latest.json      # 全部数据
        ├── online.json      # 在线资源站
        ├── offline.json     # 离线资源站
        ├── stats.json       # 统计数据
        ├── fastest.json     # 最快资源站
        ├── top-rated.json   # 高评分资源站
        └── monitor_*.json   # 历史快照
```

## 数据来源

- [ziyuanzu.com](https://www.ziyuanzu.com) API: `https://www.ziyuanzu.com/api/v1/sources`
- 本项目为第三方监测工具，与 ziyuanzu.com 官方无关
