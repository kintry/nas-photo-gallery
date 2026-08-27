"""
NAS相册 — Windows平台适配模块
适用系统: Windows 10/11 + OpenSSH 或 本地Python
"""

import os
import sys
import platform
import subprocess
import re
from pathlib import Path


# ═══════════════════════════════════════════
# 路径工具
# ═══════════════════════════════════════════

def norm_path(path):
    """Windows路径标准化 — 统一为反斜杠"""
    return str(Path(path))

def join_path(*parts):
    """Windows路径拼接"""
    return '\\'.join(parts)


# ═══════════════════════════════════════════
# 系统检测
# ═══════════════════════════════════════════

def _run_ps(script, timeout=10):
    """运行PowerShell命令"""
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except:
        return ''


def get_platform_info():
    """获取系统信息"""
    info = {
        'hostname': platform.node(),
        'os': f'Windows {platform.version()}',
        'arch': platform.machine(),
    }
    
    # CPU
    try:
        out = _run_ps(
            '(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum'
        )
        info['cores'] = int(out) if out.isdigit() else 0
    except:
        info['cores'] = 0
    
    try:
        info['cpu_model'] = _run_ps(
            '(Get-CimInstance Win32_Processor).Name'
        )
    except:
        info['cpu_model'] = 'unknown'
    
    # 内存 (bytes)
    try:
        out = _run_ps(
            '(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory'
        )
        info['mem_total'] = int(float(out)) if out else 0
    except:
        info['mem_total'] = 0
    
    try:
        out = _run_ps(
            '(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1024'
        )
        info['mem_avail'] = int(float(out)) if out else 0
    except:
        info['mem_avail'] = 0
    
    # 磁盘
    try:
        out = _run_ps(
            'Get-CimInstance Win32_LogicalDisk -Filter "DeviceID=\'C:\'" | '
            'Select-Object Size, FreeSpace | ConvertTo-Json'
        )
        import json
        d = json.loads(out) if out else {}
        info['disk_total'] = str(d.get('Size', 0))
        info['disk_free'] = str(d.get('FreeSpace', 0))
    except:
        info['disk_total'] = '0'
        info['disk_free'] = '0'
    
    return info


def get_default_cache_dir():
    """Windows默认缓存目录"""
    appdata = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    return appdata / 'nas-photo' / 'cache'


# ═══════════════════════════════════════════
# 照片路径
# ═══════════════════════════════════════════

def get_default_photo_roots():
    """获取Windows默认照片路径"""
    return [
        str(Path.home() / 'Pictures'),
        str(Path.home() / 'OneDrive' / 'Pictures'),
        str(Path(os.environ.get('PUBLIC', 'C:\\Users\\Public')) / 'Pictures'),
    ]


def scan_photo_dirs():
    """扫描Windows本地照片目录"""
    found = []
    keywords = ['Pictures', 'Photos', 'Photo', 'Camera', 'DCIM', 'Images',
                '照片', '相册', '图片', '相机', '影像', 'iCloud', 'OneDrive']
    
    for drive_letter in 'CDEFGH':
        drive = f'{drive_letter}:\\'
        if not Path(drive).exists():
            continue
        
        # 用户目录
        users = Path(drive) / 'Users'
        if users.exists():
            for user_dir in users.iterdir():
                if not user_dir.is_dir() or user_dir.name.startswith('.'):
                    continue
                if user_dir.name in ('Public', 'Default', 'Default User', 'All Users'):
                    continue
                for kw in keywords:
                    for p in user_dir.rglob(f'*{kw}*'):
                        if p.is_dir():
                            found.append(str(p))
                        if len(found) > 50:
                            return found  # 够了
        
        # 直接扫描drive根目录关键字
        for kw in keywords:
            for p in Path(drive).glob(f'*{kw}*'):
                if p.is_dir():
                    found.append(str(p))
    
    return found


# ═══════════════════════════════════════════
# 服务管理
# ═══════════════════════════════════════════

def get_python_exe(venv_dir):
    """获取venv中的Python路径（Windows）"""
    return str(Path(venv_dir) / 'Scripts' / 'python.exe')


def is_admin():
    """检查是否管理员权限"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


def start_service(venv_dir, app_py, log_file=None):
    """后台启动Flask服务（Windows用WMIC保持后台）"""
    python_exe = get_python_exe(venv_dir)
    if not log_file:
        app_dir = str(Path(app_py).parent)
        log_file = str(Path(app_dir) / 'server.log')
    
    # 使用wmic确保进程独立于当前会话
    cmd = f'wmic process call create "{python_exe} {app_py}"'
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=True)
        return 'ReturnValue = 0' in r.stdout
    except:
        return False


def stop_service():
    """停止Flask服务"""
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', 'python.exe'],
            capture_output=True, timeout=5
        )
        subprocess.run(
            ['taskkill', '/F', '/IM', 'pythonw.exe'],
            capture_output=True, timeout=5
        )
        return True
    except:
        return False


def set_auto_start(venv_dir, app_py):
    """设置Windows开机自启（任务计划程序）"""
    python_exe = get_python_exe(venv_dir)
    
    # 创建启动脚本
    app_dir = str(Path(app_py).parent)
    ps1_path = str(Path(app_dir) / 'start-nas-photo.ps1')
    ps1_content = f'''Start-Process -FilePath "{python_exe}" -ArgumentList "{app_py}" -WindowStyle Hidden
'''
    try:
        Path(ps1_path).write_text(ps1_content)
        
        # 用schtasks创建开机任务
        task_name = 'NASPhotoAlbum'
        cmd = (
            f'schtasks /Create /SC ONLOGON /TN "{task_name}" /TR '
            f'"powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File \\"{ps1_path}\\"" '
            f'/RL HIGHEST /F'
        )
        subprocess.run(cmd, capture_output=True, timeout=10, shell=True)
        return True
    except:
        return False


def unset_auto_start():
    """取消Windows开机自启"""
    try:
        subprocess.run(
            ['schtasks', '/Delete', '/TN', 'NASPhotoAlbum', '/F'],
            capture_output=True, timeout=10
        )
        return True
    except:
        return False


def get_service_status():
    """获取服务状态"""
    status = {'running': False, 'pid': 0, 'port': 5000, 'url': ''}
    try:
        out = _run_ps(
            'netstat -ano | Select-String ":5000 "'  # 注意空格避免匹配到15000等
        )
        for line in out.split('\n'):
            if ':5000' in line and 'LISTENING' in line:
                status['running'] = True
                parts = line.strip().split()
                if parts:
                    pid_str = parts[-1]
                    status['pid'] = int(pid_str) if pid_str.isdigit() else 0
                break
    except:
        pass
    return status
