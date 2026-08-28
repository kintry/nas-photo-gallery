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

PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.heif'}



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

# 照片目录管理（运行时增删，写入config.py持久化）

# ═══════════════════════════════════════════



PHOTO_ROOTS_PATH = _script_dir / 'config.py'



def _reload_photo_roots():

    """从config.py重新加载PHOTO_ROOTS"""

    global PHOTO_ROOTS

    if PHOTO_ROOTS_PATH.exists():

        try:

            ns = {}

            exec(PHOTO_ROOTS_PATH.read_text(encoding='utf-8'), ns)

            if 'PHOTO_ROOTS' in ns and ns['PHOTO_ROOTS']:

                PHOTO_ROOTS[:] = ns['PHOTO_ROOTS']

                return True

        except Exception as e:

            print(f"  [W] 重载PHOTO_ROOTS失败: {e}", flush=True)

    return False



def _norm_windows_path(p):
    """规范化 Windows 路径：双反斜杠→单反斜杠，去尾反斜杠（跨平台安全）。"""
    s = str(p)
    # 去掉前一层的转义反斜杠（如 r'D:\\叶丽芳' → D:\叶丽芳）
    s = s.replace('\\\\', '\\')
    # Windows: 去尾反斜杠（保留盘符 C:\）
    if len(s) > 3 and (s.endswith('\\') or s.endswith('/')):
        s = s.rstrip('\\/')
    return s


def _save_photo_roots(roots):

    """保存照片根目录列表到config.py（Windows路径统一单反斜杠）"""

    norm_roots = [_norm_windows_path(r) for r in roots]
    lines = ['# -*- coding: utf-8 -*-', 'PHOTO_ROOTS = [']

    for r in norm_roots:
        # 直接写单反斜杠路径（r 原始字符串里反斜杠是字面量，无需再转义）
        lines.append(f"    r'{r}',")

    lines.append(']')
    lines.append(f"CACHE_DIR = r'{_norm_windows_path(CACHE_DIR)}'")
    lines.append('')
    text = '\n'.join(lines)

    PHOTO_ROOTS_PATH.write_text(text, encoding='utf-8')

    global PHOTO_ROOTS

    PHOTO_ROOTS[:] = norm_roots

    print(f"  [OK] config.py 已更新: {len(norm_roots)} 个照片根目录", flush=True)



# ═══════════════════════════════════════════

# 相册目录历史（photo_roots_history.json）

# 目标：被停用的目录不物理删除，保留历史，可重新启用

# ═══════════════════════════════════════════

HISTORY_PATH = _script_dir / 'photo_roots_history.json'



# 相册级启用清单 enabled_albums.json

ENABLED_ALBUMS_PATH = _script_dir / 'enabled_albums.json'

def _load_enabled_albums():

    # 读取启用的相册路径集合。不存在返回None(首次需初始化)。

    if not ENABLED_ALBUMS_PATH.exists():

        return None

    try:

        data = json.loads(ENABLED_ALBUMS_PATH.read_text(encoding='utf-8'))

        return set(data.get('enabled', []))

    except Exception:

        return None

def _save_enabled_albums(enabled_set):

    # 保存启用的相册路径集合

    try:

        ENABLED_ALBUMS_PATH.write_text(

            json.dumps({'enabled': sorted(enabled_set)}, ensure_ascii=False, indent=2),

            encoding='utf-8')

    except Exception:

        pass

def _get_enabled_albums_or_init(all_album_paths):

    # 获取启用清单; 首次基于当前所有相册路径初始化(全启用)

    eset = _load_enabled_albums()

    if eset is None:

        eset = set(all_album_paths)

        _save_enabled_albums(eset)

    return eset

def _is_under_any_root(p):

    # 判断相册路径 p 是否已位于某个 PHOTO_ROOTS 根之下

    pn = str(p).rstrip('/\\')

    for r in PHOTO_ROOTS:

        rn = str(r).rstrip('/\\')

        if pn == rn or pn.startswith(rn + '/'):

            return True

    return False

def _load_history():

    """读取历史记录。首次升级：若历史文件不存在，把当前 PHOTO_ROOTS 全部记为 active"""

    if HISTORY_PATH.exists():

        try:

            data = json.loads(HISTORY_PATH.read_text(encoding='utf-8'))

            roots = data.get('roots', [])

            if roots:

                return roots

        except Exception as e:

            print(f"  [W] 历史读取失败: {e}", flush=True)

    # 初始化：从当前 PHOTO_ROOTS 生成历史

    now = datetime.now().isoformat(timespec='seconds')

    roots = [{'path': p, 'active': True, 'added_at': now, 'removed_at': None}

             for p in PHOTO_ROOTS]

    _save_history(roots)

    return roots



