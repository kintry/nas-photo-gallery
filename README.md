# NAS Photo Gallery

跨平台局域网相册 Web 应用。在家庭网络中任意设备上浏览照片和视频。

## 核心特性

- **📸 相册浏览** — 相册网格展示，照片瀑布流懒加载
- **🎬 视频支持** — 在线播放 + ffmpeg 缩略图
- **🖥️ 跨平台** — 同一套代码支持 Linux / Windows / macOS
- **⚡ 快速加载 (v5.0)** — 封面走三层缓存（内存→缓存文件→磁盘），相册列表首屏毫秒级返回
- **📊 缩略图进度条** — 首页实时显示缩略图生成进度
- **🌙 夜间预生成** — 凌晨自动全量生成缩略图
- **🔄 设备切换** — 局域网内多设备相册一键切换
- **📁 照片目录管理** — Web 界面运行时增删照片根目录，无需 SSH/重启
- **📱 移动端适配** — 手机浏览器友好界面

## 性能优化（v5.0，2026-08-16）

**核心改进：`/api/albums` 从 17.6s 降到 18ms（约 1000 倍）。**

当相册数量达到数百个（如 380+）时，原实现每次请求都对每个相册实时扫描磁盘找出封面照片，导致首页"加载中…"卡十几秒。优化方案：

```
① 内存缓存   _COVER_CACHE   — 第二次起 O(1) 秒回
② 缓存文件   photo_lists/*  — 直接读已扫描的照片列表文件（忽略24h过期，
                              封面只需任一媒体，无需最新）
③ 磁盘回退   仅当①②都失效时才遍历目录（罕见）
```

封面数据来源从"实时遍历 USB HDD"改为"读取已存在的扫描缓存"，磁盘 I/O 从数百次降到 0-1 次。



## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/kintry/nas-photo-gallery.git
cd nas-photo-gallery
```

### 2. 安装依赖

```bash
pip install flask pillow imageio-ffmpeg
```

### 3. 配置

编辑 `config.py`，设置照片目录路径：

```python
PHOTO_ROOTS = [
    '/path/to/your/photos',       # Linux
    # 'D:/Pictures',              # Windows
    # '/Volumes/PhotoDisk',       # macOS
]
CACHE_DIR = Path('/path/to/cache')  # 缩略图缓存目录
```

### 4. 启动

```bash
python app.py
```

浏览器打开 `http://设备IP:5000`

### 5. 可选：夜间缩略图预生成

设置 cron 任务每日凌晨执行：

```bash
0 3 * * * cd /path/to/app && python nightly_precache.py
```

## 目录结构

```
nas-photo-gallery/
├── app.py                   # Flask 主程序
├── config.py                # 外部配置文件
├── nightly_precache.py      # 夜间缩略图预生成
├── thumb_worker.py          # 缩略图生成 worker
├── plat/                    # 平台适配层
│   ├── __init__.py
│   ├── linux.py             # Linux 适配
│   ├── windows.py           # Windows 适配
│   └── macos.py             # macOS 适配
├── static/
│   ├── app.js               # 前端 JS
│   └── style.css            # 样式
├── templates/
│   └── index.html           # 前端页面
└── requirements.txt         # Python 依赖
```

## 依赖

- Python 3.10+
- Flask
- Pillow（照片缩略图）
- imageio-ffmpeg（可选，视频缩略图）
- ffmpeg（可选，视频缩略图，需系统安装）

## 许可

MIT License
