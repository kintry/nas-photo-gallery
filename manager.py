#!/usr/bin/env python3



"""



NAS相册 管理面板 v1.0



功能：设备发现 → 预检 → 安装 → 设备管理



"""



import sys, os, json, threading, subprocess, time, re, socket, hashlib



import urllib.request, urllib.parse



from pathlib import Path



from datetime import datetime







# ── 路径 ──



SCRIPT_DIR = Path(__file__).parent



DEVICES_PATH = SCRIPT_DIR / 'devices.json'



HOST = '0.0.0.0'



PORT = 5001







# ── 设备存储 ──



def _load_devices():



    if DEVICES_PATH.exists():



        return json.loads(DEVICES_PATH.read_text())



    return {'devices': [], 'lastUpdated': ''}







def _save_devices(data):



    data['lastUpdated'] = datetime.now().isoformat()



    DEVICES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))







def _get_device(host):



    data = _load_devices()



    for d in data['devices']:



        if d.get('host') == host:



            return d, data



    return None, data







def _device_photo_roots_request(host, action='list', payload=None):



    """代理：调用目标设备 5000 端口相册服务的 /api/photo_roots* 端点。



    action: list|scan|add|remove|refresh



    payload: {'paths':[...]} 用于 add, {'path':...} 用于 remove



    返回 dict（设备端 JSON），失败返回 {'error': ...}



    """



    base = f'http://{host}:5000/api/photo_roots'



    url = base if action == 'list' else f'{base}/{action}'



    try:



        data = None



        if action in ('add', 'remove', 'enable', 'disable') and payload:



            data = json.dumps(payload).encode('utf-8')



        method = 'POST' if action in ('add', 'remove', 'enable', 'disable') else 'GET'

        req = urllib.request.Request(url, data=data, method=method)



        req.add_header('Content-Type', 'application/json')



        # refresh/scan 触发全量重扫(可能>60s)，用更长超时；其他 25s

        _timeout = 120 if action in ('refresh', 'scan') else 25



        with urllib.request.urlopen(req, timeout=_timeout) as resp:



            return json.loads(resp.read().decode('utf-8'))



    except urllib.error.HTTPError as e:



        try:



            return json.loads(e.read().decode('utf-8')) or {'error': f'HTTP {e.code}'}



        except Exception:



            return {'error': f'HTTP {e.code}'}



    except Exception as e:



        return {'error': f"{type(e).__name__}: {e}"}











# ── ARP 扫描 → 发现局域网设备 ──



def scan_lan(timeout=15):



    """通过 ARP 扫描发现局域网活跃设备"""



    devices = []



    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)



    try:



        s.connect(('8.8.8.8', 80))



        local_ip = s.getsockname()[0]



    except:



        local_ip = '192.168.2.100'



    finally:



        s.close()







    net_prefix = '.'.join(local_ip.split('.')[:3])



    alive = []







    def ping(ip):



        try:



            r = subprocess.run(['ping', '-c', '1', '-W', '1', ip],



                             capture_output=True, timeout=2)



            if r.returncode == 0:



                alive.append(ip)



        except:



            pass







    threads = []



    for i in range(1, 255):



        t = threading.Thread(target=ping, args=(f'{net_prefix}.{i}',))



        t.start()



        threads.append(t)



        if len(threads) >= 50:



            for t in threads: t.join()



            threads = []



    for t in threads: t.join()







    for ip in sorted(alive, key=lambda x: int(x.split('.')[-1])):



        try:



            hostname = socket.gethostbyaddr(ip)[0]



        except:



            hostname = 'unknown'



        devices.append({'ip': ip, 'hostname': hostname})







    return devices, net_prefix



# ── SSH 辅助 ──



def _ssh_cmd(ssh, cmd, timeout=10):



    """执行SSH命令，返回 (stdout, stderr, exit_code)"""



    try:



        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)



        out = stdout.read().decode('utf-8', errors='replace').strip()



        err = stderr.read().decode('utf-8', errors='replace').strip()



        rc = stdout.channel.recv_exit_status()



        return out, err, rc



    except Exception as e:



        return '', str(e), -1











def detect_os(ssh):



    """检测远程设备操作系统类型：linux / windows / mac / unknown"""



    out, _, _ = _ssh_cmd(ssh, 'uname -s', timeout=5)



    if 'Linux' in out:



        return 'linux'



    elif 'Darwin' in out:



        return 'mac'



    # Windows: try ver command



    out2, _, _ = _ssh_cmd(ssh, 'ver', timeout=5)



    if 'Windows' in out2:



        return 'windows'



    # Windows: try cmd /c ver



    out3, _, _ = _ssh_cmd(ssh, 'cmd /c ver', timeout=5)



    if 'Windows' in out3:



        return 'windows'



    return 'unknown'











# ── SSH 预检（跨平台）──



