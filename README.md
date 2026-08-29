# 🖼️ NAS相册 (NAS Photo Gallery)

跨平台的局域网照片浏览与管理程序。支持 **Windows / Linux / macOS**，通过浏览器访问，自动识别设备上的照片目录并生成缩略图，提供相册浏览、照片查看、视频播放、分类管理等功能。

> 设计目标：一套代码，三平台运行（Win / Linux / Mac），可作为 NAS 应用或直接装在任意一台电脑上。

---

## ✨ 功能特性

- 🌐 **纯浏览器访问**：无需装客户端，手机/电脑浏览器直接打开
- 📁 **自动扫描相册**：配置照片根目录后，自动识别其下所有子目录为相册；安装后自动全盘扫描并批量纳入
- 🖼️ **缩略图 + 大图**：自动生成缩略图（含 RGBA/PNG 兼容），点击看原图
- 🎬 **视频支持**：照片和视频混合浏览
- 🗂️ **相册管理面板**：扫描新增 / 停用 / 手工录入目录，软删除保留历史
- 🌙 **夜间缩略图预生成**：定时任务空闲时预生成，加快浏览
- 🔀 **多设备管理**：管理面板可远程安装/管理多台设备的相册程序
- 🧠 **智能端口**：默认 5000，被系统占用时自动改用 5080
- 🚀 **国内网络友好**：GitHub 克隆/依赖下载支持代理与镜像加速（清华 pip 源）

---

## 🚀 快速开始

### 方式一：一键安装脚本（推荐）

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/kintry/nas-photo-gallery/main/install.sh | bash

# Windows (PowerShell)
curl -O https://raw.githubusercontent.com/kintry/nas-photo-gallery/main/install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1
```

脚本会自动：检出代码 → 安装依赖 → 生成配置 → 启动相册服务(默认 :5000) → 启动管理面板(默认 :5001)。

### 方式二：手动安装

```bash
git clone https://github.com/kintry/nas-photo-gallery.git
cd nas-photo-gallery
cp config.example.py app/config.py    # 配置照片根目录
pip install -r requirements.txt
python app.py                          # 启动相册
python manager.py                      # 启动管理面板(可选)
```

---

## 📦 项目结构

```
nas-photo-gallery/
├── app.py                 # 相册服务（Flask）
├── manager.py             # 管理面板（安装向导/设备管理）
├── nightly_precache.py    # 夜间缩略图预生成
├── thumb_worker.py        # 缩略图生成线程
├── requirements.txt
├── plat/                  # 跨平台适配层 (windows/linux/macos)
├── static/                # 前端静态资源
├── templates/             # 页面模板
├── config.example.py      # 配置模板（复制为 config.py 使用）
└── install.sh / install.ps1
```

---

## ⚙️ 配置

复制 `config.example.py` 为 `app/config.py`，编辑 `PHOTO_ROOTS` 填入你的照片目录：

```python
# Windows
PHOTO_ROOTS = [r'D:\相册库', r'D:\我的照片']

# Linux / macOS
PHOTO_ROOTS = [r'/mnt/photo/相册', r'/home/user/Pictures']
```

每个根目录下的一级子目录会作为一个相册。修改 `PHOTO_ROOTS` 后重启服务即可。

---

## 🖥️ 管理面板

管理面板（`:5001`）提供：
- 📎 **安装向导**：在局域网内其他设备（Win/Linux/Mac）远程安装相册程序，支持填写 GitHub 代理/镜像地址加速国内拉取
- 🗂️ **相册目录管理**：扫描发现未纳入的相册目录、一键添加、停用/恢复（软删除保留历史）、手工录入路径；扫描器自动过滤系统/软件垃圾目录
- 📊 **设备管理**：查看已安装设备、服务状态、远程卸载

---

## 🧑‍💻 开发 / 第三方适配

- 跨平台适配层在 `plat/`：windows.py / linux.py / macos.py，新增系统实现对应接口即可
- 前端在 `static/app.js` + `templates/index.html`，后端 Flask API 见 `app.py`

---

## 📄 License

内部开发使用。二次分发请保留出处。
