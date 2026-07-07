#!/usr/bin/env python3
"""
NAS相册 Web 服务 v2（性能优化版）
跑在 WSL (HP电脑) 上，通过 SSH/SFTP 从 NAS 读取照片
访问地址: http://192.168.2.119:5000

优化要点：
- 照片列表缓存到本地JSON（scan_photos结果缓存）
- 大图LRU缓存到WSL内存（避免重复SFTP下载）
- 启动后后台异步预生成所有相册前20张缩略图
- /raw/ 路由支持Range请求（渐进加载）
- /api/photos 改用本地缓存
"""

import sys, os, json, time, hashlib, io, threading, re
from pathlib import Path
from datetime import datetime
from functools import lru_cache

SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / 'cache'
THUMB_DIR = CACHE_DIR / 'thumbs'
THUMB_DIR_SMALL = THUMB_DIR / 'sm'   # 200px
THUMB_DIR_LARGE = THUMB_DIR / 'lg'   # 400px
INDEX_PATH = CACHE_DIR / 'index.json'
PHOTO_LIST_DIR = CACHE_DIR / 'photo_lists'  # 缓存每个相册的照片列表
RAW_CACHE_DIR = CACHE_DIR / 'raw_cache'     # 大图缓存
LIKES_PATH = SCRIPT_DIR / 'likes.json'

# ── NAS 配置 ──
NAS_HOST = '192.168.2.104'
NAS_USER = 'root'
NAS_PASS = '515144zqc@GZ'

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
os.makedirs(THUMB_DIR_LARGE, exist_ok=True)
os.makedirs(PHOTO_LIST_DIR, exist_ok=True)
os.makedirs(RAW_CACHE_DIR, exist_ok=True)


# ══════════════════════════════════════════
#  SFTP 连接池（连接复用）
# ══════════════════════════════════════════

_sftp_pool = threading.local()


def _get_ssh():
    """获取当前线程的SSH连接"""
    if not hasattr(_sftp_pool, 'ssh') or _sftp_pool.ssh is None:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(NAS_HOST, port=22, username=NAS_USER,
                    password=NAS_PASS, timeout=10,
                    allow_agent=False, look_for_keys=False)
        _sftp_pool.ssh = ssh
        _sftp_pool.sftp = ssh.open_sftp()
    return _sftp_pool.ssh, _sftp_pool.sftp


def _sftp_read(remote_path, timeout=15):
    """通过SSH读取文件（共享连接）"""
    import paramiko
    import socket
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(NAS_HOST, port=22, username=NAS_USER,
                    password=NAS_PASS, timeout=timeout,
                    allow_agent=False, look_for_keys=False)
        # socket层超时，防止sftp.file().read()卡死
        transport = ssh.get_transport()
        transport.set_keepalive(5)
        sock = transport.sock
        if sock:
            sock.settimeout(timeout)
        sftp = ssh.open_sftp()
        with sftp.file(remote_path, 'rb') as f:
            data = f.read()
        sftp.close()
        ssh.close()
        return data
    except:
        try: ssh.close()
        except: pass
        raise


# ══════════════════════════════════════════
#  大图LRU缓存（内存中保存最近看的N张大图）
# ══════════════════════════════════════════

RAW_MEM_CACHE = {}          # path -> (data, timestamp)
RAW_CACHE_MAX = 50          # 最多缓存50张
RAW_DISK_TIMEOUT = 3600     # 磁盘缓存有效期1小时


def _get_raw_cached(remote_path):
    """获取大图，优先走内存缓存→磁盘缓存→SFTP"""
    now = time.time()
    
    # 1. 内存缓存
    if remote_path in RAW_MEM_CACHE:
        data, ts = RAW_MEM_CACHE[remote_path]
        RAW_MEM_CACHE[remote_path] = (data, now)
        return data
    
    # 2. 磁盘缓存
    cache_key = hashlib.md5(remote_path.encode()).hexdigest()
    disk_path = RAW_CACHE_DIR / cache_key
    if disk_path.exists():
        mtime = disk_path.stat().st_mtime
        if now - mtime < RAW_DISK_TIMEOUT:
            data = disk_path.read_bytes()
            _put_mem_cache(remote_path, data)
            return data
    
    # 3. SFTP下载
    data = _sftp_read(remote_path, timeout=15)
    
    # 保存到磁盘缓存
    disk_path.write_bytes(data)
    
    # 保存到内存缓存
    _put_mem_cache(remote_path, data)
    
    return data