def _save_history(roots):

    """写历史记录"""

    try:

        HISTORY_PATH.write_text(json.dumps({'roots': roots}, ensure_ascii=False, indent=2), encoding='utf-8')

    except Exception as e:

        print(f"  [W] 历史写入失败: {e}", flush=True)



def _get_root_history(path):

    """在历史里查找某条路径记录，返回 dict 或 None"""

    for r in _load_history():

        if r['path'] == path:

            return r

    return None



def _activate_root_in_history(path):

    """将历史中某路径标记为 active（重新启用），若不在历史则新增"""

    history = _load_history()

    found = False

    for r in history:

        if r['path'] == path:

            r['active'] = True

            r['removed_at'] = None

            found = True

            break

    if not found:

        now = datetime.now().isoformat(timespec='seconds')

        history.append({'path': path, 'active': True, 'added_at': now, 'removed_at': None})

    _save_history(history)



def _deactivate_root_in_history(path):

    """将历史中某路径标记为 inactive（停用保留）"""

    history = _load_history()

    now = datetime.now().isoformat(timespec='seconds')

    found = False

    for r in history:

        if r['path'] == path:

            r['active'] = False

            r['removed_at'] = now

            found = True

            break

    if not found:

        history.append({'path': path, 'active': False, 'added_at': now, 'removed_at': now})

    _save_history(history)



def _delete_root_from_history(path):

    """将某路径从历史中彻底删除（不保留任何记录）"""

    history = _load_history()

    new_history = [r for r in history if r['path'] != path]

    if len(new_history) != len(history):

        _save_history(new_history)



def _quick_scan_photo_dirs():

    """递归扫描本地，发现所有含照片目录（深至8层，跨Win/Mac/Linux）。

    供API调用：POST /api/photo_roots/scan。与管理面板"新增"联动，
    用户直接勾选/取消未纳入的相册目录即可添加。

    """
    def _is_under_root(p):
        norm_p = str(p).rstrip('/\\')
        for r in PHOTO_ROOTS:
            if norm_p == r.rstrip('/\\'):
                return True
        return False

    SKIP = {'System Volume Information', '$RECYCLE.BIN', 'Program Files',
            'Program Files (x86)', 'Windows', 'Recovery', 'AppData',
            'node_modules', '.git', '$WinREAgent', 'Temp', '@eaDir',
            'FOUND.000', 'lost+found', 'System Volume Information',
            # 系统/软件/驱动/垃圾目录（含少量图但不是相册）
            'ProgramData', 'Intel', 'AMD', 'Canon', 'EPSON', 'Hewlett-Packard',
            'LogiOptions', 'Kingsoft', 'MyDrivers', 'NVIDIA', 'Microsoft',
            'WindowsApps', 'PerfLogs', 'inetpub', 'WINDOWS', 'Boot',}
    # 若目录名含这些关键词也视为非相册目录（跳过）
    _SKIP_KEYWORDS = ('driver', 'drivers', 'backup', 'snapshot', 'logo',
                      'cache', 'tmp', 'temp', 'install', 'cloudrender',
                      'test-classes', '软渲染', '云渲染')
    MAX_DEPTH = 8
    discovered = []
    seen = set()

    def rec(p, depth):
        if depth > MAX_DEPTH:
            return
        try:
            p_exists = p.exists()
        except OSError:
            return
        if not p_exists:
            return
        try:
            entries = list(p.iterdir())
        except OSError:
            return
        direct_has = False
        subdirs = []
        for e in entries:
            try:
                if e.is_dir():
                    _name = (e.name or '')
                    _kw_hit = any(k and k in _name.lower() for k in _SKIP_KEYWORDS)
                    if e.name not in SKIP and not e.name.startswith(('.', '$')) and not _kw_hit:
                        subdirs.append(e)
                elif e.is_file():
                    if e.suffix.lower() in (PHOTO_EXTS | VIDEO_EXTS) and not e.name.startswith('._'):
                        direct_has = True
            except OSError:
                continue
        if direct_has:
            norm = str(p).rstrip('/\\')
            if norm not in seen:
                seen.add(norm)
                discovered.append({'path': str(p), 'name': p.name or norm, 'is_current': _is_under_root(p)})
        for s in subdirs[:80]:
            rec(s, depth + 1)

    # 基础扫描路径
    scan_paths = []
    if _os_type == 'windows':
        import string
        for letter in string.ascii_uppercase:
            drive = f'{letter}:\\'
            if Path(drive).exists():
                scan_paths.append(Path(drive))
    else:
        scan_paths = [Path(p) for p in _plat.get_default_photo_roots()]
    for r in PHOTO_ROOTS:
        try:
            rp = Path(r)
            if not any(str(rp) == str(x) for x in scan_paths):
                scan_paths.append(rp)
        except Exception:
            pass

    for base in scan_paths:
        rec(base, 0)

    # 去重并压回已配置的根路径（标 is_current=true，供重新扫描显示）
    unique = []
    done_paths = set()
    for d in discovered:
        if d['path'] not in done_paths:
            done_paths.add(d['path'])
            unique.append(d)

    return unique

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



