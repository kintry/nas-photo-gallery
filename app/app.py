#!/usr/bin/env python3
"""NAS相册 Web 服务 v3 — NAS本地运行版（视频支持）
跑在 OECT NAS (Armbian) 上，直接读取本地照片和视频
"""

import sys, os, json, time, hashlib, io, threading, re, mimetypes
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from flask import send_file

SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = Path('/media/devmon/ACER120G/nas-photo-cache')
THUMB_DIR = CACHE_DIR / 'thumbs'
THUMB_DIR_SMALL = THUMB_DIR / 'sm'
INDEX_PATH = CACHE_DIR / 'index.json'
PHOTO_LIST_DIR = CACHE_DIR / 'photo_lists'
LIKES_PATH = SCRIPT_DIR / 'likes.json'

PHOTO_ROOTS = [
    '/media/devmon/SNAKE1',
    '/media/devmon/SNAKE2/叶丽芳手机相片',
    '/media/devmon/SNAKE2/叶丽芳的图片',
    '/media/devmon/SNAKE2/庄勤财手机相片',
    '/media/devmon/SNAKE2/佳能M2相片视频',
    '/media/devmon/OECT-HOME/相册',
    '/media/devmon/OECT-HOME/庄润晨的文档',
    '/media/devmon/OECT-HOME/庄润秋的文档',
    '/media/devmon/OECT-HOME/叶丽芳的影像',
    '/media/devmon/OECT-HOME/庄勤财的影像',
    '/media/devmon/OECT-HOME/家庭影像',
    '/media/devmon/SNAKE2/庄勤财手机视频',
    '/media/devmon/SNAKE2/叶丽芳手机相片视频',
    '/media/devmon/SNAKE2/叶丽芳手机视频',
    '/media/devmon/SNAKE2/庄润秋文档',
    '/media/devmon/SNAKE2/剪辑素材',
]

# ── 支持的视频格式 ──
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.mts', '.m2ts', '.3gp', '.wmv', '.mpg', '.mpeg'}
PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

HOST = '0.0.0.0'
PORT = 5000

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(THUMB_DIR_SMALL, exist_ok=True)
os.makedirs(PHOTO_LIST_DIR, exist_ok=True)

mimetypes.add_type('video/quicktime', '.mov')
mimetypes.add_type('video/mp4', '.mp4')
mimetypes.add_type('video/x-msvideo', '.avi')
mimetypes.add_type('video/x-matroska', '.mkv')
mimetypes.add_type('video/mp2t', '.mts')
mimetypes.add_type('video/mp2t', '.m2ts')
mimetypes.add_type('video/3gpp', '.3gp')
mimetypes.add_type('video/x-ms-wmv', '.wmv')
mimetypes.add_type('video/mpeg', '.mpg')
mimetypes.add_type('video/mpeg', '.mpeg')


def _read_raw(remote_path):
    return Path(remote_path).read_bytes()


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


# ── 判断文件类型 ──

def _is_video(path):
    ext = Path(path).suffix.lower()
    return ext in VIDEO_EXTS

def _is_photo(path):
    ext = Path(path).suffix.lower()
    return ext in PHOTO_EXTS

def _is_media(path):
    return _is_photo(path) or _is_video(path)

def _get_media_type(path):
    ext = Path(path).suffix.lower()
    if ext in PHOTO_EXTS:
        return 'photo'
    if ext in VIDEO_EXTS:
        return 'video'
    return 'unknown'


# ── 照片列表缓存 ──

PHOTO_LIST_CACHE = {}

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
            photos = json.loads(cache_path.read_text())
            PHOTO_LIST_CACHE[album_path] = {'photos': photos, 'ts': now}
            return photos
    return None

def _save_photo_list_cache(album_path, photos):
    cache_path = PHOTO_LIST_DIR / f"{hashlib.md5(album_path.encode()).hexdigest()}.json"
    cache_path.write_text(json.dumps(photos, ensure_ascii=False))
    PHOTO_LIST_CACHE[album_path] = {'photos': photos, 'ts': time.time()}


