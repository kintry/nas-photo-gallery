#!/usr/bin/env python3
"""
全量缩略图生成脚本 —— 不限制数量，处理所有照片（含大文件）
每个照片用独立进程+shell timeout命令，防止Pillow卡死
"""
import sys, os, json, hashlib, subprocess, time, re, glob
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / 'cache'
THUMB_DIR = CACHE_DIR / 'thumbs'
THUMB_DIR_SMALL = THUMB_DIR / 'sm'
THUMB_DIR_LARGE = THUMB_DIR / 'lg'
INDEX_PATH = CACHE_DIR / 'index.json'
PHOTO_LIST_DIR = CACHE_DIR / 'photo_lists'

NAS_HOST = '192.168.2.104'
NAS_USER = 'root'
NAS_PASS = '515144zqc@GZ'

LOG_PATH = SCRIPT_DIR / 'full_precache.log'

def log(msg):
    ts = time.strftime('%H:%M:%S')
    with open(LOG_PATH, 'a') as f:
        f.write(f'[{ts}] {msg}\n')
    print(f'[{ts}] {msg}', flush=True)

def gen_one(remote_path):
    """生成一张照片的小图和大图 — 全部放入子进程，用shell timeout兜底"""
    key = hashlib.md5(remote_path.encode()).hexdigest()
    sm_path = THUMB_DIR_SMALL / f"{key}.jpg"
    lg_path = THUMB_DIR_LARGE / f"{key}.jpg"

    ok_sm = sm_path.exists()
    ok_lg = lg_path.exists()
    if ok_sm and ok_lg:
        return True, True

    worker = os.path.join(str(SCRIPT_DIR), 'thumb_worker_full.py')
    fn = remote_path.split('/')[-1][:40]
    start = time.time()
    
    try:
        result = subprocess.run(
            ['timeout', '120', sys.executable, worker, remote_path, str(sm_path), str(lg_path)],
            capture_output=True, timeout=125
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            ok_sm = sm_path.exists()
            ok_lg = lg_path.exists()
            if ok_sm and ok_lg:
                return True, True
            else:
                log(f"    ⚠ 无输出文件({elapsed:.0f}s): {fn}")
                return False, False
        elif result.returncode == 124:
            log(f"    ⚠ 超时({elapsed:.0f}s): {fn}")
            return False, False
        else:
            err = result.stderr.decode('utf-8', errors='replace')[:200].strip()
            log(f"    ⚠ rc={result.returncode}({elapsed:.0f}s): {fn} - {err}")
            return False, False
    except subprocess.TimeoutExpired:
        log(f"    ⚠ 超时(125s): {fn}")
        return False, False
    except Exception as e:
        log(f"    ⚠ 异常: {fn} - {e}")
        return False, False

def get_all_photos(album_path):
    """从缓存或扫描获取相册全部照片"""
    album_key = hashlib.md5(album_path.encode()).hexdigest()
    cache_file = PHOTO_LIST_DIR / f"{album_key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            if data:
                return data
        except:
            pass

    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(NAS_HOST, port=22, username=NAS_USER,
                    password=NAS_PASS, timeout=15,
                    allow_agent=False, look_for_keys=False)
        sftp = ssh.open_sftp()
        try:
            items = sftp.listdir_attr(album_path)
        except:
            ssh.close()
            return []

        photos = []
        for attr in items:
            fn = attr.filename
            if fn.startswith('.') or fn.startswith('._'):
                continue
            ext = fn.lower().rsplit('.', 1)[-1] if '.' in fn else ''
            if ext not in ('jpg', 'jpeg', 'png'):
                continue
            full_path = album_path.rstrip('/') + '/' + fn
            photos.append({
                'filename': fn,
                'path': full_path,
                'size': attr.st_size,
                'mtime': attr.st_mtime,
                'id': hashlib.md5(full_path.encode()).hexdigest()[:12],
            })

        sftp.close()
        ssh.close()
        photos.sort(key=lambda x: x['mtime'], reverse=True)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        PHOTO_LIST_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(photos, ensure_ascii=False, default=str))
        return photos
    except Exception as e:
        log(f"  ⚠ 扫描失败 {album_path}: {e}")
        return []

def main():
    if not INDEX_PATH.exists():
        log("❌ 未找到相册索引文件")
        return

    albums = json.loads(INDEX_PATH.read_text())
    log(f"📸 全量缩略图生成开始 — 共 {len(albums)} 个相册")

    skip_names = ['叶丽芳手机相片（iPhone11）', 'ICLOUD照片']

    total_done = 0
    total_fail = 0
    total_albums_processed = 0

    for album in albums:
        if album['name'] in skip_names:
            log(f"⏭ 跳过超大相册: {album['name']}")
            continue

        photos = get_all_photos(album['path'])
        if not photos:
            log(f"  ⚠ 空相册: {album['name']}")
            continue

        log(f"  📁 {album['name']} ({len(photos)}张照片)")

        to_gen = []
        existing = 0
        for p in photos:
            fn = p['filename']
            if fn.startswith('.') or fn.startswith('._'):
                continue
            ck = hashlib.md5(p['path'].encode()).hexdigest()
            sm_path = THUMB_DIR_SMALL / f"{ck}.jpg"
            lg_path = THUMB_DIR_LARGE / f"{ck}.jpg"
            if sm_path.exists() and lg_path.exists():
                existing += 1
            else:
                to_gen.append(p['path'])

        if not to_gen:
            log(f"  ✅ 全部已缓存 ({existing}张)")
            continue

        log(f"  待生成: {len(to_gen)} 张 (已有{existing}张)")
        total_albums_processed += 1

        _t0 = time.time()
        for i, path in enumerate(to_gen):
            ok_sm, ok_lg = gen_one(path)
            if ok_sm and ok_lg:
                total_done += 1
            else:
                total_fail += 1

            elapsed = time.time() - _t0
            speed = (i+1) / elapsed if elapsed > 0 else 0
            remaining = (len(to_gen) - i - 1) / speed if speed > 0 else 0
            log(f"    {i+1}/{len(to_gen)} {'✅' if ok_sm and ok_lg else '❌'} 累计成功{total_done} 失败{total_fail} ETA~{remaining/60:.0f}分")

        log(f"  ✅ {album['name']} 完成")

    sm_count = len(list(THUMB_DIR_SMALL.glob('*.jpg')))
    lg_count = len(list(THUMB_DIR_LARGE.glob('*.jpg')))

    log(f"\n{'='*50}")
    log(f"🎉 全量缩略图生成完成!")
    log(f"  处理相册: {total_albums_processed}/{len(albums)}")
    log(f"  本次新生成: {total_done} 张 (小图+大图)")
    log(f"  本次失败: {total_fail} 张")
    log(f"  总计缓存: 小图 {sm_count} 张, 大图 {lg_count} 张")

if __name__ == '__main__':
    main()