_COVER_CACHE = {}  # v5.0 内存封面缓存: path -> cover dict


def _get_first_photo_cover(album_path):
    """从目录取第一个可用媒体文件做封面（v5.0 三层缓存：内存→缓存文件→磁盘）"""
    if album_path in _COVER_CACHE:
        return _COVER_CACHE[album_path]
    cover = _get_first_photo_cover_impl(album_path)
    if cover is not None:
        _COVER_CACHE[album_path] = cover
    return cover


def _get_first_photo_cover_impl(album_path):
    """封面真实计算：优先读 photo_lists 缓存文件（忽略24h过期），无缓存才扫磁盘"""
    cp = PHOTO_LIST_DIR / (hashlib.md5(album_path.encode()).hexdigest() + '.json')
    if cp.exists():
        try:
            cached = json.loads(cp.read_text(encoding='utf-8'))
            if cached:
                for m in cached:
                    if m.get('type') == 'photo':
                        return dict(m)
                return dict(cached[0])  # 全视频，用第一个
        except Exception:
            pass

    # 回退：无缓存/过期才扫磁盘
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

        # 磁盘I/O错误防护：坏盘/拔盘时 exists()/iterdir() 抛 OSError(EIO)

        try:

            root_exists = root_path.exists()

        except OSError:

            root_exists = False

        if not root_exists:

            print(f"  [W] 路径不存在 {root}", flush=True)

            continue

        try:

            entries = list(root_path.iterdir())

        except OSError:

            print(f"  [W] 路径不可读 {root}", flush=True)

            continue

        for entry in entries:

            name = entry.name

            if name.startswith('.') or name.startswith('$') or name in (

                'System Volume Information', '@eaDir', 'FOUND.000', '$RECYCLE.BIN'

            ):

                continue

            if entry.is_dir():

                try:

                    img_count = sum(1 for f in entry.rglob('*') 

                                   if f.suffix.lower() in PHOTO_EXTS and not f.name.startswith('._'))

                    vid_count = sum(1 for f in entry.rglob('*') 

                                   if f.suffix.lower() in VIDEO_EXTS and not f.name.startswith('._'))

                except OSError:

                    # 坏子目录（I/O error）：跳过该相册，不中断整体扫描

                    print(f"  [W] 相册不可读 {entry}", flush=True)

                    continue

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

                        'is_root_self': False,

                    })

                    print(f"  [OK] {name}: {img_count}照片 + {vid_count}视频", flush=True)

        # 根路径本身也含媒体文件（手工添加"本身就是相册"的路径时，如演唱会目录）

        try:

            direct_img = sum(1 for f in root_path.iterdir()

                             if f.is_file() and f.suffix.lower() in PHOTO_EXTS and not f.name.startswith('._'))

            direct_vid = sum(1 for f in root_path.iterdir()

                             if f.is_file() and f.suffix.lower() in VIDEO_EXTS and not f.name.startswith('._'))

        except OSError:

            direct_img = direct_vid = 0

        if direct_img + direct_vid > 0:

            # 用根目录名作为相册名（若与某子相册重名则加后缀）

            album_name = root_path.name

            existing_names = {a['name'] for a in albums if a.get('root') == root_path.name}

            if album_name in existing_names:

                album_name = root_path.name + '（根目录）'

            cover = _get_first_photo_cover(str(root_path))

            albums.append({

                'name': album_name,

                'path': str(root_path),

                'photo_count': direct_img + direct_vid,

                'photo_count_only': direct_img,

                'video_count': direct_vid,

                'root': root_path.name,

                'cover': cover,

                'is_root_self': True,

            })

            print(f"  [OK] {album_name}（根目录本身）: {direct_img}照片 + {direct_vid}视频", flush=True)

    return albums





# ═══════════════════════════════════════════

# 缩略图生成

# ═══════════════════════════════════════════