def _get_first_photo_cover(album_path):
    """从目录取第一个可用媒体文件做封面，优先找照片"""
    import pathlib
    album = pathlib.Path(album_path)
    if not album.exists():
        return None
    import hashlib
    first_photo = None
    first_video = None
    for fp in sorted(album.iterdir()):
        if not fp.is_file():
            continue
        fn = fp.name
        if fn.startswith('.') or fn.startswith('._'):
            continue
        ext = fn.lower().rsplit('.', 1)[-1] if '.' in fn else ''
        if '.{}'.format(ext) in PHOTO_EXTS:
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
        elif '.{}'.format(ext) in VIDEO_EXTS:
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
    """本地扫描NAS相册目录（含视频）"""
    albums = []
    for root in PHOTO_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            print(f"  ⚠️ 路径不存在 {root}", flush=True)
            continue
        for entry in root_path.iterdir():
            name = entry.name
            if name.startswith('.') or name.startswith('$') or name in ('System Volume Information', '@eaDir', 'FOUND.000', '$RECYCLE.BIN'):
                continue
            if entry.is_dir():
                img_count = sum(1 for f in entry.rglob('*') if f.suffix.lower() in PHOTO_EXTS and not f.name.startswith('._'))
                vid_count = sum(1 for f in entry.rglob('*') if f.suffix.lower() in VIDEO_EXTS and not f.name.startswith('._'))
                total_media = img_count + vid_count
                if total_media > 0:
                    # 获取封面
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
                    print(f"  ✅ {name}: {img_count}照片 + {vid_count}视频", flush=True)
    return albums


# ── 缩略图生成 ──

from PIL import Image, ImageFile, ImageDraw, ImageFont
ImageFile.LOAD_TRUNCATED_IMAGES = True