def precheck_device(host, username, password, port=22):



    """跨平台检查设备CPU/内存/磁盘/OS — 支持 Linux / Windows / Mac"""



    import paramiko



    try:



        ssh = paramiko.SSHClient()



        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())



        ssh.connect(host, port=port, username=username, password=password,



                    timeout=10, allow_agent=False, look_for_keys=False)







        result = {'host': host, 'port': port, 'username': username, 'reachable': True}







        # 1) 检测 OS



        os_type = detect_os(ssh)



        result['os_type'] = os_type







        # 获取主机名



        out_host, _, _ = _ssh_cmd(ssh, 'hostname', timeout=5)



        result['hostname'] = out_host.strip() or host







        if os_type == 'windows':



            # ── Windows 预检 ──



            out, _, _ = _ssh_cmd(ssh, 'powershell -Command "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"', timeout=10)



            result['cpu_cores'] = int(out.strip() or '1')







            out, _, _ = _ssh_cmd(ssh, 'powershell -Command "(Get-CimInstance Win32_Processor).Name"', timeout=10)



            result['cpu_model'] = (out.strip() or 'unknown')[:60]







            out, _, _ = _ssh_cmd(ssh, 'powershell -Command "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB, 1)"', timeout=10)



            result['ram_gb'] = float(out.strip() or '0')







            out, _, _ = _ssh_cmd(ssh, 'powershell -Command "Get-PSDrive -PSProvider FileSystem | Select-Object Root,Free | ConvertTo-Json"', timeout=10)



            result['disk_avail_gb'] = 0



            result['disk_details'] = []



            try:



                import json



                disks = json.loads(out) if out.startswith('[') else [json.loads(out)]



                for d in disks:



                    if isinstance(d, dict) and 'Free' in d and d['Free']:



                        gb = round(d['Free'] / 1073741824, 1)



                        mount = d.get('Root', '?')



                        result['disk_details'].append({'mount': mount, 'avail_gb': gb})



                        result['disk_avail_gb'] = max(result['disk_avail_gb'], gb)



            except:



                pass







            out, _, _ = _ssh_cmd(ssh, 'powershell -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; (Get-CimInstance Win32_OperatingSystem).Caption"', timeout=10)



            result['os_info'] = (out.strip() or 'Windows')[:100]







            out, _, _ = _ssh_cmd(ssh, 'where python 2>nul && python --version 2>&1 || echo no_python', timeout=5)



            py_out = out.strip()



            result['has_python'] = py_out if 'no_python' not in py_out else False







            out, _, _ = _ssh_cmd(ssh, 'where git 2>nul || echo no_git', timeout=5)



            result['has_git'] = out.strip()







            out, _, _ = _ssh_cmd(ssh, 'if exist D:\\nas-photo\\app\\app.py (echo yes) else (echo no)', timeout=5)



            result['installed'] = 'yes' in out







        elif os_type == 'mac':



            out, _, _ = _ssh_cmd(ssh, 'sysctl -n hw.ncpu', timeout=5)



            result['cpu_cores'] = int(out.strip() or '1')







            out, _, _ = _ssh_cmd(ssh, 'sysctl -n machdep.cpu.brand_string', timeout=5)



            result['cpu_model'] = (out.strip() or 'unknown')[:60]







            out, _, _ = _ssh_cmd(ssh, 'echo $(( $(sysctl -n hw.memsize) / 1073741824 ))', timeout=5)



            result['ram_gb'] = float(out.strip() or '0')







            out, _, _ = _ssh_cmd(ssh, 'df -BG / 2>/dev/null | tail -1 | awk "{print $4}"', timeout=5)



            disk_str = out.strip().replace('G', '')



            result['disk_avail_gb'] = float(disk_str) if disk_str else 0



            result['disk_details'] = []







            out, _, _ = _ssh_cmd(ssh, 'sw_vers -productName 2>/dev/null && sw_vers -productVersion 2>/dev/null || uname -a', timeout=5)



            result['os_info'] = (out.strip() or 'macOS')[:100]







            out, _, _ = _ssh_cmd(ssh, 'which python3 2>/dev/null && python3 --version 2>&1 || echo no_python3', timeout=5)



            py_out = out.strip()



            result['has_python'] = py_out if 'no_python3' not in py_out else False







            out, _, _ = _ssh_cmd(ssh, 'which git 2>/dev/null || echo no_git', timeout=5)



            result['has_git'] = out.strip()







            out, _, _ = _ssh_cmd(ssh, 'ls /opt/nas-photo/app/app.py 2>/dev/null || ls ~/nas-photo/app/app.py 2>/dev/null || echo no', timeout=5)



            result['installed'] = 'no' not in out







        else:



            # ── Linux 预检（原逻辑）──



            out, _, _ = _ssh_cmd(ssh, 'nproc 2>/dev/null || echo 1', timeout=5)



            result['cpu_cores'] = int(out.strip() or '1')







            out, _, _ = _ssh_cmd(ssh, "cat /proc/cpuinfo | grep 'model name' | head -1 | cut -d: -f2", timeout=5)



            result['cpu_model'] = (out.strip() or 'unknown')[:60]







            out, _, _ = _ssh_cmd(ssh, "free -m | awk '/Mem:/{print $2/1024}' 2>/dev/null || free -g | awk '/Mem:/{print $2}' 2>/dev/null", timeout=5)



            result['ram_gb'] = round(float(out.strip()), 1) if out.strip() else 0







            out, _, _ = _ssh_cmd(ssh, "df -BG --output=avail,target 2>/dev/null | tail -n+2 | sort -rn | head -5", timeout=5)



            result['disk_avail_gb'] = 0



            result['disk_details'] = []



            for line in out.strip().split('\n'):



                parts = line.strip().split()



                if len(parts) >= 2:



                    try:



                        gb = float(parts[0].replace('G', ''))



                        result['disk_details'].append({'mount': ' '.join(parts[1:]), 'avail_gb': gb})



                        result['disk_avail_gb'] = max(result['disk_avail_gb'], gb)



                    except:



                        pass



            if not result['disk_details']:



                out2, _, _ = _ssh_cmd(ssh, "df -BG / | tail -1 | awk '{print $4}'", timeout=5)



                disk_str = out2.strip().replace('G', '')



                result['disk_avail_gb'] = float(disk_str) if disk_str else 0







            out, _, _ = _ssh_cmd(ssh, "uname -m 2>/dev/null && cat /etc/os-release 2>/dev/null | head -1 || uname -a 2>/dev/null", timeout=5)



            result['os_info'] = (out.strip() or 'Linux')[:100]







            out, _, _ = _ssh_cmd(ssh, 'which python3 2>/dev/null && python3 --version 2>&1 || echo no_python3', timeout=5)



            py_out = out.strip()



            result['has_python'] = py_out if 'no_python3' not in py_out else False







            out, _, _ = _ssh_cmd(ssh, 'which git 2>/dev/null || echo no_git', timeout=5)



            result['has_git'] = out.strip()







            out, _, _ = _ssh_cmd(ssh, 'ls /opt/nas-photo/app/app.py 2>/dev/null || ls ~/nas-photo/app/app.py 2>/dev/null || echo no', timeout=5)



            result['installed'] = 'no' not in out







        ssh.close()







        # 统一检查硬件要求



        result['pass'] = True



        warnings = []



        if result.get('ram_gb', 0) < 0.5:



            result['pass'] = False



            warnings.append(f"内存不足: {result['ram_gb']}GB (<0.5GB)")



        if result.get('disk_avail_gb', 0) < 1:



            result['pass'] = False



            warnings.append(f"磁盘空间不足: {result['disk_avail_gb']}GB (<1GB)")



        if not result.get('has_python'):



            result['pass'] = False



            warnings.append("未安装 Python")



        result['warnings'] = warnings







        return result



    except Exception as e:



        import traceback



        return {'host': host, 'reachable': False, 'error': str(e), 'pass': False}











# ── 调度配置（夜间缩略图预生成）──



def setup_nightly_schedule(ssh, os_type, install_path, venv_python, username):



    """在目标设备上配置夜间缩略图预生成定时任务"""



    logs = []



    def log(msg):



        logs.append(msg)



        print(f"  {msg}", flush=True)







    log("配置夜间缩略图预生成定时任务...")







    if os_type == 'windows':



        # Windows: schtasks



        task_name = 'nas_photo_nightly_precache'



        nightly_script = f'{install_path}\\app\\nightly_precache.py'



        log_cmd = f'{install_path}\\app\\nightly_precache_cron.log'



        cmd = f'{venv_python} {nightly_script} >> {log_cmd} 2>&1'



        # Delete existing if any, then create



        _ssh_cmd(ssh, f'schtasks /delete /tn {task_name} /f 2>nul', timeout=5)



        _, err, rc = _ssh_cmd(ssh,



            f'schtasks /create /tn {task_name} /tr "{cmd}" /sc daily /st 03:00 /ru {username} /f',



            timeout=10)



        if rc == 0:



            log(f"   ✅ Windows 计划任务 {task_name} 已创建 (每天03:00)")



        else:



            log(f"   ⚠️ 创建计划任务失败: {err[:100]}")



    else:



        # Linux / Mac: crontab



        nightly_script = f'{install_path}/app/nightly_precache.py'



        log_path = f'{install_path}/app/nightly_precache_cron.log'



        cron_line = f'0 3 * * * cd {install_path}/app && {venv_python} {nightly_script} >> {log_path} 2>&1'



        # Check if already exists



        out, _, _ = _ssh_cmd(ssh, 'crontab -l 2>/dev/null', timeout=5)



        if 'nightly_precache' in out:



            log("   ⏭ nightly_precache 已在 crontab 中，跳过")



        else:



            new_cron = out + '\n' + cron_line + '\n' if out.strip() else cron_line + '\n'



            _, _, rc = _ssh_cmd(ssh, f'echo "{new_cron}" | crontab -', timeout=5)



            if rc == 0:



                log(f"   ✅ Crontab 已添加 (每天03:00)")



            else:



                log(f"   ⚠️ 添加 crontab 失败")







    return logs











# ── 安装程序（跨平台：git clone + venv + 调度）──



