"""
NAS相册 — 平台适配层统一接口

每个平台模块必须暴露以下接口：
    detect_os()           -> str          # 'linux' / 'windows' / 'macos'
    get_photo_roots()     -> [str]        # 默认照片扫描路径
    get_cache_dir()       -> Path         # 缓存目录
    get_python_exe(venv)  -> str          # venv中的python路径
    get_platform_info()   -> dict         # 系统信息（CPU/内存/磁盘）
    is_admin()            -> bool         # 是否管理员权限
    start_service(venv, app_py) -> bool   # 后台启动Flask
    stop_service()        -> bool         # 停止Flask
    set_auto_start(venv, app_py) -> bool  # 设置开机自启
    unset_auto_start()    -> bool         # 取消开机自启
    get_service_status()  -> dict         # 服务状态

路径规范化：
    norm_path(path)       -> str          # 统一路径格式
    join_path(*parts)     -> str          # 平台正确拼接路径
"""

import sys
import os
from pathlib import Path

# 平台检测
def detect_os():
    """检测当前运行的操作系统"""
    if sys.platform == 'win32':
        return 'windows'
    elif sys.platform == 'darwin':
        return 'macos'
    else:
        return 'linux'

def get_platform():
    """获取当前平台适配模块"""
    os_type = detect_os()
    if os_type == 'windows':
        from . import windows as plat
    elif os_type == 'macos':
        from . import macos as plat
    else:
        from . import linux as plat
    return plat

# 路径工具
def norm_path(path):
    """将路径统一为平台格式"""
    plat = get_platform()
    return plat.norm_path(path)

def join_path(*parts):
    """平台正确的路径拼接"""
    plat = get_platform()
    return plat.join_path(*parts)

def path_exists(path):
    """检查路径是否存在（平台兼容）"""
    return Path(path).exists()

# 便捷函数
def get_config_dir():
    """获取配置目录"""
    return Path.home() / '.nas-photo'

def ensure_config_dir():
    """确保配置目录存在"""
    d = get_config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d
