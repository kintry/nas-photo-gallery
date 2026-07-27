#!/usr/bin/env python3
"""
夜间全量缩略图预生成脚本 — 增量模式
=======================================
部署到设备的 app/ 目录下，由 Hermes cron job (凌晨3:00) 通过 SSH 触发。

特性：
- 增量：已有缓存的照片零成本跳过，只生成缺失的缩略图
- 全量：不限每相册数量、不跳过超大相册
- 安全：每张照片用独立子进程 + timeout 兜底，防止 Pillow 卡死
- 跨平台：同时支持 Linux (NAS) 和 Windows (HP)
- 自包含：直接读 config.py，不依赖 app.py 的 Flask 环境

用法：
    python3 nightly_precache.py                          # 默认模式
    python3 nightly_precache.py --force                  # 强制重新生成全部
    python3 nightly_precache.py --album "相册名称"        # 只处理指定相册
"""

import sys
import os
import json
import time
import hashlib
import subprocess
import re
from pathlib import Path

# ═══════════════════════════════════════════
# 配置加载
# ═══════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent

# 尝试读 config.py（由安装向导生成）
PHOTO_ROOTS = []
CACHE_DIR = SCRIPT_DIR / 'cache'

_config_py = SCRIPT_DIR / 'config.py'
if _config_py.exists():
    try:
        exec(_config_py.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[W] config.py 加载失败: {e}", flush=True)

# 确保 CACHE_DIR 是 Path 对象
if not isinstance(CACHE_DIR, Path):
    CACHE_DIR = Path(str(CACHE_DIR))

# 是否强制重新生成
FORCE_REGEN = '--force' in sys.argv

# ═══════════════════════════════════════════
# 缓存目录
# ═══════════════════════════════════════════

THUMB_DIR = CACHE_DIR / 'thumbs'
THUMB_DIR_SMALL = THUMB_DIR / 'sm'
INDEX_PATH = CACHE_DIR / 'index.json'
PHOTO_LIST_DIR = CACHE_DIR / 'photo_lists'
LOG_PATH = SCRIPT_DIR / 'nightly_precache.log'

os.makedirs(THUMB_DIR_SMALL, exist_ok=True)
os.makedirs(PHOTO_LIST_DIR, exist_ok=True)

# ── 支持的格式 ──
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.mts', '.m2ts', '.3gp', '.wmv', '.mpg', '.mpeg'}
PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

# ═══════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════

def log(msg):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    print(line, flush=True)

# ═══════════════════════════════════════════
# 缩略图生成（独立子进程 + timeout）
# ═══════════════════════════════════════════

WORKER_SCRIPT = ''


def gen_thumbnail(photo_path):
    """生成一张缩略图，放入子进程 + timeout 兜底"""
    key = hashlib.md5(photo_path.encode()).hexdigest()
    sm_path = THUMB_DIR_SMALL / f"{key}.jpg"

    if sm_path.exists() and sm_path.stat().st_size > 100 and not FORCE_REGEN:
        return True  # 已有缓存，跳过

    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / 'thumb_worker.py'), photo_path, str(sm_path), '400'],
            capture_output=True, timeout=60
        )
        if result.returncode == 0:
            return True
        elif result.returncode == 2:
            log(f"    ⚠ Pillow不可用，跳过: {Path(photo_path).name[:40]}")
            return False
        else:
            err = result.stderr.decode('utf-8', errors='replace')[:150].strip()
            if err:
                log(f"    ⚠ 失败: {Path(photo_path).name[:40]} - {err}")
            return False
    except subprocess.TimeoutExpired:
        log(f"    ⚠ 超时(60s): {Path(photo_path).name[:40]}")
        return False
    except Exception as e:
        log(f"    ⚠ 异常: {Path(photo_path).name[:40]} - {e}")
        return False


# ═══════════════════════════════════════════
# 相册扫描
# ═══════════════════════════════════════════