from PIL import Image, ImageFile, ImageDraw
# HEIC/HEIF 支持（iPhone 照片默认格式）——必须在 Image.open 前注册
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass  # HEIC 文件将被跳过（缩略图返回空），但 jpg/png 不受影响

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

        # RGBA/LA/P/CMYK 不能直接存 JPEG（cannot write mode RGBA as JPEG）→ 转 RGB 白底合并
        if img.mode in ('RGBA', 'LA', 'PA', 'P', 'CMYK'):
            if img.mode in ('P', 'CMYK'):
                img = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            try:
                bg.paste(img, mask=img.split()[-1])
            except Exception:
                bg.paste(img.convert('RGB'))
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

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

# 缩略图进度统计 + 手动触发（2026-08-01 新增）

# ══════════════════════════════════════════



# 全局生成状态（供 /api/thumb_summary 和 /api/thumb/trigger 使用）

THUMB_STATS_CACHE = {'ts': 0, 'data': None}   # 30秒内存缓存

THUMB_RUNNING = False                          # 手动触发生成中标记

THUMB_RUN_LOCK = threading.Lock()              # 进程内防双跑锁

THUMB_PROGRESS = {'total': 0, 'done': 0, 'album': ''}  # 当前任务进度（供前端轮询）

# ══════════════════════════════════════════
# 照片目录扫描（后台线程 + 进度回报，2026-08-25 重构）
# ══════════════════════════════════════════

SCAN_STATE = {
    'running': False,        # 是否有扫描在进行
    'progress': 0,           # 0-100
    'current': '',           # 当前扫描目录
    'discovered_total': 0,   # 已发现目录数
    'done_paths': 0,         # 已遍历路径数
    'result': [],            # 完整结果（扫描完成后填充）
    'scan_id': 0,            # 递增ID，前端识别新一轮
    'error': '',
}

import threading as _th
_SCAN_LOCK = _th.Lock()
_SCAN_COUNTER = [0]

def _run_background_scan():
    """后台扫描线程：遍历所有基础路径，收集含照片目录（全列），不时刷新进度。"""
    global SCAN_STATE
    _SCAN_LOCK.acquire()
    _SCAN_COUNTER[0] += 1
    my_id = _SCAN_COUNTER[0]
    SCAN_STATE['running'] = True
    SCAN_STATE['progress'] = 0
    SCAN_STATE['current'] = '启动扫描...'
    SCAN_STATE['error'] = ''
    SCAN_STATE['scan_id'] = my_id
    SCAN_STATE['result'] = []

    SKIP = {'System Volume Information', '$RECYCLE.BIN', 'Program Files',
            'Program Files (x86)', 'Windows', 'WinSxS', 'Recovery', 'AppData',
            'node_modules', '.git', '$WinREAgent', 'Temp', '@eaDir',
            'FOUND.000', 'lost+found', 'System Volume Information',
            'NASPhotoCache', 'nas-photo-cache', '.cache', 'Cache', 'SoftwareDistribution'}

    MAX_DEPTH = 6
    discovered = []
    seen = set()
    scanned_paths = [0]
    total_estimate = [1]

    def _is_under_root_norm(p):
        np_ = str(p).rstrip('/\\')
        for r_ in PHOTO_ROOTS:
            if np_ == r_.rstrip('/\\'):
                return True
        return False

    def _walk(base, depth):
        if not SCAN_STATE['running'] or SCAN_STATE['scan_id'] != my_id:
            return
        if depth > MAX_DEPTH:
            return
        try:
            if not base.is_dir():
                return
        except OSError:
            return
        try:
            with os.scandir(base) as it:
                entries = list(it)
        except OSError:
            return
        scanned_paths[0] += 1
        # 每扫描若干目录刷新一次进度（百分比以已扫描目录数近似）
        if scanned_paths[0] % 200 == 0:
            SCAN_STATE['current'] = str(base)[:100]
        subdirs = []
        direct_has = False
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name not in SKIP and not e.name.startswith(('.', '$')) and not e.is_symlink():
                        subdirs.append(e.path)
                elif e.is_file():
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in PHOTO_EXTS or ext in VIDEO_EXTS:
                        direct_has = True
            except OSError:
                continue
        if direct_has:
            np_ = str(base).rstrip('/\\')
            if np_ not in seen:
                seen.add(np_)
                discovered.append({'path': str(base), 'name': base.name or str(base),
                                   'is_current': _is_under_root_norm(str(base))})
        for s in subdirs[:120]:
            _walk(Path(s), depth + 1)

    # 基础路径：Windows - 所有盘符；Linux/Mac - 默认根 + PHOTO_ROOTS
    scan_paths = []
    try:
        if _os_type == 'windows':
            import string
            for letter in string.ascii_uppercase:
                drive = f'{letter}:\\'
                dp = Path(drive)
                try:
                    if dp.exists(): scan_paths.append(dp)
                except OSError: pass
        else:
            for r_ in _plat.get_default_photo_roots():
                try: scan_paths.append(Path(r_))
                except Exception: pass
        for r_ in PHOTO_ROOTS:
            try:
                rp = Path(r_)
                if not any(str(rp) == str(x) for x in scan_paths):
                    scan_paths.append(rp)
            except Exception: pass
    except Exception:
        pass

    total_estimate[0] = max(len(scan_paths), 1)
    for bi, base in enumerate(scan_paths):
        if not SCAN_STATE['running'] or SCAN_STATE['scan_id'] != my_id: break
        SCAN_STATE['current'] = f'扫描 {base}...'
        SCAN_STATE['progress'] = int((bi / total_estimate[0]) * 20)  # 前20%按基础路径
        _walk(base, 0)
        SCAN_STATE['progress'] = int(((bi + 1) / total_estimate[0]) * 100)
    SCAN_STATE['result'] = discovered
    SCAN_STATE['discovered_total'] = len(discovered)
    SCAN_STATE['progress'] = 100
    SCAN_STATE['current'] = ''
    SCAN_STATE['running'] = False
    try: _SCAN_LOCK.release()
    except Exception: pass

