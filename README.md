# 📸 NAS Photo Gallery

A lightweight, self-hosted photo and video gallery for NAS devices. Browse, view, and manage your media library directly from any browser — no external cloud services needed.

![Demo](https://img.shields.io/badge/demo-NAS%20photo%20gallery-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![License](https://img.shields.io/badge/license-MIT-orange)

## ✨ Features

- **📁 Auto-scan albums** — Scans directories on your NAS and organizes them into albums
- **📷 Photo browsing** — Grid view with lazy loading, scroll to load more
- **🎬 Video support** — Plays MP4, MOV, AVI, MKV, and more with streaming and scrubbing
- **🖼️ Thumbnails** — Auto-generated thumbnails (400px) for fast browsing
- **🎥 Video thumbnails** — Extracts real frames from videos via ffmpeg
- **❤️ Like system** — Bookmark your favorite photos/videos
- **📱 Mobile-friendly** — Responsive design works on phones and tablets
- **🔄 Auto-play slideshow** — Hands-free browsing experience
- **↔️ Touch/Keyboard navigation** — Swipe on mobile, arrow keys on desktop
- **🔍 Zoom** — Double-tap/click to zoom into photos
- **⚡ Caching** — Memory and disk caching for snappy navigation
- **📊 Album stats** — Shows photo counts and video counts per album
- **🎬 Video streaming** — Supports Range requests for seekable video playback

## 📸 Screenshots

> *Album grid view · Photo grid with videos · Full-screen viewer with thumb strip*

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Pillow (for image processing)
- ffmpeg (optional, for video thumbnails)
- A NAS or server with mounted photo directories

### Installation

```bash
# Clone the repo
git clone https://github.com/kintry/nas-photo-gallery.git
cd nas-photo-gallery

# Install dependencies
pip install flask pillow

# (Optional) Install ffmpeg for video thumbnails
# Ubuntu/Debian: sudo apt install ffmpeg
# Alpine: apk add ffmpeg
# macOS: brew install ffmpeg
```

### Configuration

Edit the photo roots in `app/app.py` to point to your photo directories:

```python
PHOTO_ROOTS = [
    '/path/to/your/photos',
    '/path/to/more/albums',
]
```

Or better, create a `config.py` file:

```python
# config.py
PHOTO_ROOTS = [
    '/mnt/nas/photos',
    '/mnt/nas/family',
]
CACHE_DIR = '/path/to/cache'  # defaults to nas-photo-cache
```

### Run

```bash
cd app
python3 app.py
```

Then open `http://your-nas-ip:5000` in your browser.

## 🏗️ Project Structure

```
nas-photo-gallery/
├── app/
│   ├── app.py              # Main Flask application
│   ├── static/
│   │   ├── app.js          # Frontend JavaScript
│   │   └── style.css       # Stylesheet
│   └── templates/
│       └── index.html      # Main template
├── requirements.txt        # Python dependencies
└── README.md
```

## 🖥️ Supported Media Formats

| Type | Formats |
|------|---------|
| 📷 **Photos** | JPG, JPEG, PNG, GIF, BMP, WebP |
| 🎬 **Videos** | MP4, MOV, AVI, MKV, MTS, M2TS, 3GP, WMV, MPG, MPEG |

## 🔧 Advanced Usage

### Custom Cache Location

```python
CACHE_DIR = Path('/your/cache/path')
```

### Change Port

```python
PORT = 8080  # default: 5000
```

### Pre-generate Thumbnails

Thumbnails are auto-generated on first access. For large libraries, you can pre-generate them by visiting the album list page.

### Video Streaming

Video files are served with Range request support, enabling seek and scrub in the browser player. Perfect for large video files.

## 🌐 Deployment

### As a systemd service (Linux)

```ini
[Unit]
Description=NAS Photo Gallery
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/nas-photo-gallery/app
ExecStart=/usr/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### With Docker (coming soon)

## 🤝 Contributing

Contributions are welcome! Feel free to:

- Report bugs via GitHub Issues
- Submit Pull Requests for new features
- Suggest improvements

## 📝 License

MIT License — see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgements

- Built with [Flask](https://flask.palletsprojects.com/)
- Image processing with [Pillow](https://python-pillow.org/)
- Video thumbnails via [ffmpeg](https://ffmpeg.org/)
