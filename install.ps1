# ============================================================
# NAS相册 一键安装脚本 (Windows)
# 从 GitHub 公开仓库拉取最新代码并部署
# ============================================================
param(
    [string]$InstallDir = "$HOME\nas-photo-gallery",
    [int]$Port = 5000,
    [int]$ManagerPort = 5001
)

$RepoUrl = "https://github.com/kintry/nas-photo-gallery.git"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   NAS相册 安装程序 (Windows)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "安装路径: $InstallDir"

Write-Host ""
Write-Host "[1/4] 检查依赖..."
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  X 需要安装 Git: https://git-scm.com/" -ForegroundColor Red
    exit 1
}
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host "  X 需要安装 Python 3: https://python.org/" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[2/4] 拉取代码..."
if (Test-Path "$InstallDir\.git") {
    Write-Host "  已存在，更新到最新..."
    Set-Location $InstallDir
    git fetch --all
    git reset --hard origin/main 2>$null
    if ($LASTEXITCODE -ne 0) { git pull }
} else {
    git clone $RepoUrl $InstallDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  X 克隆失败（检查网络/仓库地址）" -ForegroundColor Red
        exit 1
    }
}
Set-Location $InstallDir

Write-Host ""
Write-Host "[3/4] 创建虚拟环境并安装依赖..."
if (-not (Test-Path "venv")) {
    python -m venv venv
}
$pip = "$InstallDir\venv\Scripts\pip"
& $pip install --upgrade pip -q
& $pip install -r requirements.txt -q

Write-Host ""
Write-Host "[4/4] 生成配置并启动..."
if (-not (Test-Path "config.py")) {
    Copy-Item config.example.py config.py
    Write-Host "  v 已生成 config.py（请编辑 PHOTO_ROOTS 填入照片目录，然后重启）"
}

# 启动相册服务（后台）
Start-Process -WindowStyle Hidden -FilePath "$InstallDir\venv\Scripts\python.exe" -ArgumentList "-u","app.py" -WorkingDirectory $InstallDir
Write-Host "  相册服务已启动: http://0.0.0.0:${Port}" -ForegroundColor Green
# 启动管理面板
Start-Process -WindowStyle Hidden -FilePath "$InstallDir\venv\Scripts\python.exe" -ArgumentList "-u","manager.py" -WorkingDirectory $InstallDir
Write-Host "  管理面板已启动: http://0.0.0.0:${ManagerPort}" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   NAS相册 安装完成！" -ForegroundColor Green
Write-Host "  相册地址: http://<本机IP>:${Port}"
Write-Host "  管理面板: http://<本机IP>:${ManagerPort}"
Write-Host ""
Write-Host "  首次使用请编辑 config.py 设置照片目录，然后重启服务" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
