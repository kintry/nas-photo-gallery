"""
NAS相册 — macOS平台适配模块
适用系统: macOS 12+ (Intel / Apple Silicon)
"""

import os
import sys
import socket
import subprocess
import plistlib
from pathlib import Path


# ═══════════════════════════════════════════
# 路径工具
# ═══════════════════════════════════════════

def norm_path(path):
    """macOS路径标准化"""
    return Path(path).as_posix()

def join_path(*parts):
    """macOS路径拼接"""
    return '/'.join(parts)


# ═══════════════════════════════════════════
# 系统检测
# ═══════════════════════════════════════════

def _run(cmd, timeout=10):
    """运行shell命令"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))
        return r.stdout.strip()
    except:
        return ''


def get_platform_info():
    """获取系统信息"""
    info = {
        'hostname': socket.gethostname(),
    }
    
    # CPU
    info['arch'] = _run('uname -m')
    try:
        info['cores'] = int(_run('sysctl -n hw.logicalcpu') or '0')
    except:
        info['cores'] = 0
    
    info['cpu_model'] = _run('sysctl -n machdep.cpu.brand_string')
    
    # 内存
    try:
        mem_bytes = int(_run('sysctl -n hw.memsize') or '0')
        info['mem_total'] = mem_bytes
    except:
        info['mem_total'] = 0
    
    # 可用内存 - macOS用vm_stat
    vm_out = _run("vm_stat | awk '/free/ {print $NF}' | tr -d '.'")
    try:
        free_pages = int(vm_out) if vm_out else 0
        info['mem_avail'] = free_pages * 16384  # 16KB pages
    except:
        info['mem_avail'] = info.get('mem_total', 0) // 2
    
    # 磁盘
    df_out = _run("df -g / | tail -1 | awk '{print $2, $3, $4}'")
    parts = df_out.split()
    if len(parts) >= 3:
        info['disk_total'] = parts[0]
        info['disk_used'] = parts[1]
        info['disk_free'] = parts[2]
    else:
        info['disk_total'] = '0'
        info['disk_free'] = '0'
    
    # OS
    info['os'] = _run('sw_vers -productName') + ' ' + _run('sw_vers -productVersion')
    
    return info


def get_default_cache_dir():
    """macOS默认缓存目录"""
    return Path.home() / 'Library' / 'Caches' / 'nas-photo'


# ═══════════════════════════════════════════
# 照片路径
# ═══════════════════════════════════════════

def get_default_photo_roots():
    """获取macOS默认照片路径"""
    return [
        str(Path.home() / 'Pictures'),
        str(Path.home() / '图片'),
        '/Users/Shared',
    ]


def scan_photo_dirs():
    """扫描macOS本地照片目录"""
    found = []
    # 用户Pictures目录
    pics = Path.home() / 'Pictures'
    if pics.exists():
        found.append(str(pics))
        for p in pics.iterdir():
            if p.is_dir() and not p.name.startswith('.'):
                found.append(str(p))
    
    # Photos Library（系统照片图库）
    photo_lib = Path.home() / 'Pictures' / 'Photos Library.photoslibrary'
    if photo_lib.exists():
        found.append(str(photo_lib))
    
    # 扫描外置硬盘 /Volumes
    volumes = Path('/Volumes')
    if volumes.exists():
        for vol in volumes.iterdir():
            if vol.is_dir() and not vol.name.startswith('.'):
                # 检查有没有照片目录
                for root, dirs, _ in os.walk(str(vol)):
                    for d in dirs:
                        if d.lower() in ('pictures', 'photos', 'dcim', '图片', '照片'):
                            found.append(os.path.join(root, d))
                    if len(found) > 30:
                        return found
                    break  # 只检查一级目录
    
    return found


# ═══════════════════════════════════════════
# 服务管理
# ═══════════════════════════════════════════

def get_python_exe(venv_dir):
    """获取venv中的Python路径"""
    return str(Path(venv_dir) / 'bin' / 'python3')


def is_admin():
    """检查是否管理员（macOS用root检测）"""
    return os.geteuid() == 0 if hasattr(os, 'geteuid') else False


def start_service(venv_dir, app_py, log_file=None):
    """后台启动Flask服务（macOS用nohup）"""
    python_exe = get_python_exe(venv_dir)
    app_dir = str(Path(app_py).parent)
    if not log_file:
        log_file = str(Path(app_dir) / 'server.log')
    
    try:
        with open(log_file, 'a') as log:
            subprocess.Popen(
                [python_exe, app_py],
                cwd=app_dir,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            )
        return True
    except:
        return False


def stop_service():
    """停止Flask服务"""
    try:
        subprocess.run(
            ['pkill', '-f', 'python3.*app.py'],
            capture_output=True, timeout=5
        )
        subprocess.run(
            ['pkill', '-f', 'python.*app.py'],
            capture_output=True, timeout=5
        )
        return True
    except:
        return False


def _get_plist_content(python_exe, app_py, log_file):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nasphoto</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>{app_py}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{str(Path(app_py).parent)}</string>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONIOENCODING</key>
        <string>utf-8</string>
    </dict>
</dict>
</plist>'''


def set_auto_start(venv_dir, app_py):
    """设置macOS LaunchAgent开机自启"""
    python_exe = get_python_exe(venv_dir)
    log_file = str(Path(app_py).parent / 'server.log')
    plist_content = _get_plist_content(python_exe, app_py, log_file)
    
    launch_agents = Path.home() / 'Library' / 'LaunchAgents'
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / 'com.nasphoto.plist'
    
    try:
        plist_path.write_text(plist_content)
        subprocess.run(
            ['launchctl', 'load', str(plist_path)],
            capture_output=True, timeout=10
        )
        return True
    except:
        return False


def unset_auto_start():
    """取消macOS LaunchAgent开机自启"""
    plist_path = Path.home() / 'Library' / 'LaunchAgents' / 'com.nasphoto.plist'
    try:
        subprocess.run(
            ['launchctl', 'unload', str(plist_path)],
            capture_output=True, timeout=10
        )
        plist_path.unlink(missing_ok=True)
        return True
    except:
        return False


def get_service_status():
    """获取服务状态"""
    status = {'running': False, 'pid': 0, 'port': 5000, 'url': ''}
    try:
        out = _run('lsof -i :5000 -P -n 2>/dev/null | grep LISTEN')
        if out:
            status['running'] = True
            parts = out.split()
            if len(parts) >= 2:
                try:
                    status['pid'] = int(parts[1])
                except:
                    pass
    except:
        pass
    return status
