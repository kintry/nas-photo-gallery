#!/usr/bin/env python3
"""后台批量预生成缩略图 - 每个照片用外部timeout命令独立执行"""
import sys, os, json, hashlib, subprocess, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from app import THUMB_DIR_SMALL, THUMB_DIR_LARGE
from app import _get_photo_list_cache, scan_photos, INDEX_PATH

LOG_PATH = os.path.join(SCRIPT_DIR, 'precache.log')

def log(msg):
    with open(LOG_PATH, 'a') as f:
        f.write(msg + '\n')

def gen_one(path, size):
    """用shell timeout命令执行Pillow转换，确保能杀死"""
    key = hashlib.md5(path.encode()).hexdigest()
    out_dir = THUMB_DIR_SMALL if size <= 200 else THUMB_DIR_LARGE
    out_path = os.path.join(str(out_dir), f"{key}.jpg")
    if os.path.exists(out_path):
        return True
    
    # 下载
    import paramiko
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect('192.168.2.104', port=22, username='root',
                    password='515144zqc@GZ', timeout=10,
                    allow_agent=False, look_for_keys=False)
        sftp = ssh.open_sftp()
        with sftp.file(path, 'rb') as f:
            data = f.read()
        sftp.close(); ssh.close()
    except:
        return False
    
    # shell timeout命令 + 独立python进程
    script = (
        "import sys,io;"
        "from PIL import Image,ImageFile;ImageFile.LOAD_TRUNCATED_IMAGES=1;"
        "s=int(sys.argv[1]);d=sys.stdin.buffer.read();"
        "img=Image.open(io.BytesIO(d));w,h=img.size;"
        "if s<w:img=img.resize((s,int(h*s/w)),Image.LANCZOS);"
        "o=io.BytesIO();img.save(o,'JPEG',quality=(65 if s<=200 else 75));"
        "sys.stdout.buffer.write(o.getvalue())"
    )
    try:
        result = subprocess.run(
            ['timeout', '25', sys.executable, '-c', script, str(size)],
            input=data, capture_output=True, timeout=30
        )
        if result.returncode == 0 and result.stdout:
            with open(out_path, 'wb') as f:
                f.write(result.stdout)
            return True
    except:
        pass
    return False

def main():
    log(f"📸 后台批量预生成缩略图（shell timeout模式）")
    
    albums = []
    if os.path.exists(str(INDEX_PATH)):
        albums = json.loads(open(str(INDEX_PATH)).read())
    
    if not albums:
        log("  ❌ 无相册数据")
        return
    
    log(f"  📦 加载 {len(albums)} 个相册")
    
    skip_names = ['叶丽芳手机相片（iPhone11）', 'ICLOUD照片']
    
    total_done = 0
    total_albums = 0
    total_errors = 0
    
    for album in albums:
        if album['name'] in skip_names:
            log(f"  ⏭ 跳过 {album['name']}")
            continue
        
        try:
            photos_cache = _get_photo_list_cache(album['path'])
        except:
            photos_cache = None
        if not photos_cache:
            try:
                photos_cache, _ = scan_photos(album['path'], 1, 999999)
            except:
                log(f"  ⚠️ 无法扫描 {album['name']}")
                continue
        
        if not photos_cache:
            continue
        
        to_gen = []
        for p in photos_cache[:20]:
            fn = p['path'].split('/')[-1]
            if fn.startswith('.') or fn.startswith('._'):
                continue
            if p.get('size', 0) > 1_000_000:
                continue
            ck = hashlib.md5(p['path'].encode()).hexdigest()
            sm_path = os.path.join(str(THUMB_DIR_SMALL), f"{ck}.jpg")
            lg_path = os.path.join(str(THUMB_DIR_LARGE), f"{ck}.jpg")
            if not os.path.exists(sm_path) or not os.path.exists(lg_path):
                to_gen.append(p['path'])
        
        if not to_gen:
            continue
        
        total_albums += 1
        log(f"  📁 {album['name']}: {len(to_gen)} 张待生成...")
        
        for i, path in enumerate(to_gen):
            ok_sm = gen_one(path, 200)
            ok_lg = gen_one(path, 400)
            if ok_sm and ok_lg:
                total_done += 1
            else:
                total_errors += 1
            if (i+1) % 5 == 0 or i == len(to_gen) - 1:
                log(f"    ...{i+1}/{len(to_gen)} 完成, 累计{total_done}张")
        
        log(f"    ✅ 完成")
    
    sm_count = len(os.listdir(str(THUMB_DIR_SMALL)))
    lg_count = len(os.listdir(str(THUMB_DIR_LARGE)))
    log(f"\n  ✅ 全部完成: 覆盖 {total_albums} 个相册, 成功 {total_done} 张, 失败 {total_errors} 张")
    log(f"  小图: {sm_count} 大图: {lg_count}")

if __name__ == '__main__':
    main()