def start_background_scan():
    """启动后台扫描线程，立即返回。若已在扫描则返回 False。"""
    if SCAN_STATE.get('running'):
        return False
    t = _th.Thread(target=_run_background_scan, daemon=True)
    t.start()
    return True





# 进程间锁文件：cron(nightly_precache.py) 与 Flask 手动触发是不同进程，

# 靠线程锁不够，用锁文件互斥（cron 启动时检查/创建，结束时删除）

THUMB_LOCK_FILE = CACHE_DIR / 'thumb.lock'





def _thumb_lock_acquire():

    """尝试获取进程间锁。成功返回 True，已在跑返回 False。"""

    global THUMB_RUNNING

    if not THUMB_RUN_LOCK.acquire(blocking=False):

        return False

    # 检查锁文件（cron 可能正在跑）

    try:

        if THUMB_LOCK_FILE.exists():

            age = time.time() - THUMB_LOCK_FILE.stat().st_mtime

            if age < 6 * 3600:  # 6小时内创建的锁文件视为有效

                THUMB_RUN_LOCK.release()

                return False

            else:

                THUMB_LOCK_FILE.unlink()  # 过期锁清理

    except OSError:

        pass

    try:

        THUMB_LOCK_FILE.write_text(str(os.getpid()))

    except OSError:

        pass

    THUMB_RUNNING = True

    return True





def _thumb_lock_release():

    global THUMB_RUNNING

    try:

        THUMB_LOCK_FILE.unlink()

    except OSError:

        pass

    THUMB_RUNNING = False

    THUMB_RUN_LOCK.release()





def compute_thumb_stats():

    """统计全部相册缩略图生成进度（照片/视频分开），30秒缓存。



    说明：done 依赖 photo_lists 缓存（夜间任务每次运行都会刷新），

    直接用缓存文件不过期判断——缓存即代表最新扫描结果。

    """

    now = time.time()

    if THUMB_STATS_CACHE['data'] and now - THUMB_STATS_CACHE['ts'] < 30:

        return THUMB_STATS_CACHE['data']



    # total：从相册缓存拿（photo_count_only / video_count）

    albums = app_config_albums()

    photo_total = sum(a.get('photo_count_only', 0) for a in albums)

    video_total = sum(a.get('video_count', 0) for a in albums)



    # done：遍历各相册 photo_lists 缓存文件（直接读磁盘，不过期），

    # 按 type 分组检查 md5 缩略图存在

    photo_done = 0

    video_done = 0

    for album in albums:

        album_key = hashlib.md5(album['path'].encode()).hexdigest()

        cache_file = PHOTO_LIST_DIR / f"{album_key}.json"

        if not cache_file.exists():

            continue

        try:

            photos = json.loads(cache_file.read_text(encoding='utf-8'))

        except Exception:

            continue

        for p in photos:

            ck = hashlib.md5(p['path'].encode()).hexdigest()

            try:

                if (THUMB_DIR_SMALL / f'{ck}.jpg').exists():

                    if p.get('type') == 'video':

                        video_done += 1

                    else:

                        photo_done += 1

            except OSError:

                continue



    data = {

        'photo': {'total': photo_total, 'done': photo_done},

        'video': {'total': video_total, 'done': video_done},

        'running': THUMB_RUNNING,

        'progress': dict(THUMB_PROGRESS),

    }

    THUMB_STATS_CACHE['ts'] = now

    THUMB_STATS_CACHE['data'] = data

    return data





