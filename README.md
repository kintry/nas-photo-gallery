# NAS Photo Gallery

A cross-platform LAN photo album web app. Browse photos and videos on any device in your home network.

## Features

- Photo gallery with thumbnails and lazy loading
- Video playback with streaming support
- Cross-platform: Linux, Windows, macOS
- LAN access from any device
- Mobile-friendly responsive design

## Quick Start

### 1. Install Python 3.10+

### 2. Install dependencies

```bash
pip install flask pillow
```

For video thumbnails (optional but recommended):

```bash
pip install imageio-ffmpeg
```

### 3. Configure

Copy `app/config.example.py` to `app/config.py` and set your photo directories.

### 4. Run

```bash
cd app
python app.py
```

Open **http://localhost:5000** in your browser.

## Project Structure

```
nas-photo-gallery/
+-- app/
|   +-- app.py              # Main Flask app
|   +-- config.example.py   # Config template
|   +-- plat/               # Platform adaptation
|   |   +-- __init__.py
|   |   +-- linux.py
|   |   +-- windows.py
|   |   +-- macos.py
|   +-- static/
|   |   +-- app.js
|   |   +-- style.css
|   +-- templates/
|       +-- index.html
+-- nightly_precache.py
+-- requirements.txt
+-- README.md
