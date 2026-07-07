"""Debug scan_photos"""
import sys, os, json
sys.path.insert(0, '/home/kintry/.hermes/scripts/nas_photo_gallery')
os.chdir('/home/kintry/.hermes/scripts/nas_photo_gallery')
from pathlib import Path
exec(open('/home/kintry/.hermes/scripts/nas_photo_gallery/app.py').read().split("def create_app")[0])

photos, total = scan_photos('/media/devmon/SNAKE1/庄润晨的影像', 1, 5)
print(f"total={total}, photos={len(photos)}")
for p in photos:
    print(f"  filename={p['filename']}, path={p['path']}, mtime={p['mtime']}")
