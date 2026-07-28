/**
 * NAS相册 - 前端交互（含视频支持）
 */
(function() {
  'use strict';

  // ── 状态 ──
  let currentAlbum = '';
  let allPhotos = [];
  let currentPage = 1;
  let totalPages = 1;
  let currentIndex = -1;
  let likedIds = new Set();
  let isLoading = false;
  let isAutoPlaying = false;
  let autoPlayTimer = null;
  let touchStartX = 0;
  let currentMode = 'photo'; // 'photo' 或 'video'


  // ── DOM 引用 ──
  const albumGrid = document.getElementById('albumGrid');
  const photoGrid = document.getElementById('photoGrid');
  const loadMore = document.getElementById('loadMore');
  const albumsPage = document.getElementById('albumsPage');
  const photosPage = document.getElementById('photosPage');
  const viewerOverlay = document.getElementById('viewerOverlay');
  const viewerImage = document.getElementById('viewerImage');
  const viewerVideo = document.getElementById('viewerVideo');
  const viewerContainer = document.getElementById('viewerContainer');
  const viewerCounter = document.getElementById('viewerCounter');
  const thumbTrack = document.getElementById('thumbTrack');
  const breadcrumb = document.getElementById('breadcrumb');
  const likeBtn = document.getElementById('likeBtn');
  const infoPopup = document.getElementById('infoPopup');
  const infoContent = document.getElementById('infoContent');


  function photoId(p) { return p.id || p.filename.replace(/[^a-zA-Z0-9]/g, '_'); }
  function thumbUrl(p) { return '/thumb/' + photoId(p) + '?path=' + encodeURIComponent(p.path) + '&size=400'; }
  function rawUrl(p) {
    if (p.type === 'video') {
      return '/raw_video/' + photoId(p) + '?path=' + encodeURIComponent(p.path);
    }
    return '/raw/' + photoId(p) + '?path=' + encodeURIComponent(p.path);
  }
  function isVideo(p) { return p.type === 'video'; }


  // ══════════════════════════════════════════
  //  相册列表
  // ══════════════════════════════════════════

  window.showAlbums = function() {
    albumsPage.style.display = 'block';
    photosPage.style.display = 'none';
    viewerOverlay.style.display = 'none';
    breadcrumb.textContent = '';
    currentAlbum = '';
    if (albumGrid.querySelector('.loading')) loadAlbums();
  };

  async function loadAlbums() {
    albumGrid.innerHTML = '<div class="loading">加载中...</div>';
    try {
      const hostResp = await fetch('/api/hostname');
      const hostData = await hostResp.json();
      const hname = hostData.hostname || 'OECT';
      const titleEl = document.getElementById('siteTitle');
      if (titleEl) titleEl.textContent = '📸 ' + hname + '·相册';
    } catch(e) {}
    try {
      const resp = await fetch('/api/albums');
      const data = await resp.json();
      if (data.error) { albumGrid.innerHTML = `<div class="loading">❌ ${data.error}</div>`; return; }
      renderAlbums(data.albums);
    } catch(e) {
      albumGrid.innerHTML = `<div class="loading">❌ 连接失败: ${e.message}</div>`;
    }
  }

  function renderAlbums(albums) {
    if (!albums || albums.length === 0) {
      albumGrid.innerHTML = '<div class="loading">暂无相册</div>';
      return;
    }
    albumGrid.innerHTML = albums.map(a => {
      const cover = a.cover;
      const coverStyle = cover
        ? `background-image:url('/thumb/${photoId(cover)}?path=${encodeURIComponent(cover.path)}&size=400');background-size:cover;background-position:center;`
        : `background:${randomColor(a.name)};display:flex;align-items:center;justify-content:center;font-size:40px;`;
      const coverContent = cover ? '' : '📁';
      const hasVideo = a.video_count > 0;
      return `<div class="album-card" onclick="openAlbum('${escHtml(a.path)}')">
        <div class="album-cover" style="${coverStyle}">${coverContent}</div>
        <div class="album-info">
          <div class="album-name">${escHtml(a.name)}</div>
          <div class="album-count">${a.photo_count_only || a.photo_count} 张照片${hasVideo ? ' · ' + a.video_count + ' 个视频' : ''}</div>
        </div>
      </div>`;
    }).join('');
  }

  function randomColor(s) {
    const colors = ['#0f3460','#16213e','#1a1a2e','#2c3e50','#1a5276','#0e6655','#6c3483','#943126'];
    let hash = 0;
    for (let i = 0; i < (s||'').length; i++) hash = ((hash << 5) - hash) + s.charCodeAt(i);
    return colors[Math.abs(hash) % colors.length];
  }

  function escHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }


  // ══════════════════════════════════════════
  //  相册照片（含视频）
  // ══════════════════════════════════════════

  window.openAlbum = function(albumPath) {
    currentAlbum = albumPath;
    currentPage = 1;
    allPhotos = [];
    albumsPage.style.display = 'none';
    photosPage.style.display = 'block';
    viewerOverlay.style.display = 'none';
    breadcrumb.textContent = albumPath.split('/').pop();
    photoGrid.innerHTML = '<div class="loading">加载中...</div>';
    loadPhotos();
  };

  async function loadPhotos() {
    if (isLoading) return;
    isLoading = true;
    loadMore.textContent = '加载中...';
    try {
      const resp = await fetch(`/api/photos?album=${encodeURIComponent(currentAlbum)}&page=${currentPage}&per_page=20`);
      const data = await resp.json();
      if (data.error) { loadMore.textContent = `❌ ${data.error}`; isLoading = false; return; }
      allPhotos = allPhotos.concat(data.photos);
      totalPages = data.total_pages;
      renderPhotos(data.photos);
      currentPage++;
      isLoading = false;
      if (currentPage > totalPages) {
        loadMore.textContent = '— 已全部加载 —';
      } else {
        loadMore.textContent = '点击加载更多...';
      }
    } catch(e) {
      loadMore.textContent = `❌ ${e.message}`;
      isLoading = false;
    }
  }

  window.addEventListener('scroll', function() {
    if (photosPage.style.display !== 'block') return;
    if (currentPage > totalPages) return;
    const rect = loadMore.getBoundingClientRect();
    if (rect.top < window.innerHeight + 100) {
      loadPhotos();
    }
  });

  function renderPhotos(photos) {
    if (currentPage === 1) photoGrid.innerHTML = '';
    const html = photos.map((p, i) => {
      const idx = allPhotos.length - photos.length + i;
      const isVid = isVideo(p);
      const vidOverlay = isVid ? '<div class="video-play-overlay"><span class="play-icon">▶</span></div>' : '';
      return `<div class="photo-item ${isVid ? 'video-item' : ''}" onclick="openViewer(${idx})">
        <img src="${thumbUrl(p)}" alt="${escHtml(p.filename)}" loading="lazy">
        ${vidOverlay}
      </div>`;
    }).join('');

    if (currentPage === 1) {
      photoGrid.innerHTML = html;
    } else {
      photoGrid.insertAdjacentHTML('beforeend', html);
    }
  }


  // ══════════════════════════════════════════
  //  大图/大视频 浏览
  // ══════════════════════════════════════════

  window.openViewer = function(index) {
    currentIndex = index;
    viewerOverlay.style.display = 'flex';
    updateViewer();
    loadThumbStrip();
    loadLikes();
  };

  function updateViewer() {
    if (currentIndex < 0 || currentIndex >= allPhotos.length) return;
    const p = allPhotos[currentIndex];
    const isVid = isVideo(p);

    // 切换显示/隐藏 图片和视频元素
    if (isVid) {
      viewerImage.style.display = 'none';
      viewerVideo.style.display = 'block';
      // 设置video源
      viewerVideo.src = rawUrl(p);
      viewerVideo.load();
      currentMode = 'video';
      // 自动播放
      viewerVideo.play().catch(function() {
        // 浏览器可能阻止自动播放，静默处理，用户手动点击即可
      });
      viewerCounter.textContent = `${currentIndex + 1} / ${allPhotos.length}  🎬`;
    } else {
      viewerVideo.pause();
      viewerVideo.src = '';
      viewerVideo.style.display = 'none';
      viewerImage.style.display = 'block';
      currentMode = 'photo';
      viewerImage.dataset.rawUrl = rawUrl(p);
      viewerImage.dataset.isRaw = 'true';
      viewerCounter.textContent = `${currentIndex + 1} / ${allPhotos.length}`;
      // 照片原图异步加载
      var _img = new Image();
      _img.onload = function() { viewerImage.src = rawUrl(p); };
      _img.onerror = function() { viewerImage.src = thumbUrl(p); };
      _img.src = rawUrl(p);
    }
    updateLikeBtn();
    scrollThumbToCurrent();
  }

  window.navigatePhoto = function(delta) {
    const newIdx = currentIndex + delta;
    if (newIdx < 0 || newIdx >= allPhotos.length) return;
    // 切换前暂停视频
    if (currentMode === 'video') {
      viewerVideo.pause();
      viewerVideo.src = '';
    }
    currentIndex = newIdx;
    updateViewer();
  };

  window.closeViewer = function(e) {
    if (e && e.target !== viewerOverlay && !e.target.closest('.btn-close')) {
      // 允许点击video标签本身关闭（但视频需要特殊处理）
      if (e.target.tagName !== 'VIDEO') return;
      // 如果视频全屏，按ESC退出全屏，不关闭
      if (document.fullscreenElement) return;
    }
    viewerOverlay.style.display = 'none';
    if (currentMode === 'video') {
      viewerVideo.pause();
      viewerVideo.src = '';
    }
    viewerImage.src = '';
    if (autoPlayTimer) { clearInterval(autoPlayTimer); autoPlayTimer = null; isAutoPlaying = false; }
  };

  // 键盘导航
  document.addEventListener('keydown', function(e) {
    if (viewerOverlay.style.display !== 'flex') return;
    if (e.key === 'ArrowLeft') navigatePhoto(-1);
    else if (e.key === 'ArrowRight') navigatePhoto(1);
    else if (e.key === 'Escape') closeViewer();
  });

  // 触摸滑动
  window.touchStart = function(e) {
    touchStartX = e.touches[0].clientX;
  };
  window.touchEnd = function(e) {
    const diff = e.changedTouches[0].clientX - touchStartX;
    if (Math.abs(diff) > 50) {
      navigatePhoto(diff > 0 ? -1 : 1);
    }
  };

  // 双击缩放（仅照片有效）
  window.toggleZoom = function(e) {
    if (currentMode === 'video') return;
    viewerImage.classList.toggle('zoomed');
  };


  // ══════════════════════════════════════════
  //  缩略图列表
  // ══════════════════════════════════════════

  function loadThumbStrip() {
    thumbTrack.innerHTML = allPhotos.map((p, i) => {
      const isVid = isVideo(p);
      return `<div class="thumb-item ${i === currentIndex ? 'active' : ''}" onclick="openViewer(${i})">
        <img src="${thumbUrl(p)}" loading="lazy">
        ${isVid ? '<span class="thumb-vid-icon">▶</span>' : ''}
      </div>`;
    }).join('');
  }

  function scrollThumbToCurrent() {
    const thumbs = thumbTrack.querySelectorAll('.thumb-item');
    thumbs.forEach((el, i) => el.classList.toggle('active', i === currentIndex));
    if (thumbs[currentIndex]) {
      thumbs[currentIndex].scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }
  }

  window.toggleThumbStrip = function() {
    const strip = document.getElementById('thumbStrip');
    const btn = document.getElementById('thumbToggle');
    strip.classList.toggle('collapsed');
    btn.textContent = strip.classList.contains('collapsed') ? '展开列表 ▲' : '收起列表 ▼';
  };


  // ══════════════════════════════════════════
  //  工具栏
  // ══════════════════════════════════════════

  window.downloadPhoto = function() {
    if (currentIndex < 0) return;
    const p = allPhotos[currentIndex];
    const a = document.createElement('a');
    a.href = rawUrl(p);
    a.download = p.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  window.toggleLike = async function() {
    if (currentIndex < 0) return;
    const p = allPhotos[currentIndex];
    const pid = photoId(p);
    try {
      const resp = await fetch('/api/like', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({photo_id: pid}),
      });
      const data = await resp.json();
      if (data.liked) likedIds.add(pid); else likedIds.delete(pid);
      updateLikeBtn();
    } catch(e) {
      console.error('点赞失败', e);
    }
  };

  function updateLikeBtn() {
    if (currentIndex < 0) return;
    const p = allPhotos[currentIndex];
    const pid = photoId(p);
    const liked = likedIds.has(pid);
    likeBtn.textContent = liked ? '❤️' : '🤍';
    likeBtn.className = 'tool-btn' + (liked ? ' liked' : '');
  }

  async function loadLikes() {
    try {
      const resp = await fetch('/api/likes');
      const data = await resp.json();
      likedIds = new Set(data.liked_ids || []);
      updateLikeBtn();
    } catch(e) {}
  }

  window.toggleAutoPlay = function() {
    // 自动播放仅对照片有效
    if (currentMode === 'video') return;
    const btns = [document.getElementById('autoPlayBtn'), document.getElementById('autoPlayBtn2')];
    if (isAutoPlaying) {
      clearInterval(autoPlayTimer);
      autoPlayTimer = null;
      isAutoPlaying = false;
      btns.forEach(b => { if(b) b.textContent = '▶'; });
    } else {
      isAutoPlaying = true;
      btns.forEach(b => { if(b) b.textContent = '⏸'; });
      autoPlayTimer = setInterval(() => {
        const next = currentIndex + 1;
        if (next >= allPhotos.length) {
          clearInterval(autoPlayTimer);
          autoPlayTimer = null;
          isAutoPlaying = false;
          btns.forEach(b => { if(b) b.textContent = '▶'; });
          return;
        }
        navigatePhoto(1);
      }, 3000);
    }
  };

  window.showPhotoInfo = async function() {
    if (currentIndex < 0) return;
    const p = allPhotos[currentIndex];
    infoPopup.style.display = 'block';
    infoContent.innerHTML = '<div>加载中...</div>';
    try {
      const resp = await fetch(`/api/photo/${photoId(p)}?path=${encodeURIComponent(p.path)}`);
      const data = await resp.json();
      const size = data.size ? (data.size / 1024 / 1024).toFixed(1) + ' MB' : '未知';
      const typeLabel = data.type === 'video' ? '🎬 视频' : '📷 照片';
      infoContent.innerHTML = `
        <div><b>文件名：</b>${escHtml(data.filename)}</div>
        <div><b>大小：</b>${size}</div>
        <div><b>类型：</b>${typeLabel}</div>
        <div><b>修改时间：</b>${data.mtime || '未知'}</div>
        <div><b>位置：</b>${currentIndex + 1} / ${allPhotos.length}</div>
      `;
    } catch(e) {
      infoContent.innerHTML = `<div>❌ ${e.message}</div>`;
    }
  };

  document.addEventListener('click', function(e) {
    if (infoPopup.style.display === 'block' && !infoPopup.contains(e.target) && !e.target.closest('.btn-info')) {
      infoPopup.style.display = 'none';
    }
  });

  window.refreshIndex = function() {
    if (currentAlbum) {
      currentPage = 1;
      allPhotos = [];
      photoGrid.innerHTML = '<div class=\"loading\">刷新中...</div>';
      loadPhotos();
    } else {
      loadAlbums();
    }
  };


  // ══════════════════════════════════════════
  //  初始化
  // ══════════════════════════════════════════

  loadAlbums();

})();
