#!/usr/bin/env python3
"""
子进程缩略图工作器 — 下载+生成一站式
用法: timeout 120 python3 thumb_worker_full.py <remote_path> <sm_path> <lg_path>
用shell timeout 命令确保整体超时
"""
import sys, io, os, hashlib
from pathlib import Path
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

remote_path = sys.argv[1]
sm_path = sys.argv[2]
lg_path = sys.argv[3]

# SFTP下载
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.2.104', port=22, username='root',
            password='515144zqc@GZ', timeout=15,
            allow_agent=False, look_for_keys=False)
transport = ssh.get_transport()
transport.set_keepalive(10)
sock = transport.sock
if sock:
    sock.settimeout(20)
sftp = ssh.open_sftp()
with sftp.file(remote_path, 'rb') as f:
    data = f.read()
sftp.close()
ssh.close()

if len(data) < 100:
    sys.exit(2)

# 生成小图
img = Image.open(io.BytesIO(data))
w, h = img.size
ratio = 200 / w if 200 < w else 1
if ratio < 1:
    img_sm = img.resize((200, int(h * ratio)), Image.LANCZOS)
else:
    img_sm = img
img_sm.save(sm_path, 'JPEG', quality=65)

# 生成大图
ratio = 400 / w if 400 < w else 1
if ratio < 1 or (w < 200 and 400 < w):
    img_lg = img.resize((400, int(h * 400 / w)), Image.LANCZOS)
else:
    img_lg = img
img_lg.save(lg_path, 'JPEG', quality=75)
