"""
NAS相册 — Linux平台适配模块
适用系统: Debian/Ubuntu/Armbian/树莓派OS等
"""

import os
import sys
import socket
import subprocess
from pathlib import Path


# ═══════════════════════════════════════════
# 路径工具
# ═══════════════════════════════════════════

def norm_path(path):
    """Linux路径标准化"""
    return Path(path).as_posix()

def join_path(*parts):
    """Linux路径拼接"""
    return '/'.join(parts)


# ═══════════════════════════════════════════
# 系统检测
# ═══════════════════════════════════════════

def get_platform_info():
    """获取系统信息"""
    info = {}
    try:
        info['hostname'] = socket.gethostname()
    except:
        info['hostname'] = 'unknown'
    
    # CPU
    try:
        info['arch'] = subprocess.run(
            ['uname', '-m'], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except:
        info['arch'] = 'unknown'
    
    try:
        cores = subprocess.run(
            ['nproc'], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        info['cores'] = int(cores) if cores else 0
    except:
        info['cores'] = 0
    
    try:
        info['cpu_model'] = subprocess.run(
            ['cat', '/proc/cpuinfo'], capture_output=True, text=True, timeout=5
        ).stdout
        for line in info['cpu_model'].split('\n'):
            if 'model name' in line:
                info['cpu_model'] = line.split(':')[-1].strip()
                break
    except:
        info['cpu_model'] = 'unknown'
    
    # 内存
    try:
        out = subprocess.run(
            ['free', '-b'], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.split('\n'):
            if line.startswith('Mem:'):
                parts = line.split()
                info['mem_total'] = int(parts[1]) if len(parts) > 1 else 0
                info['mem_avail'] = int(parts[6]) if len(parts) > 6 else 0
                break
    except:
        info['mem_total'] = 0
        info['mem_avail'] = 0
    
    # 磁盘
    try:
        out = subprocess.run(
            ['df', '-BG', '/'], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.split('\n'):
            if line.startswith('/'):
                parts = line.split()
                if len(parts) >= 4:
                    info['disk_total'] = parts[1].replace('G', '')
                    info['disk_used'] = parts[2].replace('G', '')
                    info['disk_free'] = parts[3].replace('G', '')
                    break
    except:
        info['disk_total'] = '0'
        info['disk_free'] = '0'
    
    # OS 信息
    try:
        out = subprocess.run(
            ['cat', '/etc/os-release'], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.split('\n'):
            if line.startswith('PRETTY_NAME='):
                info['os'] = line.split('=')[-1].strip().strip('"')
                break
    except:
        info['os'] = 'Linux'
    
    return info


def get_default_cache_dir():
    """获取默认缓存目录"""
    return Path('/var/cache/nas-photo')


# ═══════════════════════════════════════════
# 照片路径
# ═══════════════════════════════════════════

def get_default_photo_roots():
    """获取Linux设备默认照片路径"""
    # 供安装向导用
    return []


def scan_photo_dirs():
    """扫描本地照片目录"""
    found = []
    # 常见路径
    common = [
        Path.home() / 'Pictures',
        Path.home() / '图片',
        Path.home() / '照片',
        Path('/media'),
        Path('/mnt'),
        Path('/nas'),
        Path('/share'),
        Path('/data'),
    ]
    for p in common:
        if p.exists():
            found.append(str(p))
    
    # 扫描可移动媒体
    media = Path('/media')
    if media.exists():
        for user_dir in media.iterdir():
            if user_dir.is_dir() and not user_dir.name.startswith('.'):
                found.append(str(user_dir))
    
    # 扫描/mnt
    mnt = Path('/mnt')
    if mnt.exists():
        for d in mnt.iterdir():
            if d.is_dir() and not d.name.startswith('.'):
                found.append(str(d))
    
    return found


# ═══════════════════════════════════════════
# 服务管理
# ═══════════════════════════════════════════

def get_python_exe(venv_dir):
    """获取venv中的Python路径"""
    return str(Path(venv_dir) / 'bin' / 'python3')


def is_admin():
    """检查是否root"""
    return os.geteuid() == 0 if hasattr(os, 'geteuid') else False


def start_service(venv_dir, app_py, log_file=None):
    """后台启动Flask服务"""
    python_exe = get_python_exe(venv_dir)
    app_dir = str(Path(app_py).parent)
    if not log_file:
        log_file = str(Path(app_dir) / 'server.log')
    
    try:
        proc = subprocess.Popen(
            [python_exe, app_py],
            cwd=app_dir,
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        )
        return proc.pid > 0
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


def set_auto_start(venv_dir, app_py):
    """设置systemd开机自启"""
    python_exe = get_python_exe(venv_dir)
    app_dir = str(Path(app_py).parent)
    log_file = str(Path(app_dir) / 'server.log')
    
    service_content = f"""[Unit]
Description=NAS Photo Album
After=network.target

[Service]
Type=simple
User={os.environ.get('USER', 'root')}
WorkingDirectory={app_dir}
ExecStart={python_exe} {app_py}
Restart=on-failure
Environment=PYTHONIOENCODING=utf-8
StandardOutput=append:{log_file}
StandardError=append:{log_file}

[Install]
WantedBy=multi-user.target
"""
    service_path = Path('/etc/systemd/system/nas-photo.service')
    try:
        service_path.write_text(service_content)
        subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, timeout=10)
        subprocess.run(['systemctl', 'enable', 'nas-photo'], capture_output=True, timeout=10)
        return True
    except:
        return False


def unset_auto_start():
    """取消systemd开机自启"""
    try:
        subprocess.run(['systemctl', 'disable', 'nas-photo'], capture_output=True, timeout=10)
        Path('/etc/systemd/system/nas-photo.service').unlink(missing_ok=True)
        subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, timeout=10)
        return True
    except:
        return False


def get_service_status():
    """获取服务状态"""
    status = {'running': False, 'pid': 0, 'port': 5000, 'url': ''}
    try:
        out = subprocess.run(
            ['ss', '-tlnp'], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.split('\n'):
            if ':5000' in line:
                status['running'] = True
                if 'pid=' in line:
                    pid_str = line.split('pid=')[-1].split(',')[0]
                    status['pid'] = int(pid_str) if pid_str.isdigit() else 0
                break
    except:
        pass
    return status