def _put_mem_cache(path, data):
    """放入内存缓存（LRU淘汰）"""
    while len(RAW_MEM_CACHE) >= RAW_CACHE_MAX:
        oldest_key = min(RAW_MEM_CACHE, key=lambda k: RAW_MEM_CACHE[k][1])
        del RAW_MEM_CACHE[oldest_key]
    RAW_MEM_CACHE[path] = (data, time.time())


# ══════════════════════════════════════════
#  照片列表缓存（避免每次打开相册都SSH find）
# ══════════════════════════════════════════

PHOTO_LIST_CACHE = {}  # album_path -> {'photos': [...], 'ts': timestamp}


def _get_photo_list_cache(album_path):
    """获取相册照片列表（优先缓存）"""
    now = time.time()
    cache_path = PHOTO_LIST_DIR / f"{hashlib.md5(album_path.encode()).hexdigest()}.json"
    
    # 内存缓存
    if album_path in PHOTO_LIST_CACHE:
        entry = PHOTO_LIST_CACHE[album_path]
        if now - entry['ts'] < 86400:  # 24h有效
            return entry['photos']
    
    # 磁盘缓存
    if cache_path.exists():
        mtime = cache_path.stat().st_mtime
        if now - mtime < 86400:
            photos = json.loads(cache_path.read_text())
            PHOTO_LIST_CACHE[album_path] = {'photos': photos, 'ts': now}
            return photos
    
    return None


def _save_photo_list_cache(album_path, photos):
    """保存照片列表到缓存"""
    cache_path = PHOTO_LIST_DIR / f"{hashlib.md5(album_path.encode()).hexdigest()}.json"
    cache_path.write_text(json.dumps(photos, ensure_ascii=False))
    PHOTO_LIST_CACHE[album_path] = {'photos': photos, 'ts': time.time()}


def scan_photos(album_path, page=1, per_page=20):
    """获取某个相册的照片列表（带缓存）"""
    # 尝试读取缓存
    cached = _get_photo_list_cache(album_path)
    if cached is not None:
        total = len(cached)
        start = (page - 1) * per_page
        end = start + per_page
        return cached[start:end], total
    
    # 缓存未命中，SSH扫描
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(NAS_HOST, port=22, username=NAS_USER,
                    password=NAS_PASS, timeout=10,
                    allow_agent=False, look_for_keys=False)
        sftp = ssh.open_sftp()
        
        c = ssh.exec_command(
            f'find "{album_path}" -maxdepth 3 -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \) 2>/dev/null',
            timeout=30
        )
        raw = c[1].read().decode('utf-8', errors='replace').strip()
        files = [f.strip() for f in raw.split('\n') if f.strip()]
        
        photos = []
        for fp in files:
            fn = fp.split('/')[-1]
            if fn.startswith('._') or fn.startswith('.'):
                continue
            try:
                attr = sftp.stat(fp)
                photos.append({
                    'filename': fn,
                    'path': fp,
                    'size': attr.st_size,
                    'mtime': attr.st_mtime,
                    'id': hashlib.md5(fp.encode()).hexdigest()[:12],
                })
            except:
                continue
        
        sftp.close()
        ssh.close()
    except Exception as e:
        try: sftp.close()
        except: pass
        try: ssh.close()
        except: pass
        return [], 0
    
    photos.sort(key=lambda x: x['mtime'], reverse=True)
    
    # 保存缓存
    _save_photo_list_cache(album_path, photos)
    
    total = len(photos)
    start = (page - 1) * per_page
    end = start + per_page
    
    return photos[start:end], total


# ══════════════════════════════════════════
#  相册扫描（只启动时运行一次）
# ══════════════════════════════════════════

