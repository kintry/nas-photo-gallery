#!/usr/bin/env bash
# ============================================================
# NAS相册 一键安装脚本 (Linux / macOS)
# 从 GitHub 公开仓库拉取最新代码并部署
# ============================================================
set -e

REPO_URL="https://github.com/kintry/nas-photo-gallery.git"
INSTALL_DIR="${1:-$HOME/nas-photo-gallery}"
PORT="${PORT:-5000}"
MANAGER_PORT="${MANAGER_PORT:-5001}"

echo "========================================"
echo " 🖼️ NAS相册 安装程序 (Linux/macOS)"
echo "========================================"
echo "安装路径: $INSTALL_DIR"

echo ""
echo "[1/4] 检查依赖..."
command -v git >/dev/null 2>&1 || { echo "  ✗ 需要安装 git"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "  ✗ 需要安装 python3"; exit 1; }

echo ""
echo "[2/4] 拉取代码..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  已存在，更新到最新..."
    git -C "$INSTALL_DIR" fetch --all
    git -C "$INSTALL_DIR" reset --hard origin/main 2>/dev/null || git -C "$INSTALL_DIR" pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

echo ""
echo "[3/4] 创建虚拟环境并安装依赖..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

echo ""
echo "[4/4] 生成配置并启动..."
# 首次运行生成 config.py（若不存在）
if [ ! -f "config.py" ]; then
    cp config.example.py config.py
    echo "  ✓ 已生成 config.py（请编辑 PHOTO_ROOTS 填入照片目录，然后重启）"
fi

# 启动相册服务
nohup ./venv/bin/python -u app.py > app.log 2>&1 &
echo "  ✓ 相册服务已启动: http://0.0.0.0:${PORT}"

# 启动管理面板
nohup ./venv/bin/python -u manager.py > manager.log 2>&1 &
echo "  ✓ 管理面板已启动: http://0.0.0.0:${MANAGER_PORT}"

echo ""
echo "========================================"
echo " ✅ NAS相册 安装完成！"
echo "  相册地址: http://<本机IP>:${PORT}"
echo "  管理面板: http://<本机IP>:${MANAGER_PORT}"
echo ""
echo " ⚠️ 首次使用请编辑 config.py 设置照片目录，然后重启服务"
echo "========================================"