def scan_albums():
    """扫描所有照片根目录，返回相册列表（与app.py scan_albums_local一致）"""
    albums = []
    for root in PHOTO_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            log(f"  [W] 路径不存在 {root}")
            continue
        try:
            entries = list(root_path.iterdir())
        except PermissionError:
            log(f"  [W] 无权限访问 {root}")
            continue

        sub_dirs = [e for e in entries if e.is_dir()
                    and not e.name.startswith('.')
                    and not e.name.startswith('$')
                    and e.name not in ('System Volume Information', '@eaDir', 'FOUND.000', '$RECYCLE.BIN', 'nas-photo-cache', 'DELL笔记本电脑C盘', 'DELL笔记本电脑D盘')]
        root_files = [e for e in entries if e.is_file()
                      and e.suffix.lower() in PHOTO_EXTS.union(VIDEO_EXTS)
                      and not e.name.startswith('.')
                      and not e.name.startswith('._')]

        if not sub_dirs and root_files:
            # 根目录散落照片
            img_count = sum(1 for f in root_files if f.suffix.lower() in PHOTO_EXTS)
            vid_count = sum(1 for f in root_files if f.suffix.lower() in VIDEO_EXTS)
            total_media = len(root_files)
            albums.append({
                'name': root_path.name,
                'path': str(root_path),
                'photo_count': total_media,
                'photo_count_only': img_count,
                'video_count': vid_count,
                'root': root_path.parent.name if root_path.parent else '',
            })
        else:
            for entry in sub_dirs:
                name = entry.name
                try:
                    all_files = list(entry.rglob('*'))
                except (PermissionError, OSError):
                    continue
                img_count = sum(1 for f in all_files
                                if f.suffix.lower() in PHOTO_EXTS and not f.name.startswith('._'))
                vid_count = sum(1 for f in all_files
                                if f.suffix.lower() in VIDEO_EXTS and not f.name.startswith('._'))
                total_media = img_count + vid_count
                if total_media > 0:
                    albums.append({
                        'name': name,
                        'path': str(entry),
                        'photo_count': total_media,
                        'photo_count_only': img_count,
                        'video_count': vid_count,
                        'root': root_path.name,
                    })
    return albums


def get_all_photos(album_path):
    """获取相册的所有照片（从缓存或重新扫描）"""
    album_key = hashlib.md5(album_path.encode()).hexdigest()
    cache_file = PHOTO_LIST_DIR / f"{album_key}.json"

    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            if data:
                return data
        except:
            pass

    # 重新扫描
    album = Path(album_path)
    if not album.exists():
        return []

    photos = []
    try:
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
                photos.append({
                    'filename': fn,
                    'path': str(fp),
                    'size': st.st_size,
                    'mtime': st.st_mtime,
                    'id': hashlib.md5(str(fp).encode()).hexdigest()[:12],
                    'type': 'video' if ext in VIDEO_EXTS else 'photo',
                })
            except:
                continue
    except (PermissionError, OSError):
        return []

    photos.sort(key=lambda x: x['mtime'], reverse=True)
    cache_file.write_text(json.dumps(photos, ensure_ascii=False, default=str), encoding='utf-8')
    return photos


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