def scan_albums():
    """扫描NAS上的相册目录（快速模式，给每个目录设5秒超时）"""
    import paramiko
    
    albums = []
    
    def _scan_root(root):
        """扫描单个根目录，独立SSH连接防卡死"""
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(NAS_HOST, port=22, username=NAS_USER,
                        password=NAS_PASS, timeout=10,
                        allow_agent=False, look_for_keys=False)
            sftp = ssh.open_sftp()
            
            try:
                entries = sorted(sftp.listdir_attr(root), key=lambda e: e.filename)
            except:
                print(f"  ⚠️ 无法读取 {root}", flush=True)
                sftp.close(); ssh.close()
                return []
            
            result = []
            for entry in entries:
                name = entry.filename
                path = f"{root}/{name}"
                if name.startswith('.') or name.startswith('$') or name in ('System Volume Information', '@eaDir', 'FOUND.000'):
                    continue
                try:
                    # 用 sftp.listdir 快速判断是否为目录并且有文件
                    children = sftp.listdir(path)
                    img_count = sum(1 for f in children if f.lower().endswith(('.jpg', '.jpeg', '.png')))
                    if img_count == 0:
                        # 可能照片在子目录中，用find统计
                        stdin, stdout, stderr = ssh.exec_command(
                            f'find "{path}" -maxdepth 2 -type f \\( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \\) 2>/dev/null | wc -l',
                            timeout=15
                        )
                        img_count = int(stdout.read().decode().strip() or 0)
                    if img_count > 0:
                        result.append({'name': name, 'path': path, 'photo_count': img_count, 'root': root.split('/')[-1]})
                        print(f"  ✅ {name}: {img_count}张", flush=True)
                except:
                    pass
            
            sftp.close()
            ssh.close()
            return result
        except Exception as e:
            print(f"  ⚠️ SSH连接失败 ({root}): {e}", flush=True)
            try: ssh.close()
            except: pass
            return []
    
    for root in PHOTO_ROOTS:
        albums.extend(_scan_root(root))
    
    return albums


# ══════════════════════════════════════════
#  缩略图生成（支持并发批量）
# ══════════════════════════════════════════

def get_thumbnail(remote_path, size=200):
    """生成缩略图（缓存到本地），支持 size=200 或 size=400"""
    # 跳过macOS的隐藏文件
    filename = remote_path.split('/')[-1]
    if filename.startswith('._') or filename.startswith('.'):
        return b''
    cache_key = hashlib.md5(remote_path.encode()).hexdigest()
    thumb_dir = THUMB_DIR_SMALL if size <= 200 else THUMB_DIR_LARGE
    cache_path = thumb_dir / f"{cache_key}.jpg"
    
    if cache_path.exists():
        return cache_path.read_bytes()
    
    data = _sftp_read(remote_path, timeout=15)
    
    # 用 multiprocessing 执行Pillow转换（可强制终止）
    import multiprocessing as _mp
    def _pillow_worker(conn, data_bytes, thumb_size):
        """在子进程中执行Pillow转换"""
        try:
            import sys, io
            from PIL import Image, ImageFile
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            img = Image.open(io.BytesIO(data_bytes))
            w, h = img.size
            if thumb_size < w:
                ratio = thumb_size / w
                img = img.resize((thumb_size, int(h * ratio)), Image.LANCZOS)
            quality = 65 if thumb_size <= 200 else 75
            out = io.BytesIO()
            img.save(out, 'JPEG', quality=quality)
            conn.send(out.getvalue())
        except:
            conn.send(None)
        finally:
            conn.close()
    
    parent_conn, child_conn = _mp.Pipe(duplex=False)
    p = _mp.Process(target=_pillow_worker, args=(child_conn, data, size))
    p.start()
    p.join(timeout=20)
    if p.is_alive():
        p.terminate()
        p.join(timeout=2)
        cache_path.write_bytes(b'')
        parent_conn.close()
        child_conn.close()
        return b''
    
    try:
        thumb_data = parent_conn.recv()
        if thumb_data is None:
            cache_path.write_bytes(b'')
            return b''
    except (EOFError, _mp.connection.BrokenPipeError):
        cache_path.write_bytes(b'')
        return b''
    finally:
        parent_conn.close()
        child_conn.close()
    
    cache_path.write_bytes(thumb_data)
    return thumb_data