def app_config_albums():

    """从 Flask app config 或 index.json 拿相册列表（compute_thumb_stats 用）"""

    try:

        from flask import current_app

        cache = current_app.config.get('ALBUM_CACHE')

        if cache:

            return cache

    except Exception:

        pass

    try:

        if INDEX_PATH.exists():

            return json.loads(INDEX_PATH.read_text(encoding='utf-8'))

    except Exception:

        pass

    return []





def _run_manual_precache():

    """后台线程：手动触发的全量增量生成（复用 nightly_precache.run_precache）"""

    try:

        import nightly_precache as np

        np.PHOTO_ROOTS = PHOTO_ROOTS

        np.CACHE_DIR = CACHE_DIR

        np.THUMB_DIR_SMALL = THUMB_DIR_SMALL

        np.PHOTO_LIST_DIR = PHOTO_LIST_DIR



        def cb(total, done, album_name):

            THUMB_PROGRESS['total'] = total

            THUMB_PROGRESS['done'] = done

            THUMB_PROGRESS['album'] = album_name

            # 顺便让 stats 缓存失效（进度会变）

            THUMB_STATS_CACHE['data'] = None



        result = np.run_precache(progress_cb=cb)

        print(f"[手动缩略图] 完成: {result}", flush=True)

    except Exception as e:

        print(f"[手动缩略图] 异常: {e}", flush=True)

    finally:

        _thumb_lock_release()





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

        # 相册级启用过滤: 只返回启用的相册

        all_paths = [a['path'] for a in albums]

        enabled_set = _get_enabled_albums_or_init(all_paths)

        albums = [a for a in albums if a['path'] in enabled_set]

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



    # ════════════════════════════════════════

    # 照片目录管理API

    # ════════════════════════════════════════



    @app.route('/api/thumb_summary')

    def api_thumb_summary():

        """缩略图生成进度总览（照片/视频分开），30秒缓存"""

        try:

            return jsonify(compute_thumb_stats())

        except Exception as e:

            return jsonify({'error': str(e), 'photo': {'total': 0, 'done': 0},

                            'video': {'total': 0, 'done': 0}, 'running': False}), 500



    @app.route('/api/thumb/trigger', methods=['POST'])

    def api_thumb_trigger():

        """手动触发增量生成缩略图（防双跑）"""

        if not _thumb_lock_acquire():

            return jsonify({'error': 'already_running',

                            'message': '缩略图生成进行中，请稍候再试'}), 409

        threading.Thread(target=_run_manual_precache, daemon=True).start()

        return jsonify({'ok': True, 'message': '已开始增量生成缩略图'})



    @app.route('/api/photo_roots')

    def api_photo_roots():

        """列出当前所有照片根目录"""

        roots = []

        for r in PHOTO_ROOTS:

            p = Path(r)

            # 磁盘I/O错误防护：坏盘/拔盘时 exists() 会抛 OSError(EIO)

            try:

                exists = p.exists()

                name = p.name if exists else os.path.basename(r)

            except OSError:

                exists = False

                name = os.path.basename(r)

            roots.append({

                'path': r,

                'exists': exists,

                'name': name,

            })

        return jsonify({'roots': roots, 'total': len(roots)})



    @app.route('/api/photo_roots/scan')

    def api_photo_roots_scan():

        """启动后台扫描，发现可用照片目录（递归全列，带进度）。立即返回。"""

        started = start_background_scan()

        return jsonify({'ok': True, 'started': started,
                        'scan_id': SCAN_STATE.get('scan_id', 0)})

    @app.route('/api/photo_roots/scan_progress')

    def api_photo_roots_scan_progress():

        """扫描进度 + 结果（前端轮询）"""

        return jsonify({
            'running': SCAN_STATE.get('running', False),
            'progress': SCAN_STATE.get('progress', 0),
            'current': SCAN_STATE.get('current', ''),
            'discovered_total': SCAN_STATE.get('discovered_total', 0),
            'done_paths': SCAN_STATE.get('done_paths', 0),
            'scan_id': SCAN_STATE.get('scan_id', 0),
            'result': SCAN_STATE.get('result', []),
            'error': SCAN_STATE.get('error', ''),
        })



    @app.route('/api/photo_roots/subdirs', methods=['POST'])

    def api_photo_roots_subdirs():
        # 列出指定目录下含照片的子目录（供前端展开根目录查看子目录）
        data = request.get_json() or {}
        base = (data.get('path') or '').strip()
        if not base:
            return jsonify({'ok': False, 'error': 'path required'}), 400
        bp = Path(base)
        try:
            exists = bp.exists()
        except OSError:
            exists = False
        if not exists or not bp.is_dir():
            return jsonify({'ok': True, 'subdirs': []})
        subdirs = []
        try:
            for entry in bp.iterdir():
                if not entry.is_dir() or entry.name.startswith(('.', '$')):
                    continue
                # 子目录是否直接含照片
                has_media_here = False
                try:
                    for f in list(entry.iterdir())[:25]:
                        if f.is_file() and f.suffix.lower() in (PHOTO_EXTS | VIDEO_EXTS):
                            has_media_here = True
                            break
                except Exception:
                    pass
                # 子目录是否还有更深层含照片的子目录
                has_deeper = False
                if not has_media_here:
                    try:
                        for sub in list(entry.iterdir())[:20]:
                            if sub.is_dir():
                                for f in list(sub.iterdir())[:6]:
                                    if f.is_file() and f.suffix.lower() in (PHOTO_EXTS | VIDEO_EXTS):
                                        has_deeper = True
                                        break
                                if has_deeper:
                                    break
                    except Exception:
                        pass
                # 未配置的子目录才列出（新增模式不显示已配置）
                np = str(entry).rstrip('/\\')
                is_cur = any(np == str(r2).rstrip('/\\') for r2 in PHOTO_ROOTS)
                if is_cur:
                    continue
                subdirs.append({
                    'path': str(entry),
                    'name': entry.name,
                    'is_current': is_cur,
                    'has_media': has_media_here,
                    'has_subdirs': has_deeper,
                })
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)[:80]})
        return jsonify({'ok': True, 'subdirs': subdirs})

    @app.route('/api/photo_roots/add', methods=['POST'])

    def api_photo_roots_add():

        """添加一个或多个照片根目录，重新扫描相册"""

        data = request.get_json() or {}

        paths = data.get('paths', [])

        if isinstance(paths, str):

            paths = [paths]

        if not paths:

            return jsonify({'error': 'paths required'}), 400



        added = []

        reactivated = []

        for p in paths:

            p = p.rstrip('\\/')

            if p not in PHOTO_ROOTS:

                # 若历史里有这条且在停用态 → 重新启用；否则新增

                hist = _get_root_history(p)

                if hist and not hist.get('active'):

                    reactivated.append(p)

                else:

                    added.append(p)

                PHOTO_ROOTS.append(p)

                _activate_root_in_history(p)



        if added or reactivated:

            _save_photo_roots(PHOTO_ROOTS)

            new_albums = scan_albums_local()

            app.config['ALBUM_CACHE'] = new_albums

            try:

                INDEX_PATH.write_text(json.dumps(new_albums, ensure_ascii=False, indent=2), encoding='utf-8')

            except:

                pass

            return jsonify({'ok': True, 'added': added, 'reactivated': reactivated, 'albums': len(new_albums)})



        return jsonify({'ok': True, 'added': [], 'message': '路径已在列表中'})



    @app.route('/api/photo_roots/remove', methods=['POST'])

    def api_photo_roots_remove():

        """移除一个照片根目录，重新扫描相册（彻底删除，不保留历史）"""

        data = request.get_json() or {}

        path = data.get('path', '')

        if not path:

            return jsonify({'error': 'path required'}), 400



        path = path.rstrip('\\/')

        if path in PHOTO_ROOTS:

            PHOTO_ROOTS.remove(path)

            # 彻底删除：config.py 移除 + 历史文件里也删除（不再保留可重启用）

            _delete_root_from_history(path)

            _save_photo_roots(PHOTO_ROOTS)

            new_albums = scan_albums_local()

            app.config['ALBUM_CACHE'] = new_albums

            try:

                INDEX_PATH.write_text(json.dumps(new_albums, ensure_ascii=False, indent=2), encoding='utf-8')

            except:

                pass

            return jsonify({'ok': True, 'removed': path, 'albums': len(new_albums)})



        return jsonify({'error': '路径不在列表中'}), 404



    @app.route('/api/photo_roots/history')

    def api_photo_roots_history():

        """返回完整历史清单（含停用的），带活跃/存在状态"""

        history = _load_history()

        out = []

        for r in history:

            p = Path(r['path'])

            # 磁盘I/O错误防护：坏盘/拔盘时 exists() 抛 OSError(EIO)

            try:

                exists = p.exists()

            except OSError:

                exists = False

            out.append({

                'path': r['path'],

                'active': r.get('active', True),

                'added_at': r.get('added_at'),

                'removed_at': r.get('removed_at'),

                'exists': exists,

                'name': p.name if exists else os.path.basename(r['path']),

            })

        return jsonify({'history': out, 'total': len(out)})



    @app.route('/api/photo_roots/albums')

    def api_photo_roots_albums():

        """返回所有相册(按根分组, 带enabled标记)。前端管理面板数据源。

        结构: {groups: [{root, albums: [{path,name,enabled,photo_count}]}], total}

        """

        # 相册候选: 优先用缓存, 无缓存才扫描
        albums = app.config.get('ALBUM_CACHE') or scan_albums_local()

        # enabled 清单
        all_paths = [a.get('path') for a in albums]
        enabled_set = _get_enabled_albums_or_init(all_paths)

        # 按根分组
        groups = {}
        for a in albums:
            root_key = a.get('root', '') or '其他'
            if root_key not in groups:
                groups[root_key] = []
            groups[root_key].append({
                'path': a.get('path'),
                'name': a.get('name'),
                'enabled': a.get('path') in enabled_set,
                'photo_count': a.get('photo_count', a.get('photo_count_only', 0)),
            })

        result = [{'root': rk, 'albums': g} for rk, g in groups.items()]
        result.sort(key=lambda x: x['root'])

        return jsonify({'groups': result, 'total': len(albums)})



    @app.route('/api/photo_roots/enable', methods=['POST'])

    def api_photo_roots_enable():

        # 相册级启用: 加入 enabled_albums, 自动补父根

        data = request.get_json() or {}

        paths = data.get('paths', [])

        if isinstance(paths, str):

            paths = [paths]

        if not paths:

            return jsonify({'error': 'paths required'}), 400

        paths = [p.rstrip('/\\') for p in paths]

        all_paths = [a.get('path') for a in (app.config.get('ALBUM_CACHE') or scan_albums_local())]

        enabled_set = _get_enabled_albums_or_init(all_paths)

        enabled_set.update(paths)

        _save_enabled_albums(enabled_set)

        # 补父根

        added_roots = []

        for p in paths:

            if not _is_under_any_root(p):

                parent = str(Path(p).parent)

                if parent and parent not in PHOTO_ROOTS:

                    PHOTO_ROOTS.append(parent)

                    added_roots.append(parent)

        if added_roots:

            # 新增了父根(扫描范围扩大), 需要重扫缓存以纳入新相册

            _save_photo_roots(PHOTO_ROOTS)

            new_albums = scan_albums_local()

            app.config['ALBUM_CACHE'] = new_albums

            try:

                INDEX_PATH.write_text(json.dumps(new_albums, ensure_ascii=False, indent=2), encoding='utf-8')

            except:

                pass

        else:

            # 路径已在扫描范围, 缓存内容未变, 无需重扫(保留缓存)

            new_albums = app.config.get('ALBUM_CACHE') or []

        return jsonify({'ok': True, 'enabled': paths, 'albums': len(new_albums)})



    @app.route('/api/photo_roots/disable', methods=['POST'])

    def api_photo_roots_disable():

        # 相册级禁用: 从 enabled_albums 移除(不再显示)

        data = request.get_json() or {}

        paths = data.get('paths', [])

        if isinstance(paths, str):

            paths = [paths]

        if not paths:

            return jsonify({'error': 'paths required'}), 400

        paths = [p.rstrip('/\\') for p in paths]

        all_paths = [a.get('path') for a in (app.config.get('ALBUM_CACHE') or scan_albums_local())]

        enabled_set = _get_enabled_albums_or_init(all_paths)

        enabled_set.difference_update(paths)

        _save_enabled_albums(enabled_set)

        # 只更新启用清单, 不从缓存移除相册(api_albums 的 enabled 过滤自然隐藏它)
        # 这样 enable 时相册仍在缓存, 加入 enabled_set 即恢复显示

        cache = app.config.get('ALBUM_CACHE') or []

        return jsonify({'ok': True, 'disabled': paths, 'albums': len(cache)})



    @app.route('/api/photo_roots/refresh', methods=['GET', 'POST'])

    def api_photo_roots_refresh():

        """重新扫描所有照片根目录，刷新相册列表"""

        new_albums = scan_albums_local()

        app.config['ALBUM_CACHE'] = new_albums

        try:

            INDEX_PATH.write_text(json.dumps(new_albums, ensure_ascii=False, indent=2), encoding='utf-8')

        except:

            pass

        return jsonify({'ok': True, 'albums': len(new_albums)})



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

