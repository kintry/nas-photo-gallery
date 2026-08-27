# -*- coding: utf-8 -*-
"""
NAS相册 配置文件（示例模板）
================================
安装后请复制本文件为 config.py，并按你的照片存放位置修改 PHOTO_ROOTS。

⚠️ 本文件是模板，不含任何真实路径。真实的 config.py 由安装向导生成或在首次运行时创建，
   **切勿**把含真实路径的 config.py 提交到 Git（已加入 .gitignore）。

照片根目录配置示例：
  - Windows:  r'D:\\相册库',  r'D:\\我的照片'
  - Linux/Mac: r'/mnt/photo/相册',  r'/home/user/Pictures'
每个根目录下的一级子目录会作为一个相册（含其下所有子目录的照片）。
"""
import os

# ── 照片根目录列表（每个根的一级子目录 = 一个相册）──
# 添加或删除目录即可增减相册；被停用的目录会保留在历史中，可随时重新启用（不会物理删除照片）。
PHOTO_ROOTS = [
    r'./photos',          # 示例：仓库自带的示例照片目录（可删除；或改成你的真实相册路径）
]

# ── 缩略图/缓存目录（默认自动选择系统缓存位置，一般无需修改）──
# 若想自定义缓存位置（例如磁盘较大），取消注释并填写：
# CACHE_DIR = r'/path/to/your/cache'      # Linux/Mac
# CACHE_DIR = r'D:\\nas-photo-cache'      # Windows

# ── 服务端口 ──
PORT = 5000

# ── 管理面板端口 ──
MANAGER_PORT = 5001