def install_gallery(host, username, password, port=22, install_path=None):



    """在目标设备上安装NAS相册 — 自动检测OS，支持 Linux / Windows / Mac"""



    import paramiko







    try:



        ssh = paramiko.SSHClient()



        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())



        ssh.connect(host, port=port, username=username, password=password,



                    timeout=15, allow_agent=False, look_for_keys=False)







        logs = []



        def log(msg):



            logs.append(msg)



            print(f"  {msg}", flush=True)







        # 检测 OS



        os_type = detect_os(ssh)



        log(f"检测到系统: {os_type}")







        # 智能默认路径



        if not install_path:



            if os_type == 'windows':



                install_path = 'C:\\nas-photo'



            else:



                install_path = '/opt/nas-photo'



        log(f"安装路径: {install_path}")







        if os_type == 'windows':



            # ── Windows 安装 ──



            py_cmd = 'python'



            venv_python = f'{install_path}\\app\\venv\\Scripts\\python.exe'



            pip_cmd = f'{install_path}\\app\\venv\\Scripts\\pip'







            # 1. 检查 git



            log("检查 Git...")



            out, _, _ = _ssh_cmd(ssh, 'where git 2>nul || echo no_git', timeout=5)



            if 'no_git' in out:



                log("   ⚠️ 未安装 Git，请手动安装 https://git-scm.com/")



                ssh.close()



                return {'success': False, 'error': 'Windows 需要先安装 Git', 'logs': logs}







            # 2. git clone



            log("克隆代码...")



            _ssh_cmd(ssh, f'if exist {install_path}\\.git (cd /d {install_path} && git pull) else (mkdir {install_path} && git clone https://github.com/kintry/nas-photo-gallery.git {install_path})', timeout=120)







            # 3. 创建虚拟环境



            log("创建虚拟环境...")



            _ssh_cmd(ssh, f'cd /d {install_path}\\app && {py_cmd} -m venv venv', timeout=30)







            # 4. 安装依赖



            log("安装依赖...")



            _ssh_cmd(ssh, f'{pip_cmd} install -r {install_path}\\app\\requirements.txt', timeout=180)







            # 5. 验证安装



            log("验证安装...")



            out, _, _ = _ssh_cmd(ssh, f'cd /d {install_path}\\app && {venv_python} -c "from app import create_app; print(\'OK\')"', timeout=15)



            log(f"   加载: {'✅' if 'OK' in out else '❌ ' + out[:50]}")







            # 6. 配置 nightly_precache 调度



            schedule_logs = setup_nightly_schedule(ssh, os_type, install_path, venv_python, username)



            logs.extend(schedule_logs)







        elif os_type == 'mac':



            # ── Mac 安装 ──



            py_cmd = 'python3'



            venv_python = f'{install_path}/app/venv/bin/python3'



            pip_cmd = f'{install_path}/app/venv/bin/pip'







            # 1. 检查 git



            log("检查 Git...")



            out, _, _ = _ssh_cmd(ssh, 'which git 2>/dev/null || echo no_git', timeout=5)



            if 'no_git' in out:



                log("   请安装 Git: brew install git")



                log("   或从 https://git-scm.com/ 下载")







            # 2. git clone



            log("克隆代码...")



            _ssh_cmd(ssh, f'if [ -d {install_path}/.git ]; then cd {install_path} && git pull; else mkdir -p {install_path} && git clone https://github.com/kintry/nas-photo-gallery.git {install_path}; fi', timeout=120)







            # 3. 创建虚拟环境



            log("创建虚拟环境...")



            _ssh_cmd(ssh, f'cd {install_path}/app && {py_cmd} -m venv venv 2>&1', timeout=30)







            # 4. 安装依赖



            log("安装依赖...")



            _ssh_cmd(ssh, f'{pip_cmd} install -r {install_path}/app/requirements.txt', timeout=180)







            # 5. 验证



            log("验证安装...")



            out, _, _ = _ssh_cmd(ssh, f'cd {install_path}/app && {venv_python} -c "from app import create_app; print(\'OK\')"', timeout=15)



            log(f"   加载: {'✅' if 'OK' in out else '❌ ' + out[:50]}")







            # 6. 调度



            schedule_logs = setup_nightly_schedule(ssh, os_type, install_path, venv_python, username)



            logs.extend(schedule_logs)







            # 7. 创建启动脚本



            log("创建启动脚本...")



            _ssh_cmd(ssh, f'echo "#!/bin/bash\\ncd {install_path}/app\\n{venv_python} app.py" > {install_path}/start.sh && chmod +x {install_path}/start.sh', timeout=5)







        else:



            # ── Linux 安装（原逻辑增强版）──



            py_cmd = 'python3'



            venv_python = f'{install_path}/app/venv/bin/python3'



            pip_cmd = f'{install_path}/app/venv/bin/pip'







            # 1. 检查/安装 git



            log("检查 Git...")



            out, _, _ = _ssh_cmd(ssh, 'which git 2>/dev/null || apt-get install -y git 2>&1 || yum install -y git 2>&1', timeout=30)



            log(f"   Git: {'OK' if 'no' not in out else '已安装'}")







            # 2. git clone



            log("克隆代码...")



            _ssh_cmd(ssh, f'if [ -d {install_path}/.git ]; then cd {install_path} && git pull 2>&1; else mkdir -p {install_path} && git clone https://github.com/kintry/nas-photo-gallery.git {install_path} 2>&1; fi', timeout=120)







            # 3. 虚拟环境



            log("创建虚拟环境...")



            _ssh_cmd(ssh, f'cd {install_path}/app && {py_cmd} -m venv venv 2>&1', timeout=30)







            # 4. 安装依赖



            log("安装依赖...")



            _ssh_cmd(ssh, f'{pip_cmd} install -r {install_path}/app/requirements.txt', timeout=180)







            # 5. 验证



            log("验证安装...")



            out, _, _ = _ssh_cmd(ssh, f'cd {install_path}/app && {venv_python} -c "from app import create_app; print(\'OK\')"', timeout=15)



            log(f"   加载: {'✅' if 'OK' in out else '❌ ' + out[:50]}")







            # 6. 调度



            schedule_logs = setup_nightly_schedule(ssh, os_type, install_path, venv_python, username)



            logs.extend(schedule_logs)







            # 7. 创建启动脚本



            log("创建启动脚本...")



            _ssh_cmd(ssh, f'echo "#!/bin/bash\\ncd {install_path}/app\\n{venv_python} app.py" > {install_path}/start.sh && chmod +x {install_path}/start.sh', timeout=5)







        ssh.close()



        log("✅ 安装完成！")



        log(f"   路径: {install_path}")



        if os_type == 'windows':



            log(f"   启动: {install_path}\\app\\venv\\Scripts\\python.exe {install_path}\\app\\app.py")



        else:



            log(f"   启动: {install_path}/start.sh")







        # 获取主机名



        hostname = host



        try:



            ssh2 = paramiko.SSHClient()



            ssh2.set_missing_host_key_policy(paramiko.AutoAddPolicy())



            ssh2.connect(host, port=port, username=username, password=password,



                        timeout=5, allow_agent=False, look_for_keys=False)



            o, _, _ = _ssh_cmd(ssh2, 'hostname', timeout=5)



            if o.strip():



                hostname = o.strip()



            ssh2.close()



        except:



            pass







        # ── 配置照片目录（初始化/重装）─────────────────────────────
        # 重装：若 config.py 已存在（卸载时保留）→ 直接复用照片路径
        # 全新：生成空 config.py，安装完成后在前端"管理相册目录"一次性全量选择
        log("配置照片目录...")
        try:
            config_file = f'{install_path}/app/config.py' if os_type != 'windows' else f'{install_path}\\app\\config.py'
            ex_chk = f'if exist "{config_file}" (echo exists) else (echo missing)' if os_type=='windows' else f'[ -f {config_file} ] && echo exists || echo missing'
            out, _, _ = _ssh_cmd(ssh, ex_chk, timeout=8)
            if 'exists' in out:
                # 读取已有 config 的照片目录数
                nread = ''
                if os_type=='windows':
                    nout,_,_ = _ssh_cmd(ssh, f'findstr /c:"r\'" {config_file} 2>nul | find /c "\'"', timeout=8)
                    nread = nout.strip()
                else:
                    nout,_,_ = _ssh_cmd(ssh, f'grep -c "r\'" {config_file} 2>/dev/null', timeout=8)
                    nread = nout.strip()
                log(f"   检测到已有 config.py（照片路径），直接复用 ({nread} 个目录)")
            else:
                # 全新：写空 config.py，防止启动空目录报错；提示进管理面板选择
                empty = "# -*- coding: utf-8 -*\nPHOTO_ROOTS = []\n"
                if os_type=='windows':
                    _ssh_cmd(ssh, f'echo {empty} > {config_file}', timeout=8)
                else:
                    _ssh_cmd(ssh, f'printf "%s\n" "# -*- coding: utf-8 -*-" "PHOTO_ROOTS = []" > {config_file}', timeout=8)
                log("   全新安装：已生成空 config.py")
                log("   → 安装完成后，请在设备管理中打开『📁 管理相册目录』，扫描并一次性全量选择照片目录")
        except Exception as e:
            log(f"   ⚠️ 配置照片目录失败: {str(e)[:60]}（可后续在管理面板手动添加）")

        # 自动启动相册服务




        log("启动相册服务...")



        try:



            if os_type == 'windows':



                _ssh_cmd(ssh, f'start /B {venv_python} {install_path}\\app\\app.py', timeout=5)



            else:



                _ssh_cmd(ssh, f'cd {install_path}/app && nohup {venv_python} app.py > app.log 2>&1 &', timeout=5)



            log(f"   ✅ 已启动: http://{host}:5000")



        except Exception as e:



            log(f"   ⚠️ 启动失败: {str(e)[:60]}")







        # 保存到设备列表



        gallery_url = f'http://{host}:5000'



        device_info = {



            'host': host, 'port': port, 'username': username, 'os_type': os_type,



            'hostname': hostname,



            'install_path': install_path,



            'installed_at': __import__('datetime').datetime.now().isoformat(),



            'name': f'{hostname} - 相册 ({os_type})',



            'gallery_url': gallery_url,



            'status': 'installed',



        }



        data = _load_devices()



        data['devices'] = [d for d in data['devices'] if d.get('host') != host]



        data['devices'].append(device_info)



        _save_devices(data)







        return {'success': True, 'logs': logs, 'device': device_info}



    except Exception as e:



        import traceback



        return {'success': False, 'error': str(e), 'traceback': traceback.format_exc(), 'logs': logs if 'logs' in locals() else []}







