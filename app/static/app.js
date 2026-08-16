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
      photoGrid.innerHTML = '<div class="loading">刷新中...</div>';
      loadPhotos();
    } else {
      loadAlbums();
    }
  };

  // ══════════════════════════════════════════
  //  缩略图进度总览（照片/视频分开）
  // ══════════════════════════════════════════

  let thumbSummaryTimer = null;
  let thumbSummaryHidden = false;   // 已完成态5秒后隐藏的标记

  // 用户手动关闭后，本次会话（浏览器标签页生命周期内）不再自动弹出
  window.dismissThumbProgress = function() {
    const bar = document.getElementById('thumbProgressBar');
    if (bar) {
      bar.style.display = 'none';
      document.body.classList.remove('progress-visible');
    }
    try { sessionStorage.setItem('thumbProgressDismissed', '1'); } catch(e) {}
  };

  function thumbProgressDismissed() {
    try { return sessionStorage.getItem('thumbProgressDismissed') === '1'; } catch(e) { return false; }
  }

  function fmtCount(n) {
    if (n >= 10000) return (n / 10000).toFixed(1) + '万';
    return String(n);
  }

  async function pollThumbSummary(showOnce) {
    const bar = document.getElementById('thumbProgressBar');
    if (!bar) return;
    try {
      const r = await fetch('/api/thumb_summary');
      const d = await r.json();
      if (d.error) { setTimeout(pollThumbSummary, 30000); return; }

      const ph = d.photo || {total: 0, done: 0};
      const vd = d.video || {total: 0, done: 0};
      const running = !!d.running;

      const photoPct = ph.total > 0 ? Math.round(ph.done / ph.total * 100) : 100;
      const videoPct = vd.total > 0 ? Math.round(vd.done / vd.total * 100) : 100;
      const overallPct = (ph.total + vd.total) > 0
        ? Math.round((ph.done + vd.done) / (ph.total + vd.total) * 100) : 100;

      document.getElementById('thumbPhotoLine').textContent =
        `🖼 照片缩略图：${fmtCount(ph.done)} / ${fmtCount(ph.total)} 张（${photoPct}%）`;
      document.getElementById('thumbVideoLine').textContent =
        `🎬 视频缩略图：${fmtCount(vd.done)} / ${fmtCount(vd.total)} 个（${videoPct}%）`;
      document.getElementById('thumbProgressFill').style.width = overallPct + '%';

      const allDone = (ph.total > 0 && ph.done >= ph.total) && (vd.total > 0 && vd.done >= vd.total);

      if (thumbProgressDismissed()) {
        // 用户已手动关闭 → 保持隐藏，后台继续轮询（完成态变化也不弹）
        setTimeout(pollThumbSummary, 30000);
        return;
      }

      if (running || !allDone) {
        // 生成中 或 未完成 → 显示（固定展示直到完成）
        bar.style.display = 'block';
        document.body.classList.add('progress-visible');
        thumbSummaryHidden = false;
        setTimeout(pollThumbSummary, 30000);
      } else if (allDone && !thumbSummaryHidden) {
        // 刚完成 → 显示完成态 5 秒后隐藏
        bar.style.display = 'block';
        document.body.classList.add('progress-visible');
        thumbSummaryHidden = true;
        setTimeout(() => { bar.style.display = 'none'; document.body.classList.remove('progress-visible'); }, 5000);
      } else {
        // 已完成且已隐藏 → 静默
        bar.style.display = 'none';
        document.body.classList.remove('progress-visible');
        setTimeout(pollThumbSummary, 30000);
      }
    } catch(e) {
      setTimeout(pollThumbSummary, 30000);
    }
  }

  // ══════════════════════════════════════════
  //  管理菜单（⚙）
  // ══════════════════════════════════════════

  window.toggleManageMenu = function(e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById('manageMenu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
  };

  document.addEventListener('click', function(e) {
    const menu = document.getElementById('manageMenu');
    if (menu && menu.style.display === 'block' && !e.target.closest('.manage-wrap')) {
      menu.style.display = 'none';
    }
  });

  window.openManageModal = function(title, bodyHtml) {
    document.getElementById('manageModalTitle').textContent = title || '📁 管理相册目录';
    document.getElementById('manageModalBody').innerHTML = bodyHtml || '<div id="prContent"><div style="color:#7f8c8d">加载中...</div></div>';
    document.getElementById('manageModal').style.display = 'flex';
    document.getElementById('manageMenu').style.display = 'none';
  };

  window.closeManageModal = function() {
    document.getElementById('manageModal').style.display = 'none';
  };

  // ══════════════════════════════════════════
  //  相册目录管理（完整版，移植自管理面板 prModal）
  // ══════════════════════════════════════════

  let prDiscovered = [];

  async function apiPR(action, payload) {
    const method = (action === 'add' || action === 'remove') ? 'POST' : 'GET';
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (method === 'POST') opts.body = JSON.stringify(payload || {});
    const r = await fetch(`/api/photo_roots${action === 'list' ? '' : '/' + action}`, opts);
    return r.json();
  }

  window.manageAction = async function(action) {
    document.getElementById('manageMenu').style.display = 'none';

    if (action === 'roots') {
      // 完整相册目录管理（移植自管理面板 prModal）
      openManageModal('📁 管理相册目录', '<div id="prContent"><div style="color:#7f8c8d">加载中...</div></div>');
      loadPhotoRoots();
    } else if (action === 'trigger') {
      openManageModal('🖼 生成缺失缩略图', '<div class="manage-status">正在启动...</div>');
      const body = document.getElementById('manageModalBody');
      try {
        const r = await fetch('/api/thumb/trigger', {method: 'POST'});
        const d = await r.json();
        if (r.status === 409) {
          body.innerHTML = `<div class="manage-status err">⚠ ${d.message || '任务进行中'}</div>`;
        } else {
          body.innerHTML = `<div class="manage-status ok">✅ ${d.message || '已开始生成'}，进度见顶部进度条</div>`;
          pollThumbSummary(true);
        }
      } catch(e) {
        body.innerHTML = `<div class="manage-status err">❌ ${e.message}</div>`;
      }
    }
  };

  // 加载相册目录（历史全量 + 三区展示，移植自管理面板）
  window.loadPhotoRoots = async function() {
    const c = document.getElementById('prContent');
    if (!c) return;
    try {
      let data;
      try { data = await apiPR('history'); }
      catch(e) { data = {error: e.message}; }
      if (data.error || !data.history) {
        const l = await apiPR('list');
        if (l.error) { c.innerHTML = `<div style="color:#e74c3c">❌ ${l.error}</div>`; return; }
        data = { history: (l.roots||[]).map(r => ({path:r.path, active:true, exists:r.exists, name:r.name})) };
      }
      const hist = data.history || [];
      const activeEx = hist.filter(h => h.active && h.exists);
      const activeBad = hist.filter(h => h.active && !h.exists);
      const inactive = hist.filter(h => !h.active);

      const renderRow = (h, extraBtn, border, color) => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 12px;border:1px solid ${border};border-radius:8px;margin-bottom:5px;background:#16213e">
          <div style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(h.path)}">
            <span>${color}</span> <span>${escHtml(h.path)}</span>
            ${h.exists ? '' : '<span style="font-size:11px;color:#e74c3c"> (路径不存在)</span>'}
          </div>
          ${extraBtn}
        </div>`;

      const activeExRows = activeEx.map(h => renderRow(h,
        `<button class="manage-btn manage-btn-danger" onclick="removePhotoRoot('${h.path.replace(/'/g,"\\'")}')" style="margin-left:10px">停用</button>`, '#27ae60', '🟢')).join('');
      const activeBadRows = activeBad.map(h => renderRow(h,
        `<button class="manage-btn manage-btn-danger" onclick="removePhotoRoot('${h.path.replace(/'/g,"\\'")}')" style="margin-left:10px">停用</button>`, '#e74c3c', '🔴')).join('');
      const inactiveRows = inactive.map(h => renderRow(h,
        `<button class="manage-btn" onclick="reactivatePhotoRoot('${h.path.replace(/'/g,"\\'")}')" style="margin-left:10px">🔄 重新启用</button>`, '#5d6d7e', '🗑️')).join('');

      c.innerHTML = `
        <div style="margin-bottom:10px">
          <div style="font-size:13px;color:#2ecc71;margin-bottom:5px">✅ 当前有效相册 (${activeEx.length})</div>
          ${activeExRows || '<div style="color:#7f8c8d;font-size:12px">无</div>'}
        </div>
        <div style="margin-bottom:10px">
          <div style="font-size:13px;color:#f39c12;margin-bottom:5px">⚠️ 已配置但路径失效 (${activeBad.length})</div>
          ${activeBadRows || '<div style="color:#7f8c8d;font-size:12px">无</div>'}
        </div>
        <div style="margin-bottom:14px">
          <div style="font-size:13px;color:#95a5a6;margin-bottom:5px">🗑️ 曾配置/已停用（可重新启用）(${inactive.length})</div>
          ${inactiveRows || '<div style="color:#7f8c8d;font-size:12px">无</div>'}
        </div>
        <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
          <button class="manage-btn manage-btn-primary" onclick="scanPhotoRoots()">🔍 扫描发现相册目录</button>
          <button class="manage-btn" onclick="refreshPhotoRoots()">🔄 重新扫描相册</button>
        </div>
        <div style="margin-bottom:14px;padding:12px;border:1px dashed #2c3e50;border-radius:8px">
          <div style="font-size:13px;color:#95a5a6;margin-bottom:6px">✍️ 手工添加相册路径（在设备上查看目录后直接填）</div>
          <div style="display:flex;gap:8px">
            <input type="text" id="prManualPath" placeholder="例如 /media/devmon/SNAKE2/xxx 或 D:\\xxx" style="flex:1;background:#0f3460;color:#e0e0e0;border:1px solid #2c3e50;border-radius:6px;padding:8px;font-size:13px">
            <button class="manage-btn manage-btn-primary" onclick="addManualPhotoRoot()">➕ 添加</button>
          </div>
        </div>
        <div id="prScanArea"></div>
        <div id="prMsg" style="font-size:12px;margin-top:8px"></div>`;
    } catch(e) {
      c.innerHTML = `<div style="color:#e74c3c">❌ 加载失败: ${e.message}</div>`;
    }
  };

  window.reactivatePhotoRoot = async function(path) {
    const msg = document.getElementById('prMsg');
    if (!msg) return;
    msg.innerHTML = '⏳ 重新启用中...';
    try {
      const data = await apiPR('add', { paths: [path] });
      if (data.error) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${data.error}</span>`; return; }
      msg.innerHTML = `<span style="color:#2ecc71">✅ 已重新启用，相册总数 ${data.albums}</span>`;
      loadPhotoRoots();
    } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }
  };

  window.scanPhotoRoots = async function() {
    const area = document.getElementById('prScanArea');
    const msg = document.getElementById('prMsg');
    if (!area) return;
    area.innerHTML = '<div style="color:#7f8c8d">扫描中...</div>';
    msg.innerHTML = '';
    try {
      const data = await apiPR('scan');
      prDiscovered = data.discovered || [];
      if (!prDiscovered.length) { area.innerHTML = '<div style="color:#7f8c8d;font-size:12px">未发现新的可用相册目录</div>'; return; }
      const checks = prDiscovered.map((d,i) => `
        <div style="display:flex;align-items:center;padding:7px 10px;border:1px solid #2c3e50;border-radius:8px;margin-bottom:5px;background:#16213e">
          <input type="checkbox" id="prc_${i}" ${d.is_current?'checked disabled':''} style="width:auto;margin:0 8px 0 0">
          <div style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${d.path}">${d.path}</div>
          ${d.is_current?'<span style="font-size:11px;color:#2ecc71">已配置</span>':''}
        </div>`).join('');
      area.innerHTML = `
        <div style="font-size:13px;color:#95a5a6;margin-bottom:6px">🗂 发现 ${prDiscovered.length} 个可用相册目录（勾选后添加）</div>
        ${checks}
        <button class="manage-btn manage-btn-primary" onclick="addSelectedPhotoRoots()" style="margin-top:8px">✅ 添加选中目录</button>`;
    } catch(e) {
      area.innerHTML = `<div style="color:#e74c3c">❌ 扫描失败: ${e.message}</div>`;
    }
  };

  window.addSelectedPhotoRoots = async function() {
    const paths = [];
    prDiscovered.forEach((d,i) => { const cb = document.getElementById('prc_'+i); if (cb && cb.checked) paths.push(d.path); });
    const msg = document.getElementById('prMsg');
    if (!paths.length) { msg.innerHTML = '<span style="color:#f39c12">请先勾选要添加的目录</span>'; return; }
    msg.innerHTML = '⏳ 添加中...';
    try {
      const data = await apiPR('add', { paths });
      msg.innerHTML = `<span style="color:#2ecc71">✅ 已添加 ${(data.added||[]).length} 个目录，相册总数 ${data.albums}</span>`;
      loadPhotoRoots();
    } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }
  };

  window.removePhotoRoot = async function(path) {
    if (!confirm('确认停用相册根目录（将保留在历史，可重新启用）：\n' + path)) return;
    const msg = document.getElementById('prMsg');
    msg.innerHTML = '⏳ 停用中...';
    try {
      const data = await apiPR('remove', { path });
      msg.innerHTML = `<span style="color:#2ecc71">✅ 已停用，相册总数 ${data.albums}</span>`;
      loadPhotoRoots();
    } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }
  };

  window.refreshPhotoRoots = async function() {
    const msg = document.getElementById('prMsg');
    msg.innerHTML = '⏳ 重新扫描中...';
    try {
      const data = await apiPR('refresh');
      msg.innerHTML = `<span style="color:#2ecc71">✅ 重新扫描完成，相册总数 ${data.albums}</span>`;
      loadAlbums();
    } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }
  };

  window.addManualPhotoRoot = async function() {
    const input = document.getElementById('prManualPath');
    const msg = document.getElementById('prMsg');
    const path = (input.value || '').trim();
    if (!path) { msg.innerHTML = '<span style="color:#f39c12">请输入相册路径</span>'; return; }
    msg.innerHTML = '⏳ 添加中...';
    try {
      const data = await apiPR('add', { paths: [path] });
      if (data.error) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${data.error}</span>`; return; }
      msg.innerHTML = `<span style="color:#2ecc71">✅ 已添加，相册总数 ${data.albums}</span>`;
      input.value = '';
      loadPhotoRoots();
    } catch(e) { msg.innerHTML = `<span style="color:#e74c3c">❌ ${e.message}</span>`; }
  };


  // ══════════════════════════════════════════
  //  初始化
  // ══════════════════════════════════════════

  loadAlbums();
  pollThumbSummary(true);

})();
