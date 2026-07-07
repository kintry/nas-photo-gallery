#!/usr/bin/env python3
"""批处理缩略图生成（带日志文件）"""
import sys
import os

# 确保输出立即刷新
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# 重定向输出到文件
log_path = '/home/kintry/.hermes/scripts/nas_photo_gallery/precache.log'
lf = open(log_path, 'w', buffering=1)
sys.stdout = lf
sys.stderr = lf

# 执行预生成
exec(open('/home/kintry/.hermes/scripts/nas_photo_gallery/precache_thumbs.py').read())
