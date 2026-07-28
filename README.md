# NAS Photo Gallery

跨平台局域网相册 Web 应用。在家庭网络中任意设备上浏览照片和视频。

## 核心特性

- **📸 相册浏览** — 相册网格展示，照片瀑布流懒加载
- **🎬 视频支持** — 在线播放 + ffmpeg 缩略图
- **🖥️ 跨平台** — 同一套代码支持 Linux / Windows / macOS
- **📊 缩略图进度条** — 首页实时显示缩略图生成进度
- **🌙 夜间预生成** — 凌晨自动全量生成缩略图
- **🔄 设备切换** — 局域网内多设备相册一键切换
- **📱 移动端适配** — 手机浏览器友好界面

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
