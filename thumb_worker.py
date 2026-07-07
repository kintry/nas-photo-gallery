#!/usr/bin/env python3
"""
子进程Pillow缩略图生成器 - 通过临时文件调用，避免-c长命令行问题
用法: python3 thumb_worker.py <size> <quality> <输入文件路径> <输出文件路径>
"""
import sys, io
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

size = int(sys.argv[1])
quality = int(sys.argv[2])
in_path = sys.argv[3]
out_path = sys.argv[4]

with open(in_path, 'rb') as f:
    data = f.read()

img = Image.open(io.BytesIO(data))
w, h = img.size
if size < w:
    ratio = size / w
    img = img.resize((size, int(h * ratio)), Image.LANCZOS)
img.save(out_path, 'JPEG', quality=quality)
