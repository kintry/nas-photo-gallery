#!/usr/bin/env python3
"""
NAS相册 Web 服务 v4 — 跨平台版

平台无关的核心文件。平台差异通过 platform/ 模块自动适配。
当前支持：Linux / Windows / macOS

运行方式：
    python3 app.py         # 前台运行
    python3 app.py --daemon  # 后台运行（fork）
"""

import sys
import os
import json
import time
import hashlib
import io
import threading
import re
import mimetypes
import argparse
from pathlib import Path
from datetime import datetime

# ── 平台适配层 ──
# 注入 platform 模块到 sys.path，确保各种启动方式都能找到
_script_dir = Path(__file__).parent
_plat_dir = _script_dir / 'plat'
if _plat_dir.exists():
    sys.path.insert(0, str(_script_dir))

from plat import detect_os, get_platform, norm_path, join_path, ensure_config_dir

# 获取当前平台模块
_plat = get_platform()

# ═══════════════════════════════════════════
# 配置（可通过 config.py 或环境变量覆盖）
# ═══════════════════════════════════════════

# 尝试加载 config.py
PHOTO_ROOTS = []
CACHE_DIR = _plat.get_default_cache_dir()

_config_py = _script_dir / 'config.py'
if _config_py.exists():
    try:
        exec(_config_py.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[W] config.py 加载失败: {e}", flush=True)

if not PHOTO_ROOTS:
    PHOTO_ROOTS = _plat.get_default_photo_roots()

# 确保 CACHE_DIR 是 Path 对象
CACHE_DIR = Path(CACHE_DIR) if not isinstance(CACHE_DIR, Path) else CACHE_DIR

# 环境变量覆盖
HOST = os.environ.get('NAS_PHOTO_HOST', '0.0.0.0')
PORT = int(os.environ.get('NAS_PHOTO_PORT', '5000'))
_override_cache = os.environ.get('NAS_PHOTO_CACHE_DIR', '')
if _override_cache:
    CACHE_DIR = Path(_override_cache)

# ── 缓存目录 ──
THUMB_DIR = CACHE_DIR / 'thumbs'
THUMB_DIR_SMALL = THUMB_DIR / 'sm'
INDEX_PATH = CACHE_DIR / 'index.json'
PHOTO_LIST_DIR = CACHE_DIR / 'photo_lists'
LIKES_PATH = _script_dir / 'likes.json'

# ── 支持的视频 & 照片格式 ──
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.mts', '.m2ts', '.3gp', '.wmv', '.mpg', '.mpeg'}
PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(THUMB_DIR_SMALL, exist_ok=True)
os.makedirs(PHOTO_LIST_DIR, exist_ok=True)

# MIME 类型注册
mimetypes.add_type('video/quicktime', '.mov')
mimetypes.add_type('video/x-msvideo', '.avi')
mimetypes.add_type('video/x-matroska', '.mkv')
mimetypes.add_type('video/mp2t', '.mts')
mimetypes.add_type('video/mp2t', '.m2ts')
mimetypes.add_type('video/3gpp', '.3gp')
mimetypes.add_type('video/x-ms-wmv', '.wmv')
mimetypes.add_type('video/mpeg', '.mpg')
mimetypes.add_type('video/mpeg', '.mpeg')

_os_type = detect_os()


# ═══════════════════════════════════════════
# 文件读写（平台无关）
# ═══════════════════════════════════════════

def _read_raw(local_path):
    """读取文件字节"""
    return Path(local_path).read_bytes()


RAW_MEM_CACHE = {}
RAW_CACHE_MAX = 50

def _get_raw_cached(local_path):
    now = time.time()
    if local_path in RAW_MEM_CACHE:
        data, ts = RAW_MEM_CACHE[local_path]
        RAW_MEM_CACHE[local_path] = (data, now)
        return data
    data = _read_raw(local_path)
    _put_mem_cache(local_path, data)
    return data

def _put_mem_cache(path, data):
    while len(RAW_MEM_CACHE) >= RAW_CACHE_MAX:
        oldest_key = min(RAW_MEM_CACHE, key=lambda k: RAW_MEM_CACHE[k][1])
        del RAW_MEM_CACHE[oldest_key]
    RAW_MEM_CACHE[path] = (data, time.time())


def _is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS

def _is_photo(path):
    return Path(path).suffix.lower() in PHOTO_EXTS

def _is_media(path):
    return _is_photo(path) or _is_video(path)

def _get_media_type(path):
    ext = Path(path).suffix.lower()
    if ext in PHOTO_EXTS:
        return 'photo'
    if ext in VIDEO_EXTS:
        return 'video'
    return 'unknown'


# ═══════════════════════════════════════════
# 相册扫描（平台无关，路径由 PHOTO_ROOTS 决定）
# ═══════════════════════════════════════════

def _get_photo_list_cache(album_path):
    now = time.time()
    cache_path = PHOTO_LIST_DIR / f"{hashlib.md5(album_path.encode()).hexdigest()}.json"
    if album_path in PHOTO_LIST_CACHE:
        entry = PHOTO_LIST_CACHE[album_path]
        if now - entry['ts'] < 86400:
            return entry['photos']
    if cache_path.exists():
        mtime = cache_path.stat().st_mtime
        if now - mtime < 86400:
            photos = json.loads(cache_path.read_text(encoding='utf-8'))
            PHOTO_LIST_CACHE[album_path] = {'photos': photos, 'ts': now}
            return photos
    return None

def _save_photo_list_cache(album_path, photos):
    cache_path = PHOTO_LIST_DIR / f"{hashlib.md5(album_path.encode()).hexdigest()}.json"
    cache_path.write_text(json.dumps(photos, ensure_ascii=False), encoding='utf-8')
    PHOTO_LIST_CACHE[album_path] = {'photos': photos, 'ts': time.time()}


PHOTO_LIST_CACHE = {}

def _get_first_photo_cover(album_path):
    """从目录取第一个可用媒体文件做封面"""
    album = Path(album_path)
    if not album.exists():
        return None
    first_photo = None
    first_video = None
    for fp in sorted(album.iterdir()):
        if not fp.is_file():
            continue
        fn = fp.name
        if fn.startswith('.') or fn.startswith('._'):
            continue
        ext = fp.suffix.lower()
        if ext in PHOTO_EXTS:
            if first_photo is None:
                try:
                    st = fp.stat()
                    first_photo = {
                        "filename": fn, "path": str(fp),
                        "size": st.st_size, "mtime": st.st_mtime,
                        "id": hashlib.md5(str(fp).encode()).hexdigest()[:12],
                        "type": "photo",
                    }
                except:
                    pass
        elif ext in VIDEO_EXTS:
            if first_video is None:
                try:
                    st = fp.stat()
                    first_video = {
                        "filename": fn, "path": str(fp),
                        "size": st.st_size, "mtime": st.st_mtime,
                        "id": hashlib.md5(str(fp).encode()).hexdigest()[:12],
                        "type": "video",
                    }
                except:
                    pass
        if first_photo:
            break
    if first_photo:
        return first_photo
    if first_video:
        return first_video
    for sub in sorted(album.iterdir()):
        if sub.is_dir() and not sub.name.startswith("."):
            result = _get_first_photo_cover(str(sub))
            if result:
                return result
    return None


def scan_photos_local(album_path, page=1, per_page=20):
    """获取某个相册的照片+视频列表（带缓存）"""
    cached = _get_photo_list_cache(album_path)
    if cached is not None:
        total = len(cached)
        start = (page - 1) * per_page
        end = start + per_page
        return cached[start:end], total

    album = Path(album_path)
    if not album.exists():
        return [], 0

    items = []
    for fp in album.rglob('*'):
        if not fp.is_file():
            continue
        fn = fp.name
        if fn.startswith('.') or fn.startswith('._'):
            continue
        ext = fp.suffix.lower()
        if ext not in PHOTO_EXTS and ext not in VIDEO_EXTS:
            continue
        try:
            st = fp.stat()
            items.append({
                'filename': fn,
                'path': str(fp),
                'size': st.st_size,
                'mtime': st.st_mtime,
                'id': hashlib.md5(str(fp).encode()).hexdigest()[:12],
                'type': _get_media_type(str(fp)),
            })
        except:
            continue

    items.sort(key=lambda x: x['mtime'], reverse=True)
    _save_photo_list_cache(album_path, items)

    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total


def scan_albums_local():
    """扫描所有配置的相册目录"""
    albums = []
    for root in PHOTO_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            print(f"  [W] 路径不存在 {root}", flush=True)
            continue
        for entry in root_path.iterdir():
            name = entry.name
            if name.startswith('.') or name.startswith('$') or name in (
                'System Volume Information', '@eaDir', 'FOUND.000', '$RECYCLE.BIN'
            ):
                continue
            if entry.is_dir():
                img_count = sum(1 for f in entry.rglob('*') 
                               if f.suffix.lower() in PHOTO_EXTS and not f.name.startswith('._'))
                vid_count = sum(1 for f in entry.rglob('*') 
                               if f.suffix.lower() in VIDEO_EXTS and not f.name.startswith('._'))
                total_media = img_count + vid_count
                if total_media > 0:
                    cover = _get_first_photo_cover(str(entry))
                    albums.append({
                        'name': name,
                        'path': str(entry),
                        'photo_count': total_media,
                        'photo_count_only': img_count,
                        'video_count': vid_count,
                        'root': root_path.name,
                        'cover': cover,
                    })
                    print(f"  [OK] {name}: {img_count}照片 + {vid_count}视频", flush=True)
    return albums


# ═══════════════════════════════════════════
# 缩略图生成
# ═══════════════════════════════════════════

from PIL import Image, ImageFile, ImageDraw
ImageFile.LOAD_TRUNCATED_IMAGES = True

def _find_ffmpeg():
    """跨平台查找 ffmpeg"""
    import shutil
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        return ffmpeg
    # Windows 常见路径
    for p in [
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
    ]:
        if Path(p).exists():
            return p
    return None


def get_thumbnail(local_path, size=400):
    """生成缩略图（照片直接缩略，视频用ffmpeg截帧）"""
    filename = Path(local_path).name
    if filename.startswith('._') or filename.startswith('.'):
        return b''
    cache_key = hashlib.md5(local_path.encode()).hexdigest()
    cache_path = THUMB_DIR_SMALL / f"{cache_key}.jpg"

    if cache_path.exists() and cache_path.stat().st_size > 100:
        return cache_path.read_bytes()

    # 视频用 ffmpeg 截第一帧
    if _is_video(local_path):
        import subprocess as sp
        ffmpeg_path = _find_ffmpeg()
        if ffmpeg_path:
            try:
                thumb_tmp = THUMB_DIR_SMALL / f"{cache_key}_tmp.jpg"
                r = sp.run(
                    [ffmpeg_path, '-y', '-i', local_path, '-vframes', '1',
                     '-vf', f'scale={size}:-1', '-q:v', '5', str(thumb_tmp)],
                    capture_output=True, timeout=30
                )
                if r.returncode == 0 and thumb_tmp.exists() and thumb_tmp.stat().st_size > 1000:
                    data = thumb_tmp.read_bytes()
                    thumb_tmp.rename(cache_path)
                    return data
                if thumb_tmp.exists():
                    thumb_tmp.unlink()
            except:
                pass
        # ffmpeg 不可用或失败：生成带播放按钮的占位缩略图
        try:
            img = Image.new('RGB', (size, size), (20, 20, 40))
            draw = ImageDraw.Draw(img)
            cx, cy = size // 2, size // 2
            r = size // 5
            for ox in range(-r, r + 1):
                for oy in range(-r, r + 1):
                    if ox * ox + oy * oy <= r * r:
                        draw.point((cx + ox, cy + oy), fill=(52, 152, 219))
            tri_size = r // 2
            tri_points = [
                (cx - tri_size // 2, cy - tri_size),
                (cx + tri_size, cy),
                (cx - tri_size // 2, cy + tri_size),
            ]
            draw.polygon(tri_points, fill=(255, 255, 255))
            out = io.BytesIO()
            img.save(out, 'JPEG', quality=70)
            return out.getvalue()
        except:
            pass

    # 照片缩略图
    try:
        img = Image.open(local_path)
        w, h = img.size
        if size < w:
            ratio = size / w
            img = img.resize((size, int(h * ratio)), Image.LANCZOS)
        quality = 80
        out = io.BytesIO()
        img.save(out, 'JPEG', quality=quality)
        data = out.getvalue()
        if len(data) > 100:
            cache_path.write_bytes(data)
        return data
    except:
        return b''


def batch_precache_thumbnails(albums, max_per_album=20):
    """后台批量预生成缩略图"""
    print("\n[..] 后台批量预生成缩略图...")
    total_done = 0
    total_albums = 0
    for album in albums:
        photos_cache = _get_photo_list_cache(album['path'])
        if not photos_cache:
            photos_cache, _ = scan_photos_local(album['path'], 1, 999999)
        if not photos_cache:
            continue
        to_gen = []
        for p in photos_cache[:max_per_album]:
            if Path(p['path']).name.startswith('.'):
                continue
            if p.get('size', 0) > 50_000_000:
                continue
            ck = hashlib.md5(p['path'].encode()).hexdigest()
            sm = THUMB_DIR_SMALL / f"{ck}.jpg"
            if not sm.exists():
                to_gen.append(p['path'])
        if not to_gen:
            continue
        total_albums += 1
        batch = to_gen[:max_per_album]
        done = 0
        for path in batch:
            try:
                get_thumbnail(path, size=400)
                done += 1
                total_done += 1
                if total_done % 30 == 0:
                    print(f"  ...已预生成 {total_done} 张", flush=True)
            except:
                pass
    print(f"  [OK] 预生成完成: {total_albums} 个相册, {total_done} 张", flush=True)
    
    # 视频缩略图
    print("\n[..] 后台预生成视频缩略图...")
    vid_done = 0
    vid_albums = 0
    for album in albums:
        photos_cache = _get_photo_list_cache(album['path'])
        if not photos_cache:
            photos_cache, _ = scan_photos_local(album['path'], 1, 999999)
        if not photos_cache:
            continue
        vid_to_gen = []
        for p in photos_cache:
            if p.get('type') == 'video':
                if Path(p['path']).name.startswith('.'):
                    continue
                if p.get('size', 0) > 200_000_000:
                    continue
                ck = hashlib.md5(p['path'].encode()).hexdigest()
                sm = THUMB_DIR_SMALL / f"{ck}.jpg"
                if not sm.exists() or sm.stat().st_size < 1000:
                    vid_to_gen.append(p['path'])
                if len(vid_to_gen) >= 5:
                    break
        if not vid_to_gen:
            continue
        vid_albums += 1
        for path in vid_to_gen:
            try:
                data = get_thumbnail(path, size=400)
                if data and len(data) > 1000:
                    vid_done += 1
                    if vid_done % 10 == 0:
                        print(f"  ...已预生成 {vid_done} 个视频缩略图", flush=True)
            except:
                pass
    print(f"  [OK] 视频缩略图预生成完成: {vid_albums} 个相册, {vid_done} 个视频", flush=True)


# ══════════════════════════════════════════
#  Flask Web 服务（完全平台无关）
# ══════════════════════════════════════════

def create_app():
    from flask import Flask, jsonify, send_file, request, render_template, abort, Response

    app = Flask(__name__,
                template_folder=str(_script_dir / 'templates'),
                static_folder=str(_script_dir / 'static'))

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/album/<path:album_path>')
    def album_view(album_path):
        return render_template('index.html', album=album_path)

    @app.route('/view')
    def viewer():
        return render_template('index.html',
                             photo_id=request.args.get('img', ''),
                             album=request.args.get('album', ''))

    @app.route('/api/hostname')
    def api_hostname():
        import socket
        return jsonify({'hostname': socket.gethostname()})

    @app.route('/api/albums')
    def api_albums():
        albums = app.config.get('ALBUM_CACHE', [])
        if not albums and INDEX_PATH.exists():
            albums = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
        # 后台异步检查缓存过期（不再阻塞API响应）
        threading.Thread(target=_check_album_cache_expiry, args=(app,), daemon=True).start()
        albums = app.config.get('ALBUM_CACHE', [])
        result = []
        for a in albums:
            try:
                cover = _get_first_photo_cover(a['path'])
            except:
                cover = None
            result.append({
                'name': a['name'],
                'path': a['path'],
                'photo_count': a.get('photo_count', 0),
                'photo_count_only': a.get('photo_count_only', a.get('photo_count', 0)),
                'video_count': a.get('video_count', 0),
                'root': a.get('root', ''),
                'cover': cover,
            })
        return jsonify({'albums': result})

    @app.route('/api/photos')
    def api_photos():
        album = request.args.get('album', '')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        if not album:
            return jsonify({'error': 'album required'}), 400
        try:
            photos, total = scan_photos_local(album, page, per_page)
            return jsonify({
                'photos': photos,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/thumb/<photo_id>')
    def api_thumb(photo_id):
        path = request.args.get('path', '')
        if not path:
            return '', 400
        try:
            data = get_thumbnail(path, size=400)
            return Response(data, mimetype='image/jpeg')
        except:
            return '', 500

    @app.route('/raw/<photo_id>')
    def api_raw(photo_id):
        path = request.args.get('path', '')
        if not path:
            return '', 400
        try:
            data = _get_raw_cached(path)
            ext = path.lower().split('.')[-1]
            mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                    'gif': 'image/gif', 'webp': 'image/webp'}.get(ext, 'image/jpeg')
            return Response(data, mimetype=mime)
        except Exception as e:
            return str(e), 500

    @app.route('/raw_video/<photo_id>')
    def api_raw_video(photo_id):
        """流式传输视频文件（支持Range请求）"""
        path = request.args.get('path', '')
        if not path:
            return '', 400
        try:
            file_path = Path(path)
            if not file_path.exists():
                return 'File not found', 404

            total_size = file_path.stat().st_size
            ext = path.lower().split('.')[-1]
            mime_type, _ = mimetypes.guess_type(f'file.{ext}')
            if not mime_type:
                mime_type = 'video/mp4'

            range_header = request.headers.get('Range', '')
            if range_header:
                byte_str = range_header.replace('bytes=', '')
                start_str = byte_str.split('-')[0]
                end_str = byte_str.split('-')[1] if '-' in byte_str and byte_str.split('-')[1] else ''
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else total_size - 1
                end = min(end, total_size - 1)
                length = end - start + 1
                with open(file_path, 'rb') as f:
                    f.seek(start)
                    data = f.read(length)
                resp = Response(data, status=206, mimetype=mime_type,
                                headers={
                                    'Content-Range': f'bytes {start}-{end}/{total_size}',
                                    'Accept-Ranges': 'bytes',
                                    'Content-Length': str(length),
                                })
                return resp
            else:
                return send_file(str(file_path), mimetype=mime_type,
                               as_attachment=False, conditional=True)
        except Exception as e:
            return str(e), 500

    @app.route('/api/like', methods=['POST'])
    def api_like():
        data = request.get_json() or {}
        photo_id = data.get('photo_id', '')
        if not photo_id:
            return jsonify({'error': 'photo_id required'}), 400
        likes = {}
        if LIKES_PATH.exists():
            likes = json.loads(LIKES_PATH.read_text(encoding='utf-8'))
        if photo_id in likes and likes[photo_id].get('liked'):
            likes[photo_id]['liked'] = False
        else:
            likes[photo_id] = {'liked': True, 'liked_at': datetime.now().isoformat()}
        LIKES_PATH.write_text(json.dumps(likes, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify({'liked': likes[photo_id]['liked']})

    @app.route('/api/likes')
    def api_get_likes():
        if LIKES_PATH.exists():
            likes = json.loads(LIKES_PATH.read_text(encoding='utf-8'))
            liked_ids = {k for k, v in likes.items() if v.get('liked')}
            return jsonify({'liked_ids': list(liked_ids)})
        return jsonify({'liked_ids': []})

    @app.route('/api/photo/<photo_id>')
    def api_photo_info(photo_id):
        path = request.args.get('path', '')
        if not path:
            return jsonify({'error': 'path required'}), 400
        try:
            st = Path(path).stat()
            return jsonify({
                'filename': Path(path).name,
                'size': st.st_size,
                'mtime': datetime.fromtimestamp(st.st_mtime).isoformat(),
                'type': _get_media_type(path),
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/refresh/<path:album_path>')
    def api_refresh_album(album_path):
        cache_path = PHOTO_LIST_DIR / f"{hashlib.md5(album_path.encode()).hexdigest()}.json"
        if cache_path.exists():
            cache_path.unlink()
        if album_path in PHOTO_LIST_CACHE:
            del PHOTO_LIST_CACHE[album_path]
        return jsonify({'ok': True})

    @app.route('/api/platform')
    def api_platform():
        """前端获取当前平台信息"""
        return jsonify({
            'os': _os_type,
            'arch': _plat.get_platform_info().get('arch', ''),
        })

    return app


def _check_album_cache_expiry(app):
    """检查相册缓存是否超过24小时"""
    if not INDEX_PATH.exists():
        return
    try:
        now = time.time()
        mtime = INDEX_PATH.stat().st_mtime
        if now - mtime >= 86400:
            print("  [..] 相册缓存已过期(>24h)，重新扫描...", flush=True)
            new_albums = scan_albums_local()
            INDEX_PATH.write_text(json.dumps(new_albums, ensure_ascii=False, indent=2), encoding='utf-8')
            app.config['ALBUM_CACHE'] = new_albums
            print(f"  [OK] 相册缓存已更新: {len(new_albums)} 个相册", flush=True)
    except Exception as e:
        print(f"  [W] 相册缓存过期检查失败: {e}", flush=True)


# ══════════════════════════════════════════
# 启动入口
# ══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='NAS相册 Web 服务')
    parser.add_argument('--daemon', action='store_true', help='后台运行')
    parser.add_argument('--port', type=int, default=PORT, help='监听端口')
    parser.add_argument('--host', default=HOST, help='监听地址')
    args = parser.parse_args()

    host = args.host
    port = args.port

    app = create_app()

    # 加载相册缓存
    album_cache = []
    if INDEX_PATH.exists():
        try:
            album_cache = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
            print(f"  [OK] 从缓存加载: {len(album_cache)} 个相册")
        except:
            pass

    if not album_cache:
        print("[信号] 正在扫描相册...")
        try:
            album_cache = scan_albums_local()
            INDEX_PATH.write_text(json.dumps(album_cache, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"  [OK] 共 {len(album_cache)} 个相册")
        except Exception as e:
            print(f"  [W] 扫描失败: {e}")

    app.config['ALBUM_CACHE'] = album_cache

    # 夜间 cron job (凌晨3:00) 由 nightly_precache.py 负责全量缩略图生成
    print(f"   [..] 共 {len(album_cache)} 个相册 (缩略图由夜间任务生成)", flush=True)

    info = _plat.get_platform_info()
    print(f"\n[相机] NAS相册服务启动 (v4 跨平台版)")
    print(f"    运行平台: {_os_type} ({info.get('arch', '')})")
    print(f"    访问地址: http://{host}:{port}")
    print(f"    照片源: {len(PHOTO_ROOTS)} 个目录", flush=True)
    print()

    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    # 编码设置（关键：Windows GBK 兼容）
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass
    
    # 重定向 stdout/stderr 到日志文件（后台模式不做）
    if '--daemon' not in sys.argv:
        log_path = _script_dir / 'server.log'
        log_file = open(str(log_path), 'a', buffering=1, encoding='utf-8', errors='replace')
        sys.stdout = log_file
        sys.stderr = log_file

    main()