def main():
    t_start = time.time()

    log("=" * 60)
    log("🌙 夜间全量缩略图预生成 — 开始")
    if FORCE_REGEN:
        log("   [强制模式] 将重新生成所有缩略图")
    log(f"   照片根目录: {len(PHOTO_ROOTS)} 个")
    log(f"   缓存目录: {CACHE_DIR}")

    # Step 1: 扫描相册
    log("\n📁 Step 1/3: 扫描相册目录...")
    albums = scan_albums()
    if not albums:
        log("   ❌ 未找到任何相册，请检查 PHOTO_ROOTS 配置")
        return

    log(f"   ✅ 共 {len(albums)} 个相册")
    for a in albums:
        log(f"      📂 {a['name']}: {a['photo_count_only']}照片 + {a['video_count']}视频")

    # Step 2: 更新 index.json
    log("\n💾 Step 2/3: 更新相册索引缓存...")
    INDEX_PATH.write_text(json.dumps(albums, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f"   ✅ index.json 已更新")

    # Step 3: 增量生成缩略图
    log("\n🖼️  Step 3/3: 增量生成缩略图...")
    total_processed = 0
    total_skipped = 0
    total_failed = 0
    total_albums_done = 0

    for album in albums:
        album_name = album['name']
        photos = get_all_photos(album['path'])

        if not photos:
            log(f"   ⏭ 空相册: {album_name}")
            continue

        # 区分照片和视频
        photo_files = [p for p in photos if p.get('type') == 'photo' or p['path'].lower().rsplit('.',1)[-1] in ('jpg','jpeg','png','gif','bmp','webp')]
        video_files = [p for p in photos if p.get('type') == 'video' or p['path'].lower().rsplit('.',1)[-1] in ('mp4','mov','avi','mkv','mts','m2ts','3gp','wmv','mpg','mpeg')]

        log(f"\n   📂 {album_name}: {len(photo_files)}照片 + {len(video_files)}视频")

        # — 照片缩略图 —
        photo_to_gen = []
        photo_skip = 0
        for p in photo_files:
            ck = hashlib.md5(p['path'].encode()).hexdigest()
            sm_path = THUMB_DIR_SMALL / f"{ck}.jpg"
            if sm_path.exists() and sm_path.stat().st_size > 100 and not FORCE_REGEN:
                photo_skip += 1
            else:
                photo_to_gen.append(p['path'])

        if photo_to_gen:
            log(f"     照片: 待生成 {len(photo_to_gen)} 张 (已有{photo_skip}张, 跳过)")
            done = 0
            fail = 0
            for i, path in enumerate(photo_to_gen):
                ok = gen_thumbnail(path)
                if ok:
                    done += 1
                else:
                    fail += 1
                if (i+1) % 50 == 0 or i+1 == len(photo_to_gen):
                    log(f"       {i+1}/{len(photo_to_gen)} 张... (成功{done}, 失败{fail})")
            total_processed += done
            total_failed += fail
        else:
            log(f"     照片: 全部已缓存 ({photo_skip}张, 跳过)")

        # — 视频缩略图 —
        video_to_gen = []
        video_skip = 0
        for p in video_files:
            ck = hashlib.md5(p['path'].encode()).hexdigest()
            sm_path = THUMB_DIR_SMALL / f"{ck}.jpg"
            if sm_path.exists() and sm_path.stat().st_size > 1000 and not FORCE_REGEN:
                video_skip += 1
            else:
                video_to_gen.append(p['path'])

        if video_to_gen:
            log(f"     视频: 待生成 {len(video_to_gen)} 个 (已有{video_skip}个, 跳过)")
            done = 0
            fail = 0
            for i, path in enumerate(video_to_gen):
                ok = gen_thumbnail(path)
                if ok:
                    done += 1
                else:
                    fail += 1
                if (i+1) % 30 == 0 or i+1 == len(video_to_gen):
                    log(f"       {i+1}/{len(video_to_gen)} 个... (成功{done}, 失败{fail})")
            total_processed += done
            total_failed += fail
        else:
            log(f"     视频: 全部已缓存 ({video_skip}个, 跳过)")

        total_skipped += photo_skip + video_skip
        total_albums_done += 1

    # 统计
    t_elapsed = time.time() - t_start
    sm_count = len(list(THUMB_DIR_SMALL.glob('*.jpg')))

    log("\n" + "=" * 60)
    log("🎉 夜间全量缩略图预生成 — 完成!")
    log(f"   处理相册: {total_albums_done}/{len(albums)}")
    log(f"   本次新生成: {total_processed} 张")
    log(f"   已有跳过: {total_skipped} 张")
    log(f"   失败: {total_failed} 张")
    log(f"   总计缓存: {sm_count} 张小图")
    log(f"   耗时: {t_elapsed/60:.1f} 分钟")
    log("=" * 60)


if __name__ == '__main__':
    main()
