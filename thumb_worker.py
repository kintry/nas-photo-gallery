import sys, os, hashlib
from pathlib import Path
try:
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    Image.MAX_IMAGE_PIXELS = None
except ImportError:
    sys.exit(2)

remote_path = sys.argv[1]
sm_path = sys.argv[2]
size = int(sys.argv[3]) if len(sys.argv) > 3 else 400

video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.mts', '.m2ts', '.3gp', '.wmv', '.mpg', '.mpeg'}
ext = os.path.splitext(remote_path)[1].lower()
is_video = ext in video_exts

if is_video:
    import subprocess as sp
    ffmpeg = '/usr/bin/ffmpeg' if os.path.exists('/usr/bin/ffmpeg') else 'ffmpeg'
    thumb_tmp = Path(sm_path).with_suffix('.tmp.jpg')
    try:
        r = sp.run([ffmpeg, '-y', '-i', remote_path, '-vframes', '1',
                     '-vf', f'scale={size}:-1', '-q:v', '5', str(thumb_tmp)],
                    capture_output=True, timeout=30)
        if r.returncode == 0 and thumb_tmp.exists() and thumb_tmp.stat().st_size > 1000:
            thumb_tmp.rename(sm_path)
            print("OK")
            sys.exit(0)
        if thumb_tmp.exists(): thumb_tmp.unlink()
    except:
        if thumb_tmp.exists(): thumb_tmp.unlink()
    from PIL import ImageDraw
    img = Image.new('RGB', (size, size), (20, 20, 40))
    draw = ImageDraw.Draw(img)
    cx, cy = size//2, size//2
    r2 = size//5
    for ox in range(-r2, r2+1):
        for oy in range(-r2, r2+1):
            if ox*ox + oy*oy <= r2*r2:
                draw.point((cx+ox, cy+oy), fill=(52,152,219))
    ts = r2//2
    draw.polygon([(cx-ts//2, cy-ts), (cx+ts, cy), (cx-ts//2, cy+ts)], fill=(255,255,255))
    img.save(str(sm_path), 'JPEG', quality=70)
    print("OK")
    sys.exit(0)
else:
    try:
        img = Image.open(remote_path)
        w, h = img.size
        if size < w:
            ratio = size / w
            img = img.resize((size, int(h * ratio)), Image.LANCZOS)
        img.save(str(sm_path), 'JPEG', quality=80)
        if Path(sm_path).exists() and Path(sm_path).stat().st_size > 100:
            print("OK")
            sys.exit(0)
        sys.exit(1)
    except:
        sys.exit(1)
