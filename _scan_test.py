"""快速扫描测试"""
import paramiko, json
from pathlib import Path

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

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(NAS_HOST, port=22, username=NAS_USER, password=NAS_PASS, timeout=10, allow_agent=False, look_for_keys=False)
sftp = ssh.open_sftp()

albums = []
for root in PHOTO_ROOTS:
    try:
        entries = sorted(sftp.listdir_attr(root), key=lambda e: e.filename)
    except Exception as ex:
        print(f"⚠️ 无法访问 {root}: {ex}")
        continue
    for e in entries:
        name = e.filename
        if name.startswith('.') or name.startswith('$') or name in ('System Volume Information', '@eaDir', 'FOUND.000'):
            continue
        path = f"{root}/{name}"
        try:
            sftp.listdir(path)  # 是目录
            c2 = ssh.exec_command(f'find "{path}" -maxdepth 2 -type f \\( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \\) 2>/dev/null | wc -l', timeout=30)
            count = int(c2[1].read().decode().strip() or 0)
            if count > 0:
                print(f"✅ {name:20s} ({root.split('/')[-1]:12s}) → {count:5d}张")
                albums.append({'name': name, 'path': path, 'photo_count': count, 'root': root.split('/')[-1]})
            else:
                print(f"❌ {name:20s} ({root.split('/')[-1]:12s}) → 0张")
        except:
            print(f"⚠️ {name:20s} — 不是目录")

sftp.close()
ssh.close()
print(f"\n共 {len(albums)} 个有照片的相册")
for a in albums:
    print(f"  {a['name']:25s} @ {a['root']:12s} → {a['photo_count']}张")