def get_thumbnail(local_path, size=400):
    """生成缩略图（照片直接缩略，视频返回一个播放按钮图标）"""
    filename = local_path.split('/')[-1]
    if filename.startswith('._') or filename.startswith('.'):
        return b''
    cache_key = hashlib.md5(local_path.encode()).hexdigest()
    cache_path = THUMB_DIR_SMALL / f"{cache_key}.jpg"

    if cache_path.exists() and cache_path.stat().st_size > 100:
        return cache_path.read_bytes()

    # 如果是视频，用ffmpeg截取第一帧做真实缩略图（如果ffmpeg可用）
    if _is_video(local_path):
        import subprocess
        ffmpeg_path = '/usr/bin/ffmpeg'
        if os.path.exists(ffmpeg_path):
            try:
                thumb_tmp = THUMB_DIR_SMALL / f"{cache_key}_tmp.jpg"
                r = subprocess.run(
                    [ffmpeg_path, '-y', '-i', local_path, '-vframes', '1',
                     '-vf', f'scale={size}:-1', '-q:v', '5', str(thumb_tmp)],
                    capture_output=True, timeout=30
                )
                if r.returncode == 0 and thumb_tmp.exists() and thumb_tmp.stat().st_size > 1000:
                    data = thumb_tmp.read_bytes()
                    # 移动到最终缓存路径
                    thumb_tmp.rename(cache_path)
                    return data
                # 清理临时文件
                if thumb_tmp.exists():
                    thumb_tmp.unlink()
            except:
                pass
        # ffmpeg不可用或失败：生成带播放按钮的占位缩略图
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
            data = out.getvalue()
            # ★ 修复：不写入缓存，避免播放按钮图标覆盖预生成的真实帧缩略图
            return data
        except:
            img = Image.new('RGB', (size, size), (30, 50, 80))
            draw = ImageDraw.Draw(img)
            cx, cy = size // 2, size // 2
            tri_size = size // 6
            tri_points = [
                (cx - tri_size // 2, cy - tri_size),
                (cx + tri_size, cy),
                (cx - tri_size // 2, cy + tri_size),
            ]
            draw.polygon(tri_points, fill=(255, 255, 255))
            out = io.BytesIO()
            img.save(out, 'JPEG', quality=70)
            return out.getvalue()

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
    print("\n⏳ 后台批量预生成缩略图（400px）...")
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
            fn = p['path'].split('/')[-1]
            if fn.startswith('.') or fn.startswith('._'):
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
                    print(f"  ...已预生成 {total_done} 张 (已处理 {total_albums} 个相册)", flush=True)
            except:
                pass
    print(f"  ✅ 预生成完成: 覆盖 {total_albums} 个相册, 共 {total_done} 张", flush=True)
    
    # ── 额外：为每个相册预生成前5个视频的ffmpeg缩略图 ──
    print("\n⏳ 后台预生成视频缩略图（每相册前5个）...")
    vid_done = 0
    vid_albums = 0
    for album in albums:
        photos_cache = _get_photo_list_cache(album['path'])
        if not photos_cache:
            photos_cache, _ = scan_photos_local(album['path'], 1, 999999)
        if not photos_cache:
            continue
        
        # 找出前5个视频
        vid_to_gen = []
        for p in photos_cache:
            if p.get('type') == 'video':
                fn = p['path'].split('/')[-1]
                if fn.startswith('.') or fn.startswith('._'):
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
                        print(f"  ...已预生成 {vid_done} 个视频缩略图 (已处理 {vid_albums} 个相册)", flush=True)
            except:
                pass
    print(f"  ✅ 视频缩略图预生成完成: 覆盖 {vid_albums} 个相册, 共 {vid_done} 个视频", flush=True)


# ══════════════════════════════════════════
#  Flask Web 服务
# ══════════════════════════════════════════

def create_app():
    from flask import Flask, jsonify, send_file, request, render_template, abort, Response, stream_with_context

    app = Flask(__name__,
                template_folder=str(SCRIPT_DIR / 'templates'),
                static_folder=str(SCRIPT_DIR / 'static'))

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
            albums = json.loads(INDEX_PATH.read_text())
        
        # 检查缓存是否过期（24小时），过期则自动重扫
        _check_album_cache_expiry(app)
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
        except Exception as e:
            return str(e), 500

    @app.route('/raw/<photo_id>')
    def api_raw(photo_id):
        path = request.args.get('path', '')
        if not path:
            return '', 400
        try:
            data = _get_raw_cached(path)
            ext = path.lower().split('.')[-1]
            mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}.get(ext, 'image/jpeg')
            return Response(data, mimetype=mime)
        except Exception as e:
            return str(e), 500

    @app.route('/raw_video/<photo_id>')
    def api_raw_video(photo_id):
        """流式传输视频文件（支持Range请求实现拖拽播放）"""
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
                # 处理 Range 请求
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
                # 全量返回
                return send_file(
                    str(file_path),
                    mimetype=mime_type,
                    as_attachment=False,
                    conditional=True,
                )
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
            likes = json.loads(LIKES_PATH.read_text())
        if photo_id in likes and likes[photo_id].get('liked'):
            likes[photo_id]['liked'] = False
        else:
            likes[photo_id] = {'liked': True, 'liked_at': datetime.now().isoformat()}
        LIKES_PATH.write_text(json.dumps(likes, ensure_ascii=False, indent=2))
        return jsonify({'liked': likes[photo_id]['liked']})

    @app.route('/api/likes')
    def api_get_likes():
        if LIKES_PATH.exists():
            likes = json.loads(LIKES_PATH.read_text())
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
                'filename': path.split('/')[-1],
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

    return app


def _check_album_cache_expiry(app):
    """检查相册缓存是否超过24小时，过期则重新扫描并更新"""
    if not INDEX_PATH.exists():
        return
    try:
        now = time.time()
        mtime = INDEX_PATH.stat().st_mtime
        if now - mtime >= 86400:
            print(f"   🔄 相册缓存已过期(>24h)，重新扫描...", flush=True)
            new_albums = scan_albums_local()
            INDEX_PATH.write_text(json.dumps(new_albums, ensure_ascii=False, indent=2))
            app.config['ALBUM_CACHE'] = new_albums
            print(f"   ✅ 相册缓存已更新: {len(new_albums)} 个相册", flush=True)
    except Exception as e:
        print(f"   ⚠️ 相册缓存过期检查失败: {e}", flush=True)


if __name__ == '__main__':
    log_file = open(SCRIPT_DIR / 'server.log', 'a', buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file

    app = create_app()

    _album_cache = []
    if INDEX_PATH.exists():
        try:
            _album_cache = json.loads(INDEX_PATH.read_text())
            print(f"   📦 从缓存加载: {len(_album_cache)} 个相册")
        except:
            pass

    if not _album_cache:
        print("📡 正在扫描NAS相册...")
        try:
            _album_cache = scan_albums_local()
            INDEX_PATH.write_text(json.dumps(_album_cache, ensure_ascii=False, indent=2))
            print(f"   ✅ 共 {len(_album_cache)} 个相册")
        except Exception as e:
            print(f"   ⚠️ 扫描失败: {e}")

    app.config['ALBUM_CACHE'] = _album_cache

    small_albums = [a for a in _album_cache if a.get('photo_count', 0) < 2000]
    big_albums_names = [a['name'] for a in _album_cache if a.get('photo_count', 0) >= 2000]
    if big_albums_names:
        print(f"   ⏭ 跳过超大相册(>2000张): {', '.join(big_albums_names[:5])}...", flush=True)

    bg_thread = threading.Thread(target=batch_precache_thumbnails, args=(small_albums, 20), daemon=True)
    bg_thread.start()

    print(f"\n📸 NAS相册服务启动（v3本地版 · 视频支持）", flush=True)
    print(f"   访问地址: http://{HOST}:{PORT}", flush=True)
    print(f"   照片&视频源: 本地读取", flush=True)
    print(flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