MANAGER_HTML = '''<!DOCTYPE html>



<html lang="zh-CN">



<head>



<meta charset="UTF-8">



<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">



<title>NAS相册 · 管理面板</title>



<style>



*{margin:0;padding:0;box-sizing:border-box}



body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0f0f23;color:#e0e0e0;min-height:100vh}



.header{background:#1a1a3e;padding:14px 20px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #2c3e50}



.header h1{font-size:18px;color:#3498db}



.header .sub{font-size:12px;color:#7f8c8d;margin-top:2px}



.container{max-width:960px;margin:0 auto;padding:20px}



.card{background:#1a1a3e;border-radius:12px;padding:20px;margin-bottom:16px;border:1px solid #2c3e50}



.card h2{font-size:15px;margin-bottom:12px;color:#3498db}



.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}



.device-card{background:#16213e;border-radius:10px;padding:16px;border:1px solid #2c3e50;cursor:pointer;transition:all .15s}



.device-card:hover{border-color:#3498db;transform:translateY(-1px)}



.device-card .ip{font-size:14px;font-weight:600}



.device-card .name{font-size:12px;color:#7f8c8d;margin-top:4px}



.device-card .status{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;margin-top:8px}



.status-ok{background:#27ae6033;color:#2ecc71;border:1px solid #27ae60}



.status-fail{background:#e74c3c33;color:#e74c3c;border:1px solid #e74c3c}



.status-wait{background:#f39c1233;color:#f39c12;border:1px solid #f39c12}



.btn{display:inline-block;padding:8px 20px;border-radius:8px;border:none;cursor:pointer;font-size:13px;transition:all .15s}



.btn-primary{background:#3498db;color:#fff}



.btn-primary:hover{background:#2980b9}



.btn-success{background:#27ae60;color:#fff}



.btn-success:hover{background:#219a52}



.btn-danger{background:#e74c3c;color:#fff}



.btn-sm{padding:4px 12px;font-size:11px}



input,select{background:#0f0f23;border:1px solid #2c3e50;border-radius:6px;padding:8px 12px;color:#e0e0e0;font-size:13px;width:100%;margin-bottom:8px}



input:focus{outline:none;border-color:#3498db}



.form-row{display:flex;gap:8px;margin-bottom:4px}



.form-row input{flex:1}



.tabs{display:flex;gap:4px;margin-bottom:16px}



.tab{padding:8px 20px;border-radius:8px 8px 0 0;cursor:pointer;font-size:13px;background:#16213e;border:1px solid #2c3e50;border-bottom:none;color:#7f8c8d}



.tab.active{background:#1a1a3e;color:#3498db;font-weight:600}



.panel{display:none}



.panel.active{display:block}



.log-box{background:#0a0a15;border-radius:8px;padding:12px;font-family:monospace;font-size:12px;max-height:300px;overflow-y:auto;line-height:1.6;white-space:pre-wrap;word-break:break-all;margin-top:12px}



.log-box .info{color:#2ecc71}



.log-box .warn{color:#f39c12}



.log-box .err{color:#e74c3c}



#resultBox{padding:12px;border-radius:8px;margin-top:12px}



#resultBox.success{background:#27ae6033;border:1px solid #27ae60}



#resultBox.error{background:#e74c3c33;border:1px solid #e74c3c}



.loading-dots::after{content:'';animation:dots 1.5s infinite}



@keyframes dots{0%,20%{content:' .'}40%{content:' ..'}60%,100%{content:' ...'}}



.installed-badge{color:#2ecc71;font-size:11px;margin-left:6px}



</style>



</head>



<body>



<div class="header">



  <div><h1>📡 NAS相册 · 管理面板</h1><div class="sub">安装向导 · 设备管理</div></div>



  <div><a href="https://github.com/kintry/nas-photo-gallery" target="_blank" style="color:#7f8c8d;font-size:12px;text-decoration:none">GitHub ↗</a></div>



</div>



<div class="container">







<div class="tabs">



  <div class="tab active" onclick="switchTab('devices',this)">📋 已安装设备</div>



  <div class="tab" onclick="switchTab('wizard',this)">🔧 安装向导</div>



  <div class="tab" onclick="switchTab('settings',this)">⚙ 设置</div>



</div>







<!-- 已安装设备 -->



<div id="panelDevices" class="panel active">



  <div class="card"><h2>📋 已安装设备</h2><div id="deviceList"><div class="loading-dots" style="color:#7f8c8d">加载中...</div></div></div>



</div>







<!-- 安装向导 -->



<div id="panelWizard" class="panel">



  <div class="card">



    <h2>🔍 第一步：扫描局域网设备</h2>



    <button class="btn btn-primary" onclick="scanLan()" id="scanBtn">🔍 扫描局域网</button>



    <div id="scanResult" style="margin-top:12px"></div>



  </div>



  <div class="card" id="installForm" style="display:none">



    <h2>🔧 第二步：安装配置</h2>



    <div class="form-row">



      <input type="text" id="installHost" placeholder="设备IP" readonly>



      <input type="text" id="installUser" value="root" placeholder="用户名">



    </div>



    <input type="password" id="installPass" placeholder="密码">



    <input type="text" id="installPath" value="/opt/nas-photo" placeholder="安装路径">



    <button class="btn btn-success" onclick="precheckDevice()" id="precheckBtn">🔍 预检设备</button>



    <div id="precheckResult" style="margin-top:8px"></div>



    <div id="installActions" style="display:none;margin-top:12px">



      <button class="btn btn-primary" onclick="installDevice()" id="installBtn">🚀 开始安装</button>



    </div>



    <div id="installLog" class="log-box" style="display:none"></div>



  </div>



</div>







<!-- 设置 -->



<div id="panelSettings" class="panel">



  <div class="card">



    <h2>⚙ 管理面板信息</h2>



    <div style="font-size:13px;color:#95a5a6;line-height:1.8">



      <div>端口: <code>5001</code></div>



      <div>配置: <code>~/.hermes/scripts/manager/devices.json</code></div>



      <div>仓库: <a href="https://github.com/kintry/nas-photo-gallery" target="_blank" style="color:#3498db">github.com/kintry/nas-photo-gallery</a></div>



    </div>



  </div>



</div>







</div>







<!-- 相册目录管理 模态框 -->



<div id="prModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.55);z-index:999;overflow-y:auto" onclick="if(event.target===this)closePhotoRootsModal()">



  <div style="max-width:760px;margin:30px auto;background:#1a1a3e;border-radius:14px;border:1px solid #2c3e50;padding:22px">



    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">



      <h2 style="font-size:16px;color:#3498db" id="prModalTitle">📁 管理相册目录</h2>



      <button class="btn btn-sm" onclick="closePhotoRootsModal()" style="background:#2c3e50;color:#e0e0e0">✖ 关闭</button>



    </div>



    <div id="prContent"><div class="loading-dots" style="color:#7f8c8d">加载中...</div></div>



  </div>



</div>







<script>



let scannedDevices = [];



let prHost = '';



let prDiscovered = [];

let prChecked = {};







// ══════════════════════════════════════════════



// 相册目录管理（模态框）



// ══════════════════════════════════════════════



function closePhotoRootsModal() {



  document.getElementById('prModal').style.display = 'none';



}



function openPhotoRootsModal(host) {



  prHost = host;



  document.getElementById('prModalTitle').textContent = '📁 管理相册目录 · ' + host;



  document.getElementById('prModal').style.display = 'block';



  document.getElementById('prContent').innerHTML = '<div class="loading-dots" style="color:#7f8c8d">加载中...</div>';



  loadPhotoRoots(host);



}







async function apiPR(host, action, payload) {



  const method = (action === 'add' || action === 'remove' || action === 'enable' || action === 'disable') ? 'POST' : 'GET';



  const opts = { method, headers: { 'Content-Type': 'application/json' } };



  if (method === 'POST') opts.body = JSON.stringify(payload || {});



  const r = await fetch(`/api/device/${host}/photo_roots${action === 'list' ? '' : '/' + action}`, opts);



  return r.json();



}







// 🔑 转义 HTML



function escHtml(s) { return String(s==null?'':s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }







// 加载相册目录（历史全量 + 三区展示）



async function loadPhotoRoots(host) {

  const c = document.getElementById('prContent');

  try {

    let data;

    try { data = await apiPR(host, 'albums'); }

    catch(e) { data = {error: e.message}; }

    if (data.error || !data.groups) {

      c.innerHTML = `<div style="color:#e74c3c">❌ ${data.error||'接口不可用(需新版app.py)'}</div>`;

      return;

    }

    const groups = data.groups || [];

    const totalCount = groups.reduce((s,g) => s + g.albums.length, 0);

    const enabledCount = groups.reduce((s,g) => s + g.albums.filter(a=>a.enabled).length, 0);

    window.__prCollapsed = window.__prCollapsed || {};

    const esc = escHtml;

    const groupsHtml = groups.map((g, gi) => {

      const isCollapsed = window.__prCollapsed[gi] === true;

      const checkedAll = g.albums.every(a => a.enabled);

      const someChecked = g.albums.some(a => a.enabled);

      const cards = g.albums.map((a, ai) => `

        <div style="display:flex;align-items:center;padding:6px 10px;border:1px solid ${a.enabled?'#27ae60':'#2c3e50'};border-radius:6px;margin-bottom:4px;background:#1a2541">

          <input type="checkbox" id="grp_${gi}_${ai}" class="grpbox" data-g="${gi}" data-path="${esc(a.path)}" ${a.enabled?'checked':''} onchange="updateGroupState(${gi})" style="width:auto;margin:0 8px 0 0">

          <div style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(a.path)}">${esc(a.name)} <span style="color:#7f8c8d">(${a.photo_count||0})</span></div>

        </div>`).join('');

      return `

        <div style="margin-bottom:10px;border:1px solid #2c3e50;border-radius:8px;overflow:hidden">

          <div style="display:flex;align-items:center;padding:10px 12px;background:#16213e;cursor:pointer" onclick="toggleGroupCollapse(${gi})">

            <span style="flex:1;font-size:13px;color:#e8e8e8;font-weight:600">📁 ${esc(g.root)} <span style="color:#7f8c8d;font-weight:normal">(${g.albums.length})</span></span>

            <span style="font-size:11px;color:#2ecc71;margin-right:8px">${checkedAll?'✅已全启用':(someChecked?'◐部分启用':'☆未启用')}</span>

            <span style="color:#7f8c8d">${isCollapsed?'▶':'▼'}</span>

          </div>

          <div id="grpbody_${gi}" style="padding:8px;${isCollapsed?'display:none':''}">

            <div style="margin-bottom:6px;text-align:right">

              <label style="font-size:11px;color:#95a5a6;cursor:pointer"><input type="checkbox" id="grpall_${gi}" onchange="toggleGroupAll(${gi})" ${checkedAll?'checked':''} style="width:auto;margin:0 4px 0 0"> 全选本组</label>

            </div>

            ${cards}

          </div>

        </div>`;

    }).join('');

    c.innerHTML = `

      <div style="margin-bottom:10px">

        <div style="display:flex;justify-content:space-between;align-items:center">

          <div style="font-size:13px;color:#e8e8e8"><strong>📁 管理相册目录</strong></div>

          <div style="font-size:12px;color:#7f8c8d" id="prCount">已启用 ${enabledCount} / ${totalCount}</div>

        </div>

        <input type="text" id="prSearch" placeholder="🔍 搜索相册名..." oninput="filterPhotoRoots()" style="margin-top:8px;width:100%">

      </div>

      <div id="prGroups">${groupsHtml}</div>

      <div style="display:flex;gap:8px;margin-top:14px">

        <button class="btn btn-success" onclick="savePhotoRoots()" style="flex:1">💾 保存更改</button>

        <button class="btn btn-primary" onclick="refreshPhotoRoots()">🔄 重新扫描</button>

        <button class="btn btn-secondary" onclick="scanPhotoRoots(false)">🔍 新增</button>

      </div>

      <div id="prScanArea" style="margin-top:10px"></div>

      <div id="prMsg" style="font-size:12px;margin-top:8px"></div>`;

  } catch(e) {

    c.innerHTML = `<div style="color:#e74c3c">❌ 加载失败: ${e.message}</div>`;

  }

}

function toggleGroupCollapse(gi) {

  window.__prCollapsed[gi] = !window.__prCollapsed[gi];

  loadPhotoRoots(prHost);

}

function toggleGroupAll(gi) {

  const cb = document.getElementById('grpall_'+gi);

  const boxes = document.querySelectorAll('#grpbody_'+gi+' input[type=checkbox].grpbox');

  boxes.forEach(b => b.checked = cb.checked);

}

function updateGroupState(gi) {

  const boxes = document.querySelectorAll('#grpbody_'+gi+' input[type=checkbox][data-g]');

  const all = Array.from(boxes).every(b => b.checked);

  const s = document.getElementById('grpall_'+gi);

  if (s) s.checked = all;

}

function filterPhotoRoots() {

  const q = (document.getElementById('prSearch')||{}).value || '';

  const groups = document.querySelectorAll('#prGroups > div');

  groups.forEach(g => {

    const cards = g.querySelectorAll('[data-g]');

    let visible = 0;

    cards.forEach(cb => {

      const row = cb.closest('div');

      const name = row.querySelector('div[style*="flex:1"]')?.textContent || '';

      const show = !q || name.toLowerCase().includes(q.toLowerCase());

      row.style.display = show ? '' : 'none';

      if (show) visible++;

    });

    g.style.display = visible ? '' : 'none';

  });

}

async function savePhotoRoots() {

  const msg = document.getElementById('prMsg');

  // 从当前 DOM 直接收集所有勾选状态(DOM是用户操作后的最新状态)
  const allBoxes = document.querySelectorAll('#prGroups input[type=checkbox].grpbox');

  if (!allBoxes.length) { msg.innerHTML = `<span style="color:#e74c3c">❌ 未找到相册checkbox,请先加载</span>`; return; }

  const checked = [];

  const unchecked = [];

  allBoxes.forEach(cb => {

    const p = cb.getAttribute('data-path');

    if (!p) return;

    if (cb.checked) checked.push(p); else unchecked.push(p);

  });

  msg.innerHTML = `⏳ 保存中(启用${checked.length}, 停用${unchecked.length})...`;

  try {

    // 全量同步: 勾选的启用, 未勾选的停用(需先enable后disable,避免同一路径冲突)
    if (checked.length) await apiPR(prHost, 'enable', { paths: checked });

    if (unchecked.length) await apiPR(prHost, 'disable', { paths: unchecked });

    msg.innerHTML = `<span style="color:#2ecc71">✅ 已保存: 启用${checked.length}个, 停用${unchecked.length}个</span>`;

    loadPhotoRoots(prHost);

  } catch(e) {

    msg.innerHTML = `<span style="color:#e74c3c">❌ 保存失败: ${e.message}</span>`;

  }

}



// 复制相册路径到剪贴板

function copyPhotoRootPath(path) {

  if (navigator.clipboard && navigator.clipboard.writeText) {

    navigator.clipboard.writeText(path).then(() => {

      const msg = document.getElementById('prMsg');

      if (msg) msg.innerHTML = `<span style="color:#2ecc71">✅ 已复制路径: ${escHtml(path)}</span>`;

    }).catch(() => fallbackCopyPath(path));

  } else {

    fallbackCopyPath(path);

  }

}

function fallbackCopyPath(path) {

  const ta = document.createElement('textarea');

  ta.value = path; ta.style.position = 'fixed'; ta.style.opacity = '0';

  document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, ta.value.length);

  try { document.execCommand('copy');

    const msg = document.getElementById('prMsg');

    if (msg) msg.innerHTML = `<span style="color:#2ecc71">✅ 已复制路径: ${escHtml(path)}</span>`;

  } catch(e) {

    const msg = document.getElementById('prMsg');

    if (msg) msg.innerHTML = `<span style="color:#f39c12">复制失败，路径: ${escHtml(path)}</span>`;

  }

  document.body.removeChild(ta);

}





// 重新启用已停用的相册路径



async function reactivatePhotoRoot(path) {



  const msg = document.getElementById('prMsg');



  msg.innerHTML = '⏳ 重新启用中...';



  try {



    const data = await apiPR(prHost, 'add', { paths: [path] });



    if (data.error) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${data.error}</span>`; return; }



    msg.innerHTML = `<span style="color:#2ecc71">✅ 已重新启用，相册总数 ${data.albums}</span>`;



    loadPhotoRoots(prHost);



  } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }



}











async function scanPhotoRoots(onlyNew) {
  // onlyNew=true: 新增扫描(只显示未配置)；false/undefined: 重新扫描(显示全部)
  const area = document.getElementById('prScanArea');

  const msg = document.getElementById('prMsg');

  area.innerHTML = '<div class="loading-dots" style="color:#7f8c8d">扫描中...</div>';

  msg.innerHTML = '';

  try {

    const data = await apiPR(prHost, 'scan');

    let all = data.discovered || [];
    // 重新扫描显示全部；新增扫描只显示未配置
    prDiscovered = (onlyNew === true) ? all.filter(d => !d.is_current) : all;

    if (!prDiscovered.length) { area.innerHTML = '<div style="color:#7f8c8d;font-size:12px">未发现可用相册目录</div>'; return; }


    // 勾选状态标记

    prChecked = {};

    const checks = prDiscovered.map((d,i) => `

      <div style="display:flex;align-items:center;padding:7px 10px;border:1px solid ${d.is_current?'#27ae60':'#2c3e50'};border-radius:8px;margin-bottom:5px;background:#16213e">

        <input type="checkbox" id="prc_${i}" data-idx="${i}" ${d.is_current?'disabled':''} onchange="updatePrChecked()" style="width:auto;margin:0 8px 0 0" ${d.is_current?'checked':''}>

        <div style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${d.path}">${d.path}</div>

        ${d.is_current?'<span style="font-size:11px;color:#2ecc71;flex-shrink:0">✅ 已配置</span>':''}

      </div>`).join('');



    area.innerHTML = `

      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">

        <div style="font-size:13px;color:#95a5a6">🗂 共发现 ${prDiscovered.length} 个相册目录</div>

        <label style="font-size:12px;color:#e8e8e8;display:flex;align-items:center;gap:4px">

          <input type="checkbox" id="prSelectAll" onchange="prToggleAll(this)" style="width:auto;margin:0"> 全选

        </label>

      </div>

      ${checks}

      <button class="btn btn-primary btn-sm" onclick="addSelectedPhotoRoots()" style="margin-top:8px">✅ 添加选中目录 (<span id="prAddCount">0</span>)</button>`;



  } catch(e) {



    area.innerHTML = `<div style="color:#e74c3c">❌ 扫描失败: ${e.message}</div>`;



  }



}



// 全选 / 取消全选（只勾选未配置的）

function prToggleAll(el) {

  const boxes = document.querySelectorAll('#prScanArea input[type=checkbox][data-idx]');

  boxes.forEach(b => { if (!b.disabled) b.checked = el.checked; });

  updatePrChecked();

}



// 更新选中计数

function updatePrChecked() {

  const boxes = document.querySelectorAll('#prScanArea input[type=checkbox][data-idx]');

  let n = 0;

  boxes.forEach(b => { if (b.checked && !b.disabled) n++; });

  const cnt = document.getElementById('prAddCount');

  if (cnt) cnt.textContent = n;

}







// 添加勾选的目录



async function addSelectedPhotoRoots() {



  const paths = [];



  prDiscovered.forEach((d,i) => { const cb = document.getElementById('prc_'+i); if (cb && cb.checked) paths.push(d.path); });



  const msg = document.getElementById('prMsg');



  if (!paths.length) { msg.innerHTML = '<span style="color:#f39c12">请先勾选要添加的目录</span>'; return; }



  msg.innerHTML = '⏳ 添加中...';



  try {



    const data = await apiPR(prHost, 'add', { paths });



    msg.innerHTML = `<span style="color:#2ecc71">✅ 已添加 ${(data.added||[]).length} 个目录，相册总数 ${data.albums}</span>`;



    loadPhotoRoots(prHost);



  } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }



}







// 停用一个目录（保留历史，可重新启用）



async function removePhotoRoot(path) {



  if (!confirm('确认停用相册根目录（将保留在历史，可重新启用）：\\n' + path)) return;



  const msg = document.getElementById('prMsg');



  msg.innerHTML = '⏳ 停用中...';



  try {



    const data = await apiPR(prHost, 'remove', { path });



    msg.innerHTML = `<span style="color:#2ecc71">✅ 已停用，相册总数 ${data.albums}</span>`;



    loadPhotoRoots(prHost);



  } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }



}







// 重新扫描相册



async function refreshPhotoRoots() {
  // 🔄 重新扫描：与新增扫描共用扫描逻辑，显示全部相册(含已配置)，可全选添加
  scanPhotoRoots(false);
}

// 手工添加相册路径



async function addManualPhotoRoot() {



  const input = document.getElementById('prManualPath');



  const msg = document.getElementById('prMsg');



  const path = (input.value || '').trim();



  if (!path) { msg.innerHTML = '<span style="color:#f39c12">请输入相册路径</span>'; return; }



  msg.innerHTML = '⏳ 添加中...';



  try {



    const data = await apiPR(prHost, 'add', { paths: [path] });



    if (data.error) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${data.error}</span>`; return; }



    msg.innerHTML = `<span style="color:#2ecc71">✅ 已添加，相册总数 ${data.albums}</span>`;



    input.value = '';



    loadPhotoRoots(prHost);



  } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }



}











function switchTab(name, el) {



  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));



  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));



  el.classList.add('active');



  document.getElementById('panel'+name.charAt(0).toUpperCase()+name.slice(1)).classList.add('active');



}







// 加载设备列表



async function loadDevices() {



  try {



    const r = await fetch('/api/devices');



    const data = await r.json();



    const list = document.getElementById('deviceList');



    if (!data.devices || data.devices.length === 0) {



      list.innerHTML = '<div style="color:#7f8c8d;font-size:13px">暂无已安装设备。请到"安装向导"安装。';



      return;



    }



    list.innerHTML = '<div class="grid">' + data.devices.map(d => `



      <div class="device-card" onclick="location.href='/goto/${d.host}'">



        <div class="ip"><span style="color:#3498db">▶</span> ${d.name || d.host}</div>



        <div class="name">${d.gallery_url}</div>



        <div style="font-size:11px;color:#7f8c8d;margin-top:4px">



          ${d.hostname ? d.hostname+' · ' : ''}安装: ${d.installed_at?.slice(0,10)||'?'}



          ${d.os_type ? ' · '+d.os_type : ''}



        </div>



        <span class="status status-ok">🟢 运行中</span>



        <div style="margin-top:8px"><button class="btn btn-primary" onclick="event.stopPropagation();openPhotoRootsModal('${d.host}')">📁 管理相册目录</button> <button class="btn" style="background:#c0392b;color:#fff" onclick="event.stopPropagation();uninstallDevice('${d.host}')">🗑️ 卸载</button></div>



      </div>



    `).join('') + '</div>';



  } catch(e) {



    document.getElementById('deviceList').innerHTML = '<div style="color:#e74c3c">加载失败: '+e.message+'</div>';



  }



}







// 卸载设备（真卸载，可重复安装）
async function uninstallDevice(host) {
  const password = prompt('请输入设备 ' + host + ' 的 SSH 密码用于卸载：');
  if (password === null) return;

  const txt = '确认卸载设备 ' + host + ' 的相册程序？ 将删除服务/venv/代码/调度；保留照片、config.py(照片路径)、缩略图缓存；此操作可重复安装重新恢复。';
  if (!confirm(txt)) return;

  const tip = confirm('是否保留缩略图缓存？建议保留，避免重新生成慢。点确定=保留缓存推荐；点取消=同时删除缓存');
  const keep_cache = tip;

  const logEl = document.getElementById('deviceList');
  if (logEl) logEl.innerHTML = '<div style="color:#7f8c8d;padding:20px">⏳ 正在卸载 ' + host + '，可能需要十几秒...</div>';

  try {
    const r = await fetch('/api/device/' + host + '/uninstall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep_cache: keep_cache, password: password })
    });
    const data = await r.json();
    if (data.ok) {
      alert('卸载成功：' + host);
    } else {
      alert('卸载失败：' + (data.error || '未知错误'));
    }
  } catch(e) {
    alert('卸载出错：' + e.message);
  }
  loadDevices();
}

// 扫描局域网




async function scanLan() {



  const btn = document.getElementById('scanBtn');



  btn.disabled = true; btn.textContent = '⏳ 扫描中...';



  document.getElementById('scanResult').innerHTML = '<div style="color:#7f8c8d">扫描中，请等待...</div>';



  try {



    const r = await fetch('/api/scan');



    const data = await r.json();



    scannedDevices = data.devices || [];



    const html = scannedDevices.map(d => `



      <div class="device-card" onclick="selectDevice('${d.ip}')" id="dev_${d.ip.replace(/\./g,'_')}">



        <div class="ip">${d.ip}</div>



        <div class="name">${d.hostname}</div>



      </div>



    `).join('');



    document.getElementById('scanResult').innerHTML =



      `<div style="color:#7f8c8d;font-size:12px;margin-bottom:8px">找到 ${data.count} 台设备（点击选择）</div>



       <div class="grid">${html||'<div style="color:#e74c3c">未发现设备</div>'}</div>`;



  } catch(e) {



    document.getElementById('scanResult').innerHTML = `<div style="color:#e74c3c">扫描失败: ${e.message}</div>`;



  }



  btn.disabled = false; btn.textContent = '🔍 重新扫描';



}







function selectDevice(ip) {



  document.querySelectorAll('#scanResult .device-card').forEach(el => el.style.borderColor='#2c3e50');



  const el = document.getElementById('dev_'+ip.replace(/\./g,'_'));



  if (el) el.style.borderColor = '#3498db';



  document.getElementById('installHost').value = ip;



  document.getElementById('installForm').style.display = 'block';



  document.getElementById('precheckResult').innerHTML = '';



  document.getElementById('installActions').style.display = 'none';



  document.getElementById('installLog').style.display = 'none';



}







// 预检设备



async function precheckDevice() {



  const host = document.getElementById('installHost').value;



  const user = document.getElementById('installUser').value;



  const pass = document.getElementById('installPass').value;



  if (!host || !pass) { alert('请填写IP和密码'); return; }



  const btn = document.getElementById('precheckBtn');



  btn.disabled = true; btn.textContent = '⏳ 预检中...';



  document.getElementById('precheckResult').innerHTML = '<div style="color:#7f8c8d">正在检查...</div>';



  document.getElementById('installActions').style.display = 'none';



  try {



    const r = await fetch('/api/precheck', {method:'POST', headers:{'Content-Type':'application/json'},



      body: JSON.stringify({host, username: user, password: pass}) });



    const data = await r.json();



    if (data.reachable === false) {



      document.getElementById('precheckResult').innerHTML =



        `<div id="resultBox" class="error">❌ 无法连接: ${data.error||'超时或无响应'}</div>`;



      btn.disabled = false; btn.textContent = '🔍 预检设备';



      return;



    }



    const passCheck = data.pass ? '<span class="status status-ok">✅ 通过</span>' : '<span class="status status-fail">❌ 不通过</span>';



    const warnings = (data.warnings||[]).map(w => `<div style="color:#e74c3c">⚠ ${w}</div>`).join('');



    document.getElementById('precheckResult').innerHTML = `



      <div id="resultBox" class="${data.pass?'success':'error'}">



        ${passCheck}



        <div style="margin-top:8px;font-size:13px;line-height:1.8">



          <div>🖥 OS: ${data.os_type||'?'}</div>



          <div>🖥 CPU: ${data.cpu_model||'?'} (${data.cpu_cores}核)</div>



          <div>💾 内存: ${data.ram_gb} GB</div>



          <div>📀 磁盘可用: ${data.disk_avail_gb} GB${data.disk_details.length>0?' ('+data.disk_details.map(d=>d.mount+':'+d.avail_gb+'G').join(', ')+')':''}</div>



          <div>🐍 Python: <span style="white-space:pre-line;word-break:break-all;font-size:12px">${data.has_python||'❌'}</span></div>



          <div>🖥 设备: ${data.hostname||data.host||'?'}</div>



          <div>🖥 OS: <span style="word-break:break-all">${data.os_info||'?'}</span></div>



          ${data.installed?'<div style="color:#2ecc71">📦 已安装</div>':''}



        </div>



        ${warnings}



      </div>`;



    if (data.pass || data.installed) {



      document.getElementById('installActions').style.display = 'block';



    }



  } catch(e) {



    document.getElementById('precheckResult').innerHTML = `<div id="resultBox" class="error">❌ ${e.message}</div>`;



  }



  btn.disabled = false; btn.textContent = '🔍 预检设备';



}







// 安装



async function installDevice() {



  if (!confirm('确认将NAS相册安装到该设备？')) return;



  const host = document.getElementById('installHost').value;



  const user = document.getElementById('installUser').value;



  const pass = document.getElementById('installPass').value;



  const path = document.getElementById('installPath').value;



  const btn = document.getElementById('installBtn');



  btn.disabled = true; btn.textContent = '⏳ 安装中...';



  const logBox = document.getElementById('installLog');



  logBox.style.display = 'block';



  logBox.innerHTML = '开始安装...';



  document.getElementById('installActions').style.display = 'none';



  try {



    const r = await fetch('/api/install', {method:'POST', headers:{'Content-Type':'application/json'},



      body: JSON.stringify({host, username: user, password: pass, install_path: path}) });



    const data = await r.json();



    if (data.success) {



      const url = data.device?.gallery_url || `http://${host}:5000`;



      logBox.innerHTML = data.logs.map(l => `<div>  ${l}</div>`).join('') +



        '<div style="color:#2ecc71;margin-top:12px;font-size:14px">✅ 安装成功！</div>' +



        '<div style="margin-top:8px;padding:10px;background:#0f0f23;border-radius:8px;border:1px solid #27ae60">' +



        '  <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">🌐 相册地址</div>' +



        '  <a href="'+url+'" target="_blank" style="color:#3498db;font-size:16px;text-decoration:none">'+url+'</a>' +



        '  <span style="color:#7f8c8d;font-size:11px;margin-left:8px">👆 点击打开</span>' +



        '</div>';



      loadDevices();



    } else {



      logBox.innerHTML += `<div style="color:#e74c3c">❌ 安装失败: ${data.error||'未知错误'}</div>`;



      if (data.logs) logBox.innerHTML = data.logs.map(l => `<div>  ${l}</div>`).join('') + logBox.innerHTML;



    }



  } catch(e) {



    logBox.innerHTML += `<div style="color:#e74c3c">❌ ${e.message}</div>`;



  }



  btn.disabled = false; btn.textContent = '🚀 开始安装';



}







loadDevices();



</script>



</body>



</html>'''







