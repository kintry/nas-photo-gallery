# -*- coding: utf-8 -*-
"""初始化照片目录配置脚本（独立运行）

用途：NAS 相册首次安装后，递归扫描目标设备本地所有"直接含照片"的目录，
      生成 config.py（PHOTO_ROOTS）。实现"初始化时一次性全量选择扫描出的目录"。

说明：
  - 若已存在含 PHOTO_ROOTS 的 config.py，则直接复用（重装场景，卸载时保留了 config.py）
  - 递归扫描到"照片文件直接位于该目录"的层，把每个这样的目录作为根目录加入 PHOTO_ROOTS
  - 生成的 config.py 之后仍可在管理面板手动增删

调用（目标设备 app/ 目录下 + venv python）:
    python bootstrap_config.py [--config 路径] [--max-roots N] [--depth 4]
"""
import os
import sys
import argparse

PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.heif',
              '.tif', '.tiff', '.JPG', '.JPEG', '.PNG', '.HEIC', '.HEIF', '.jfif'}
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.3gp', '.webm', '.MP4', '.MOV',
              '.MKV', '.AVI', '.wmv', '.flv'}

SKIP_DIRS = {
    'System Volume Information', '$RECYCLE.BIN', 'Program Files', 'Program Files (x86)',
    'Windows', 'Recovery', 'Users', 'AppData', 'Temp', 'tmp', 'node_modules', '.git',
    '$WinREAgent', 'lost+found', 'Recycle.Bin', 'boot', 'proc', 'sys', 'dev', 'run', 'etc',
    'venv', '__pycache__', '.cache', 'Thumbs.db', 'Desktop.ini', 'store', 'programdata',
}


def _is_media_file(name):
    return os.path.splitext(name)[1] in PHOTO_EXTS | VIDEO_EXTS


def _scan_root(root, depth, out, seen):
    """递归扫描 root，找出所有"直接含媒体文件"的目录（照片所在层）。"""
    try:
        entries = list(os.scandir(root))
    except Exception:
        return
    has_media_here = False
    subdirs = []
    for e in entries:
        if e.is_file():
            if _is_media_file(e.name):
                has_media_here = True
        elif e.is_dir() and not e.name.startswith('.') and e.name not in SKIP_DIRS and not e.is_symlink():
            subdirs.append(e.path)
    # 本目录直接含照片 → 作为一个根目录
    if has_media_here:
        out.append(root)
        return  # 不再下钻（该层就是相册）
    # 否则继续下钻
    if depth > 0:
        for sub in subdirs:
            _scan_root(sub, depth - 1, out, seen)


def candidate_top_dirs():
    """返回平台相关的顶层扫描起点"""
    tops = []
    if sys.platform in ('linux', 'darwin'):
        for base in ['/media', '/mnt', '/home', '/root', '/data']:
            if os.path.isdir(base):
                try:
                    for e in os.scandir(base):
                        if e.is_dir() and not e.name.startswith('.'):
                            tops.append(e.path)
                except Exception:
                    pass
    else:  # windows
        for letter in 'ABCDEFGH':
            d = letter + ':\\'
            if os.path.isdir(d):
                try:
                    for e in os.scandir(d):
                        if e.is_dir() and e.name not in SKIP_DIRS and not e.name.startswith(('$', '.')):
                            tops.append(e.path)
                except Exception:
                    pass
    return sorted(set(tops))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=None, help='写出的 config.py 路径')
    parser.add_argument('--max-roots', type=int, default=0, help='最多保留N个根目录(0=不限)')
    parser.add_argument('--depth', type=int, default=5, help='递归扫描深度')
    args = parser.parse_args()

    config_path = args.config or os.path.join(os.getcwd(), 'config.py')

    # 已存在含 PHOTO_ROOTS 的 config → 直接复用（重装沿用）
    if os.path.exists(config_path):
        try:
            ns = {}
            exec(open(config_path, encoding='utf-8').read(), ns)
            existing = ns.get('PHOTO_ROOTS') or []
            if existing:
                print(f'BOOTSTRAP_EXISTING={len(existing)}')
                return 0
        except Exception:
            pass

    roots = []
    seen = set()
    for top in candidate_top_dirs():
        _scan_root(top, args.depth, roots, seen)

    # 去重
    seen_paths = set()
    uniq = []
    for r in roots:
        rr = r.rstrip('/\\')
        if rr not in seen_paths:
            seen_paths.add(rr)
            uniq.append(rr)

    if args.max_roots and len(uniq) > args.max_roots:
        uniq = uniq[:args.max_roots]

    lines = ['# -*- coding: utf-8 -*-', 'PHOTO_ROOTS = [']
    for r in uniq:
        lines.append("    r'{}',".format(r))
    lines.append(']')
    content = '\n'.join(lines) + '\n'

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print('BOOTSTRAP_ERROR=' + str(e))
        return 1

    print(f'BOOTSTRAP_ROOTS={len(uniq)}')
    for r in uniq:
        print('  - ' + r)
    return 0


if __name__ == '__main__':
    sys.exit(main())