def batch_precache_thumbnails(albums, max_per_album=999999):
    """后台批量预生成缩略图（逐张生成全部照片）"""
    print("\n⏳ 后台批量预生成缩略图...")
    total_done = 0
    total_albums = 0
    total_photos = 0
    
    for album in albums:
        try:
            photos_cache = _get_photo_list_cache(album['path'])
        except:
            photos_cache = None
        if not photos_cache:
            try:
                photos_cache, _ = scan_photos(album['path'], 1, 999999)
            except:
                continue
        
        if not photos_cache:
            continue
        
        # 检查哪些还没生成（预生成只处理JPG，跳过PNG和超大文件）
        existing200 = existing400 = 0
        to_gen_200 = []
        to_gen_400 = []
        for p in photos_cache[:max_per_album]:
            fn = p['path'].split('/')[-1]
            if fn.startswith('.') or fn.startswith('._'):
                continue
            if p.get('size', 0) > 2_000_000:  # 超过2MB跳过
                continue
            ck_sm = THUMB_DIR_SMALL / f"{hashlib.md5(p['path'].encode()).hexdigest()}.jpg"
            ck_lg = THUMB_DIR_LARGE / f"{hashlib.md5(p['path'].encode()).hexdigest()}.jpg"
            if ck_sm.exists():
                existing200 += 1
            else:
                to_gen_200.append(p['path'])
            if ck_lg.exists():
                existing400 += 1
            else:
                to_gen_400.append(p['path'])
        
        if not to_gen_200 and not to_gen_400:
            continue
        
        total_albums += 1
        total_photos += len(photos_cache)
        
        # 同时生成200px和400px两种缩略图（每个相册最多20张照片的两种尺寸）
        batch = list(set(to_gen_200[:20] + to_gen_400[:20]))
        done = 0
        for remote_path in batch:
            try:
                get_thumbnail(remote_path, size=200)
                get_thumbnail(remote_path, size=400)
                done += 1
                total_done += 1
                if total_done % 10 == 0:
                    print(f"  ...已预生成 {total_done} 张照片的缩略图 (已处理 {total_albums}/{len(albums)} 个相册, 这个相册{done}/{len(batch)})", flush=True)
            except:
                pass
    
    print(f"  ✅ 预生成完成: 覆盖 {total_albums}/{len(albums)} 个相册, 共 {total_done} 张照片 (每张200+400双尺寸)")


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
        
        # 为每个相册获取第一张照片作为封面（从缓存读取）
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
                'cover': cover,  # 第一张照片信息（含path，前端可拼thumbUrl）
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
            photos, total = scan_photos(album, page, per_page)
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
        size = request.args.get('size', '200')
        if not path:
            return '', 400
        try:
            size = int(size)
            if size not in (200, 400):
                size = 200
        except:
            size = 200
        try:
            data = get_thumbnail(path, size=size)
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
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(NAS_HOST, port=22, username=NAS_USER,
                        password=NAS_PASS, timeout=10,
                        allow_agent=False, look_for_keys=False)
            sftp = ssh.open_sftp()
            attr = sftp.stat(path)
            sftp.close(); ssh.close()
            return jsonify({
                'filename': path.split('/')[-1],
                'size': attr.st_size,
                'mtime': datetime.fromtimestamp(attr.st_mtime).isoformat(),
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/refresh/<path:album_path>')
    def api_refresh_album(album_path):
        """强制刷新某个相册的缓存"""
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
    # 日志输出到文件（因为WSL背景进程stdout不可见）
    log_file = open(SCRIPT_DIR / 'server.log', 'a', buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
    
    app = create_app()
    
    # 从缓存加载相册列表
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
            _album_cache = scan_albums()
            INDEX_PATH.write_text(json.dumps(_album_cache, ensure_ascii=False, indent=2))
            print(f"   ✅ 共 {len(_album_cache)} 个相册")
        except Exception as e:
            print(f"   ⚠️ 扫描失败: {e}")
    
    app.config['ALBUM_CACHE'] = _album_cache
    
    # 启动后台线程批量预生成缩略图（仅对小相册，跳过超大图库）
    small_albums = [a for a in _album_cache if a.get('photo_count', 0) < 2000]
    big_albums_names = [a['name'] for a in _album_cache if a.get('photo_count', 0) >= 2000]
    if big_albums_names:
        print(f"   ⏭ 跳过超大相册(>2000张): {', '.join(big_albums_names[:5])}...", flush=True)
    
    bg_thread = threading.Thread(target=batch_precache_thumbnails, args=(small_albums, 20), daemon=True)
    bg_thread.start()
    
    print(f"\n📸 NAS相册服务启动 v2", flush=True)
    print(f"   访问地址: http://{HOST}:{PORT}", flush=True)
    print(f"   照片源: NAS ({NAS_HOST})", flush=True)
    print(f"   照片缓存: {len(_album_cache)} 个相册 | 内存LRU: {RAW_CACHE_MAX}张 | 缩略图本地缓存", flush=True)
    print(flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
