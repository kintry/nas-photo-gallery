#!/usr/bin/env python3
"""
NAS相册 Web 服务 v3 — NAS本地运行版（优化版）
跑在 OECT NAS (Armbian) 上，直接读取本地照片
访问地址: http://192.168.2.104:5000

v3改动：
- 网格缩略图从200px改为400px
- 详情页大图直接加载原图（NAS本地读取仅4ms）
- 缩略图生成统一只生成400px（sm目录存400px）
- lg目录不再使用
"""

import sys, os, json, time, hashlib, io, threading, re
from pathlib import Path
from datetime import datetime
from functools import lru_cache

SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / 'cache'
THUMB_DIR = CACHE_DIR / 'thumbs'
THUMB_DIR_SMALL = THUMB_DIR / 'sm'   # 400px（网格用）
INDEX_PATH = CACHE_DIR / 'index.json'
PHOTO_LIST_DIR = CACHE_DIR / 'photo_lists'
LIKES_PATH = SCRIPT_DIR / 'likes.json'

# ── 照片路径（NAS本地路径）──
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
]

HOST = '0.0.0.0'
PORT = 5000

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(THUMB_DIR_SMALL, exist_ok=True)
os.makedirs(PHOTO_LIST_DIR, exist_ok=True)

# ══════════════════════════════════════════
#  本地文件读取（替代SFTP）
# ══════════════════════════════════════════

def _read_raw(remote_path):
    return Path(remote_path).read_bytes()


# ══════════════════════════════════════════
#  大图读取（内存LRU缓存）
# ══════════════════════════════════════════

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


# ══════════════════════════════════════════
#  照片列表缓存（本地扫描替代SSH find）
# ══════════════════════════════════════════

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


def scan_photos_local(album_path, page=1, per_page=20):
    """获取某个相册的照片列表（带缓存）"""
    cached = _get_photo_list_cache(album_path)
    if cached is not None:
        total = len(cached)
        start = (page - 1) * per_page
        end = start + per_page
        return cached[start:end], total

    # 本地扫描
    album = Path(album_path)
    if not album.exists():
        return [], 0

    photos = []
    for fp in album.rglob('*'):
        if not fp.is_file():
            continue
        fn = fp.name
        if fn.startswith('.') or fn.startswith('._'):
            continue
        ext = fn.lower().rsplit('.', 1)[-1] if '.' in fn else ''
        if ext not in ('jpg', 'jpeg', 'png'):
            continue
        try:
            st = fp.stat()
            photos.append({
                'filename': fn,
                'path': str(fp),
                'size': st.st_size,
                'mtime': st.st_mtime,
                'id': hashlib.md5(str(fp).encode()).hexdigest()[:12],
            })
        except:
            continue

    photos.sort(key=lambda x: x['mtime'], reverse=True)
    _save_photo_list_cache(album_path, photos)

    total = len(photos)
    start = (page - 1) * per_page
    end = start + per_page
    return photos[start:end], total


# ══════════════════════════════════════════
#  相册扫描（本地扫描替代SSH扫描）
# ══════════════════════════════════════════

def scan_albums_local():
    """本地扫描NAS相册目录"""
    albums = []
    for root in PHOTO_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            print(f"  ⚠️ 路径不存在 {root}", flush=True)
            continue
        for entry in root_path.iterdir():
            name = entry.name
            if name.startswith('.') or name.startswith('$') or name in ('System Volume Information', '@eaDir', 'FOUND.000'):
                continue
            if entry.is_dir():
                img_count = sum(1 for f in entry.rglob('*') if f.suffix.lower() in ('.jpg', '.jpeg', '.png') and not f.name.startswith('._'))
                if img_count > 0:
                    albums.append({'name': name, 'path': str(entry), 'photo_count': img_count, 'root': root_path.name})
                    print(f"  ✅ {name}: {img_count}张", flush=True)
    return albums


# ══════════════════════════════════════════
#  缩略图生成（v3：统一400px，质量提升）
# ══════════════════════════════════════════

from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

def get_thumbnail(local_path, size=400):
    """生成缩略图（v3统一400px，网格展示用）"""
    filename = local_path.split('/')[-1]
    if filename.startswith('._') or filename.startswith('.'):
        return b''
    cache_key = hashlib.md5(local_path.encode()).hexdigest()
    cache_path = THUMB_DIR_SMALL / f"{cache_key}.jpg"

    if cache_path.exists() and cache_path.stat().st_size > 100:
        return cache_path.read_bytes()

    try:
        img = Image.open(local_path)
        w, h = img.size
        if size < w:
            ratio = size / w
            img = img.resize((size, int(h * ratio)), Image.LANCZOS)
        quality = 80  # 提升质量，本地无带宽瓶颈
        out = io.BytesIO()
        img.save(out, 'JPEG', quality=quality)
        data = out.getvalue()
        if len(data) > 100:
            cache_path.write_bytes(data)
        return data
    except:
        return b''


def batch_precache_thumbnails(albums, max_per_album=999999):
    """后台批量预生成缩略图（v3：只生成400px）"""
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
            if p.get('size', 0) > 50_000_000:  # 超过50MB跳过
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


# ══════════════════════════════════════════
#  Flask Web 服务
# ══════════════════════════════════════════

def create_app():
    from flask import Flask, jsonify, send_file, request, render_template, abort, Response

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
        return render_template('viewer.html',
                             photo_id=request.args.get('img', ''),
                             album=request.args.get('album', ''))

    @app.route('/api/albums')
    def api_albums():
        albums = app.config.get('ALBUM_CACHE', [])
        if not albums and INDEX_PATH.exists():
            albums = json.loads(INDEX_PATH.read_text())
        result = []
        for a in albums:
            try:
                cached = _get_photo_list_cache(a['path'])
                cover = cached[0] if cached else None
            except:
                cover = None
            result.append({
                'name': a['name'],
                'path': a['path'],
                'photo_count': a.get('photo_count', 0),
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
            mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png'}.get(ext, 'image/jpeg')
            return Response(data, mimetype=mime)
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


# ══════════════════════════════════════════
#  启动
# ══════════════════════════════════════════

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

    # 后台预生成缩略图（统一400px）
    small_albums = [a for a in _album_cache if a.get('photo_count', 0) < 2000]
    big_albums_names = [a['name'] for a in _album_cache if a.get('photo_count', 0) >= 2000]
    if big_albums_names:
        print(f"   ⏭ 跳过超大相册(>2000张): {', '.join(big_albums_names[:5])}...", flush=True)

    bg_thread = threading.Thread(target=batch_precache_thumbnails, args=(small_albums, 20), daemon=True)
    bg_thread.start()

    print(f"\n📸 NAS相册服务启动（v3本地版）", flush=True)
    print(f"   访问地址: http://{HOST}:{PORT}", flush=True)
    print(f"   照片源: 本地读取", flush=True)
    print(f"   网格缩略图: 400px | 详情页大图: 原图直接加载", flush=True)
    print(f"   照片缓存: {len(_album_cache)} 个相册 | 内存LRU: {RAW_CACHE_MAX}张 | 缩略图本地缓存", flush=True)
    print(flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
