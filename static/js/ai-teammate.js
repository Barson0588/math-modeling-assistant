// AI Teammate — floating panel with auto role-switching, proactive hints, voice input
// Now with drag-to-move, resize handle, welcome message, and preference persistence
(function() {
  const ROLE_CONFIG = {
    generator: { name: '建模手', icon: '📐' },
    paper: { name: '写作手', icon: '✍️' },
    models: { name: '建模手', icon: '📐' },
    problems: { name: '建模手', icon: '📐' },
    guide: { name: '教练', icon: '🎯' },
    roles: { name: '教练', icon: '🎯' },
  };

  const WELCOME_SHOWN_KEY = 'mma-teammate-welcome';
  const PANEL_PREF_KEY = 'mma-teammate-prefs';

  let currentRole = 'generator';
  let panelOpen = false;
  let unreadCount = 0;
  let isMobile = window.innerWidth <= 768;

  const btn = document.getElementById('teammate-btn');
  const panel = document.getElementById('teammate-panel');
  const messagesEl = document.getElementById('teammate-messages');
  const inputEl = document.getElementById('teammate-input');
  const badge = document.getElementById('teammate-badge');
  const roleIcon = document.getElementById('teammate-role-icon');
  const roleName = document.getElementById('teammate-role-name');
  const headerEl = panel ? panel.querySelector('.teammate-header') : null;

  // ---- Drag state ----
  let dragging = false, dragStartX = 0, dragStartY = 0, panelStartX = 0, panelStartY = 0;

  // ---- Resize state ----
  let resizing = false, resizeStartX = 0, resizeStartY = 0, panelStartW = 0, panelStartH = 0;

  function updateRole(tabName) {
    const config = ROLE_CONFIG[tabName] || ROLE_CONFIG.generator;
    currentRole = tabName;
    if (roleIcon) roleIcon.textContent = config.icon;
    if (roleName) roleName.textContent = config.name;
    if (btn) btn.querySelector('.teammate-avatar').textContent = config.icon;

    // On tab switch, auto-fetch context hint
    const problemType = document.getElementById('problem-type')?.value || '';
    const problemText = document.getElementById('problem')?.value || '';
    if (tabName === 'models' || tabName === 'paper' || tabName === 'generator') {
      fetchHint({ tab: tabName, problem_type: problemType, problem_text: problemText, last_action: 'tab_switch', idle_seconds: 0 });
    }
  }

  function addMessage(role, text, actions) {
    if (!text) return;
    const el = document.createElement('div');
    el.className = 'teammate-message role-' + (role === 'user' ? 'user' : 'teammate');
    el.innerHTML = '<div class="msg-text">' + text + '</div>';
    if (actions && actions.length) {
      el.innerHTML += '<div class="msg-actions">' + actions.map(function(a) {
        return '<button class="msg-btn" data-payload="' + (a.payload || '') + '">' + (a.label || '') + '</button>';
      }).join('') + '</div>';

      // Add click handlers for action buttons
      setTimeout(function() {
        el.querySelectorAll('.msg-btn').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var payload = this.dataset.payload;
            handleAction(payload);
          });
        });
      }, 50);
    }
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    if (!panelOpen && role !== 'user') {
      unreadCount++;
      if (badge) { badge.textContent = unreadCount; badge.hidden = false; }
    }

    return el;
  }

  function showWelcome() {
    var shown = sessionStorage.getItem(WELCOME_SHOWN_KEY);
    if (shown) return;
    sessionStorage.setItem(WELCOME_SHOWN_KEY, '1');

    var config = ROLE_CONFIG[currentRole] || ROLE_CONFIG.generator;
    addMessage('teammate',
      '👋 你好！我是你的 <b>AI 竞赛队友</b>，会根据当前页面自动切换角色：<br><br>' +
      '📐 <b>建模手</b> — 在 Generator / Models 页面出现，帮你分析题目、推荐模型<br>' +
      '✍️ <b>写作手</b> — 在 Paper 页面出现，帮你优化论文结构、精修摘要<br>' +
      '🎯 <b>教练</b> — 在 Guide / Roles 页面出现，帮团队规划时间、检查进度<br><br>' +
      '💡 <b>小技巧：</b>拖动标题栏可以移动面板，拖拽左下角可以调整大小，双击标题恢复默认。直接问我问题，我会调用 AI 帮你解答！',
      [{ label: '知道了', payload: 'dismiss_welcome' }]
    );
  }

  function open() {
    panel.hidden = false;
    panelOpen = true;
    unreadCount = 0;
    badge.hidden = true;
    loadPanelPrefs();
    showWelcome();
    setTimeout(function() { if (inputEl) inputEl.focus(); }, 300);
  }

  function close() {
    panel.hidden = true;
    panelOpen = false;
  }

  function handleAction(payload) {
    if (!payload) return;
    if (payload === 'dismiss_welcome') return;
    switch(payload) {
      case 'recommend_continuous':
      case 'recommend_discrete':
      case 'recommend_data':
      case 'recommend_evaluation':
      case 'recommend_network':
      case 'recommend_policy':
        document.querySelector('[data-tab="models"]')?.click();
        break;
      case 'open_paper_tab':
        document.querySelector('[data-tab="paper"]')?.click();
        break;
      case 'generate_full_paper':
        document.querySelector('[data-tab="paper"]')?.click();
        setTimeout(function() {
          var paperBtn = document.getElementById('paper-generate-btn');
          if (paperBtn) paperBtn.click();
        }, 500);
        break;
      case 'analyze_problem':
        addMessage('user', '帮我分析一下这个题目');
        break;
      case 'filter_recommended':
        if (typeof filterModels === 'function') {
          addMessage('teammate', '已为你筛选推荐模型', []);
        }
        break;
    }
  }

  async function fetchHint(context) {
    try {
      var res = await fetch('/api/context-hint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(context),
      });
      var data = await res.json();
      if (data.hint_text) addMessage('teammate', data.hint_text, data.actions);
    } catch(e) {}
  }

  // ---- Drag to move ----
  function initDrag() {
    if (!headerEl || isMobile) return;
    headerEl.style.cursor = 'grab';
    headerEl.addEventListener('mousedown', onDragStart);
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
    // Touch support
    headerEl.addEventListener('touchstart', onDragStart, { passive: false });
    document.addEventListener('touchmove', onDragMove, { passive: false });
    document.addEventListener('touchend', onDragEnd);
    // Double-click to reset
    headerEl.addEventListener('dblclick', resetPanelPosition);
  }

  function onDragStart(e) {
    if (e.target.tagName === 'BUTTON') return; // Don't drag on close button
    dragging = true;
    var clientX = e.touches ? e.touches[0].clientX : e.clientX;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    dragStartX = clientX;
    dragStartY = clientY;
    panelStartX = panel.offsetLeft;
    panelStartY = panel.offsetTop;
    panel.style.transition = 'none';
    headerEl.style.cursor = 'grabbing';
    if (e.preventDefault) e.preventDefault();
  }

  function onDragMove(e) {
    if (!dragging) return;
    var clientX = e.touches ? e.touches[0].clientX : e.clientX;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    var dx = clientX - dragStartX;
    var dy = clientY - dragStartY;
    var newLeft = panelStartX + dx;
    var newTop = panelStartY + dy;

    // Clamp to viewport
    var maxLeft = window.innerWidth - panel.offsetWidth - 8;
    var maxTop = window.innerHeight - panel.offsetHeight - 8;
    newLeft = Math.max(8, Math.min(newLeft, maxLeft));
    newTop = Math.max(8, Math.min(newTop, maxTop));

    panel.style.left = newLeft + 'px';
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.top = newTop + 'px';
  }

  function onDragEnd() {
    if (!dragging) return;
    dragging = false;
    panel.style.transition = '';
    if (headerEl) headerEl.style.cursor = 'grab';
    savePanelPrefs();
  }

  function resetPanelPosition() {
    panel.style.left = '';
    panel.style.right = '24px';
    panel.style.bottom = '92px';
    panel.style.top = '';
    panel.style.width = '';
    panel.style.height = '';
    panel.style.maxHeight = '';
    localStorage.removeItem(PANEL_PREF_KEY);
    if (headerEl) headerEl.style.cursor = 'grab';
  }

  // ---- Resize handle ----
  function initResize() {
    if (isMobile) return;
    // Create resize handle
    var handle = document.createElement('div');
    handle.className = 'teammate-resize-handle';
    handle.title = '拖拽调整大小';
    handle.innerHTML = '↘';
    panel.appendChild(handle);

    handle.addEventListener('mousedown', onResizeStart);
    document.addEventListener('mousemove', onResizeMove);
    document.addEventListener('mouseup', onResizeEnd);
    handle.addEventListener('touchstart', onResizeStart, { passive: false });
    document.addEventListener('touchmove', onResizeMove, { passive: false });
    document.addEventListener('touchend', onResizeEnd);
  }

  function onResizeStart(e) {
    resizing = true;
    var clientX = e.touches ? e.touches[0].clientX : e.clientX;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    resizeStartX = clientX;
    resizeStartY = clientY;
    panelStartW = panel.offsetWidth;
    panelStartH = panel.offsetHeight;
    panel.style.transition = 'none';
    if (e.preventDefault) e.preventDefault();
    e.stopPropagation();
  }

  function onResizeMove(e) {
    if (!resizing) return;
    var clientX = e.touches ? e.touches[0].clientX : e.clientX;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    var dw = clientX - resizeStartX;
    var dh = clientY - resizeStartY;
    var newW = Math.max(280, Math.min(600, panelStartW + dw));
    var newH = Math.max(300, Math.min(window.innerHeight * 0.8, panelStartH + dh));
    panel.style.width = newW + 'px';
    panel.style.height = newH + 'px';
    panel.style.maxHeight = 'none';
  }

  function onResizeEnd() {
    if (!resizing) return;
    resizing = false;
    panel.style.transition = '';
    savePanelPrefs();
  }

  // ---- Persistence ----
  function savePanelPrefs() {
    if (isMobile) return;
    var prefs = {
      left: panel.style.left || '',
      right: panel.style.right || '',
      top: panel.style.top || '',
      bottom: panel.style.bottom || '',
      width: panel.style.width || '',
      height: panel.style.height || '',
    };
    // Only save if user actually moved/resized
    if (!prefs.left && !prefs.top && !prefs.width) return;
    localStorage.setItem(PANEL_PREF_KEY, JSON.stringify(prefs));
  }

  function loadPanelPrefs() {
    if (isMobile) return;
    try {
      var raw = localStorage.getItem(PANEL_PREF_KEY);
      if (!raw) return;
      var prefs = JSON.parse(raw);
      if (prefs.left) { panel.style.left = prefs.left; panel.style.right = 'auto'; }
      if (prefs.top) { panel.style.top = prefs.top; panel.style.bottom = 'auto'; }
      if (prefs.width) { panel.style.width = prefs.width; panel.style.maxHeight = 'none'; }
      if (prefs.height) { panel.style.height = prefs.height; panel.style.maxHeight = 'none'; }
    } catch(e) {}
  }

  // Button handlers
  btn.addEventListener('click', function() { panelOpen ? close() : open(); });
  document.getElementById('teammate-close').addEventListener('click', function(e) { e.stopPropagation(); close(); });

  // Scroll detection
  var scrollTimer;
  window.addEventListener('scroll', function() {
    btn.classList.add('scrolling');
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(function() { btn.classList.remove('scrolling'); }, 200);
  }, { passive: true });

  // Send message via LLM
  async function sendMessage() {
    var text = inputEl.value.trim();
    if (!text) return;
    addMessage('user', text);
    inputEl.value = '';

    try {
      var res = await fetch('/api/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section_title: '用户提问', section_content: text }),
      });
      var data = await res.json();
      if (data.content) {
        addMessage('teammate', data.content, []);
      } else {
        addMessage('teammate', '抱歉，生成失败：' + (data.error || '未知错误'), []);
      }
    } catch(e) {
      addMessage('teammate', '网络错误，请检查连接后重试', []);
    }
  }

  document.getElementById('teammate-send').addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') sendMessage();
  });

  // ---- Voice Input (mobile only) ----
  var micBtn = document.getElementById('teammate-mic-btn');
  if (isMobile && micBtn) micBtn.hidden = false;

  var recognition = null;
  if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'zh-CN';

    var silenceTimer;
    recognition.onresult = function(e) {
      var transcript = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        transcript += e.results[i][0].transcript;
      }
      inputEl.value = transcript;
      clearTimeout(silenceTimer);
      silenceTimer = setTimeout(function() {
        if (transcript.trim()) sendMessage();
        recognition.stop();
        if (micBtn) micBtn.classList.remove('recording');
      }, 2000);
    };
    recognition.onerror = function() {
      if (micBtn) { micBtn.classList.remove('recording'); micBtn.disabled = true; micBtn.title = '麦克风权限未开放'; }
    };
    recognition.onend = function() {
      if (micBtn) micBtn.classList.remove('recording');
    };
  }

  if (micBtn) {
    micBtn.addEventListener('click', function() {
      if (!recognition) return;
      if (micBtn.classList.contains('recording')) {
        recognition.stop();
        micBtn.classList.remove('recording');
      } else {
        try {
          recognition.start();
          micBtn.classList.add('recording');
        } catch(e) {}
      }
    });
  }

  // ---- Init drag & resize ----
  setTimeout(function() {
    initDrag();
    initResize();
  }, 500);

  // Resize handler
  window.addEventListener('resize', function() {
    isMobile = window.innerWidth <= 768;
    if (micBtn) micBtn.hidden = !isMobile;
  });

  // Expose global API
  window.Teammate = {
    updateRole: updateRole,
    addMessage: addMessage,
    fetchHint: fetchHint,
    open: open,
    close: close,
    handleAction: handleAction,
  };

  // ---- Hook into tab switching ----
  document.querySelectorAll('.nav-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var tabName = btn.dataset.tab;
      updateRole(tabName);
    });
  });

  document.querySelectorAll('.bottom-nav-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var tabName = btn.dataset.tab;
      updateRole(tabName);
    });
  });

  // ---- Hook into generation lifecycle ----
  var genObserver = new MutationObserver(function(mutations) {
    mutations.forEach(function(m) {
      if (m.target.id === 'result-content' && m.target.children.length > 50) {
        setTimeout(function() {
          fetchHint({
            tab: 'generator',
            last_action: 'generation_complete',
            problem_type: document.getElementById('problem-type')?.value || '',
            problem_text: document.getElementById('problem')?.value || '',
            idle_seconds: 0,
          });
        }, 1000);
        genObserver.disconnect();
        setTimeout(function() {
          var rc = document.getElementById('result-content');
          if (rc) genObserver.observe(rc, { childList: true, subtree: false });
        }, 5000);
      }
    });
  });

  setTimeout(function() {
    var rc = document.getElementById('result-content');
    if (rc) genObserver.observe(rc, { childList: true, subtree: false });
  }, 1000);

  // Show welcome message on first visit
  setTimeout(function() {
    var shown = sessionStorage.getItem('mma-teammate-welcome');
    if (!shown && messagesEl && messagesEl.children.length === 0) {
      var tab = 'generator';
      var activeTab = document.querySelector('.tab.active');
      if (activeTab) {
        var tabId = activeTab.id.replace('tab-', '');
        if (ROLE_CONFIG[tabId]) tab = tabId;
      }
      updateRole(tab);
      fetchHint({
        tab: tab,
        last_action: 'problem_filled',
        problem_type: document.getElementById('problem-type')?.value || '',
        problem_text: document.getElementById('problem')?.value || '',
        idle_seconds: 0,
      }).then(function() {
        sessionStorage.setItem('mma-teammate-welcome', '1');
      });
    }
  }, 1500);
})();