def uninstall_gallery(host, username, password, port=22, install_path=None, os_type=None, keep_cache=True):
    """在目标设备上卸载NAS相册程序 — 支持重复安装/卸载。

    保留（不删除）：
      - config.py（照片根目录路径，便于重装后沿用）
      - 缩略图缓存目录（app/cache 及独立缓存目录）
      - 照片本体（config.py 指向的原始目录，永不触碰）

    删除：
      - 相册服务进程 (app.py)
      - venv 虚拟环境
      - .git 代码库
      - 夜间缩略图调度 (crontab 行 / schtasks)
      - 启动脚本、日志
      调用方应负责从 devices.json 移除设备记录。
    """
    import paramiko
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password,
                    timeout=15, allow_agent=False, look_for_keys=False)

        logs = []
        def log(msg):
            logs.append(msg)
            print(f"  {msg}", flush=True)

        # 检测 OS（若未显式传入）
        if not os_type:
            os_type = detect_os(ssh)
        log(f"检测到系统: {os_type}")

        # 智能默认路径
        if not install_path:
            install_path = 'C:\\nas-photo' if os_type == 'windows' else '/opt/nas-photo'
        log(f"卸载路径: {install_path}")

        # ── 1. 停止相册服务 ──
        log("停止相册服务...")
        if os_type == 'windows':
            _ssh_cmd(ssh, f'taskkill /f /im python.exe 2>nul', timeout=10)
            _ssh_cmd(ssh, f'taskkill /f /im pythonw.exe 2>nul', timeout=10)
        else:
            _ssh_cmd(ssh, 'pkill -f "app.py" 2>/dev/null; sleep 1', timeout=10)
        log("   ✅ 服务已停止")

        # ── 2. 移除夜间缩略图调度 ──
        log("移除夜间缩略图调度...")
        if os_type == 'windows':
            _ssh_cmd(ssh, 'schtasks /delete /tn nightly_precache /f 2>nul', timeout=10)
        else:
            # 从 crontab 删除包含 insprint_path 中 nightly_precache 的那一行
            rm = f'crontab -l 2>/dev/null | grep -v "nightly_precache" | crontab -'
            _ssh_cmd(ssh, rm, timeout=10)
        log("   ✅ 调度已移除")

        # ── 3. 删除 venv ──
        log("删除虚拟环境 venv...")
        if os_type == 'windows':
            _ssh_cmd(ssh, f'if exist "{install_path}\\venv" rmdir /s /q "{install_path}\\venv"', timeout=30)
            _ssh_cmd(ssh, f'if exist "{install_path}\\app\\venv" rmdir /s /q "{install_path}\\app\\venv"', timeout=30)
        else:
            _ssh_cmd(ssh, f'rm -rf {install_path}/venv {install_path}/app/venv', timeout=30)
        log("   ✅ venv 已删除")

        # ── 4. 删除 .git（为干净重装）──
        log("删除 .git 代码仓库...")
        if os_type == 'windows':
            _ssh_cmd(ssh, f'if exist "{install_path}\\.git" rmdir /s /q "{install_path}\\.git"', timeout=20)
        else:
            _ssh_cmd(ssh, f'rm -rf {install_path}/.git', timeout=20)
        log("   ✅ .git 已删除")

        # ── 5. 清理启动脚本/日志（保留 config.py 和 cache）──
        log("清理启动脚本与日志...")
        if os_type == 'windows':
            _ssh_cmd(ssh, f'del "{install_path}\\start.bat" "{install_path}\\start_hidden.vbs" "{install_path}\\*.log" 2>nul', timeout=10)
        else:
            _ssh_cmd(ssh, f'rm -f {install_path}/start.sh {install_path}/app.log {install_path}/app_output.log 2>/dev/null', timeout=10)
        log("   ✅ 已清理启动脚本/日志")

        # ── 6. 缩略图缓存处理 ──
        if keep_cache:
            log("保留缩略图缓存 (config.py + 缩略图缓存，便于重装沿用)")
        else:
            log("删除缩略图缓存...")
            if os_type == 'windows':
                _ssh_cmd(ssh, f'if exist "{install_path}\\app\\cache" rmdir /s /q "{install_path}\\app\\cache"', timeout=30)
            else:
                _ssh_cmd(ssh, f'rm -rf {install_path}/app/cache 2>/dev/null; rm -rf {install_path}-cache 2>/dev/null', timeout=30)
            log("   ✅ 缩略图缓存已删除")
        log("   (照片本体永不删除)")

        ssh.close()
        return {'success': True, 'logs': logs}
    except Exception as e:
        import traceback
        return {'success': False, 'error': str(e), 'traceback': traceback.format_exc(), 'logs': logs if 'logs' in dir() else []}




def create_app():

    from flask import Flask, jsonify, request, render_template_string, redirect







    app = Flask(__name__)







    # CORS支持（跨端口读取设备列表）



    @app.after_request



    def add_cors(response):



        response.headers['Access-Control-Allow-Origin'] = '*'



        response.headers['Access-Control-Allow-Headers'] = '*'



        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'



        return response







    @app.route('/')



    def index():



        return render_template_string(MANAGER_HTML)







    @app.route('/api/devices')



    def api_devices():



        return jsonify(_load_devices())







    @app.route('/api/scan')



    def api_scan():



        devices, net = scan_lan()



        return jsonify({'devices': devices, 'net': net, 'count': len(devices)})







    @app.route('/api/precheck', methods=['POST'])



    def api_precheck():



        data = request.get_json() or {}



        host = data.get('host', '')



        username = data.get('username', 'root')



        password = data.get('password', '')



        port = int(data.get('port', 22))



        if not host:



            return jsonify({'error': 'host required'}), 400



        return jsonify(precheck_device(host, username, password, port))







    @app.route('/api/install', methods=['POST'])



    def api_install():



        data = request.get_json() or {}



        host = data.get('host', '')



        username = data.get('username', 'root')



        password = data.get('password', '')



        port = int(data.get('port', 22))



        install_path = data.get('install_path', '/opt/nas-photo')



        if not host or not password:



            return jsonify({'error': 'host and password required'}), 400



        return jsonify(install_gallery(host, username, password, port, install_path))







    @app.route('/api/device/<host>')



    def api_device(host):



        device, _ = _get_device(host)



        if device:



            return jsonify(device)



        return jsonify({'error': 'not found'}), 404







    @app.route('/api/device/<host>/delete', methods=['DELETE'])



    def api_delete_device(host):



        data = _load_devices()



        data['devices'] = [d for d in data['devices'] if d.get('host') != host]



        _save_devices(data)



        return jsonify({'ok': True})







    @app.route('/api/device/<host>/uninstall', methods=['POST'])
    def api_uninstall_device(host):
        """真卸载：停止服务 + 删除 venv/.git/调度，保留 config.py + 照片。
        密码由前端传入（devices.json 不存密码）；keep_cache 控制是否删缩略图缓存。"""
        data = _load_devices()
        dev = next((d for d in data['devices'] if d.get('host') == host), None)
        if not dev:
            return jsonify({'ok': False, 'error': f'设备 {host} 不在列表'}), 404

        body = request.get_json() or {}
        password = body.get('password') or dev.get('username', 'root')
        keep_cache = body.get('keep_cache', True)  # 默认保留缩略图缓存（避免重新生成慢）

        # 构造卸载参数
        result = uninstall_gallery(
            host, dev.get('username', 'root'), password,
            port=dev.get('port', 22), install_path=dev.get('install_path'),
            os_type=dev.get('os_type'), keep_cache=keep_cache,
        )
        if not result.get('success'):
            return jsonify({'ok': False, 'error': result.get('error'), 'logs': result.get('logs', [])}), 500

        # 卸载成功后移除设备记录
        data['devices'] = [d for d in data['devices'] if d.get('host') != host]
        _save_devices(data)

        return jsonify({'ok': True, 'logs': result.get('logs', []), 'removed': host})

    # ── 相册目录管理（代理到设备相册服务）────────────────



    @app.route('/api/device/<host>/photo_roots')



    def api_device_photo_roots(host):



        return jsonify(_device_photo_roots_request(host, 'list'))







    @app.route('/api/device/<host>/photo_roots/history')



    def api_device_photo_roots_history(host):



        return jsonify(_device_photo_roots_request(host, 'history'))







    @app.route('/api/device/<host>/photo_roots/scan')



    def api_device_photo_roots_scan(host):



        return jsonify(_device_photo_roots_request(host, 'scan'))







    @app.route('/api/device/<host>/photo_roots/add', methods=['POST'])



    def api_device_photo_roots_add(host):



        data = request.get_json() or {}



        return jsonify(_device_photo_roots_request(host, 'add', {'paths': data.get('paths', [])}))







    @app.route('/api/device/<host>/photo_roots/remove', methods=['POST'])



    def api_device_photo_roots_remove(host):



        data = request.get_json() or {}



        return jsonify(_device_photo_roots_request(host, 'remove', {'path': data.get('path', '')}))







    @app.route('/api/device/<host>/photo_roots/albums')

    def api_device_photo_roots_albums(host):

        return jsonify(_device_photo_roots_request(host, 'albums'))

    @app.route('/api/device/<host>/photo_roots/enable', methods=['POST'])

    def api_device_photo_roots_enable(host):

        data = request.get_json() or {}

        return jsonify(_device_photo_roots_request(host, 'enable', {'paths': data.get('paths', [])}))

    @app.route('/api/device/<host>/photo_roots/disable', methods=['POST'])

    def api_device_photo_roots_disable(host):

        data = request.get_json() or {}

        return jsonify(_device_photo_roots_request(host, 'disable', {'paths': data.get('paths', [])}))

    @app.route('/api/device/<host>/photo_roots/refresh', methods=['GET', 'POST'])



    def api_device_photo_roots_refresh(host):



        return jsonify(_device_photo_roots_request(host, 'refresh'))







    @app.route('/goto/<host>')



    def goto_device(host):



        device, _ = _get_device(host)



        if device:



            return redirect(device.get('gallery_url', f'http://{host}:5000'))



        return 'Device not found', 404







    return app











def main():



    log_file = open(str(SCRIPT_DIR / 'server.log'), 'a', buffering=1)



    sys.stdout = log_file



    sys.stderr = log_file







    app = create_app()



    print(f"\n📡 NAS相册管理面板 v1.0", flush=True)



    print(f"   地址: http://{HOST}:{PORT}", flush=True)



    print(f"   设备配置: {DEVICES_PATH}", flush=True)



    print(flush=True)



    app.run(host=HOST, port=PORT, debug=False, threaded=True)











if __name__ == '__main__':



    if hasattr(sys.stdout, 'reconfigure'):



        try:



            sys.stdout.reconfigure(encoding='utf-8', errors='replace')



            sys.stderr.reconfigure(encoding='utf-8', errors='replace')



        except:



            pass



    main()
