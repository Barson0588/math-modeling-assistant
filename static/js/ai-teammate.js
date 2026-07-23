// AI Teammate — transparent glass-bubble chat overlay
// Collapse/expand, drag+reset, per-role chat histories
(function() {
  const ROLE_CONFIG = {
    generator: { name: '建模手', persona: 'architect', cssClass: 'avatar-architect' },
    paper: { name: '写作手', persona: 'writer', cssClass: 'avatar-writer' },
    models: { name: '建模手', persona: 'architect', cssClass: 'avatar-architect' },
    problems: { name: '建模手', persona: 'architect', cssClass: 'avatar-architect' },
    guide: { name: '教练', persona: 'coach', cssClass: 'avatar-coach' },
    roles: { name: '教练', persona: 'coach', cssClass: 'avatar-coach' },
  };

  function getRoleAvatarHtml(persona) {
    var cssClass = 'avatar-architect';
    if (persona === 'writer') cssClass = 'avatar-writer';
    else if (persona === 'coach') cssClass = 'avatar-coach';
    return '<div class="teammate-avatar-icon ' + cssClass + '"></div>';
  }

  const WELCOME_SHOWN_KEY = 'mma-teammate-welcome';
  const PANEL_PREF_KEY = 'mma-teammate-prefs';
  const CHAT_HISTORY_KEY = 'mma-teammate-chats';

  // Default panel position
  const DEFAULT_TOP = 80;
  const DEFAULT_RIGHT = 24;
  const DEFAULT_WIDTH = 360;
  const DEFAULT_HEIGHT = 520;

  let currentRole = 'generator';
  let panelState = 'hidden'; // 'open' | 'collapsed' | 'hidden'
  let unreadCount = 0;
  let isMobile = window.innerWidth <= 768;

  const btn = document.getElementById('teammate-btn');
  const panel = document.getElementById('teammate-panel');
  const messagesEl = document.getElementById('teammate-messages');
  const inputEl = document.getElementById('teammate-input');
  const badge = document.getElementById('teammate-badge');
  const dragBar = document.getElementById('teammate-drag-bar');
  const collapseBar = document.getElementById('teammate-collapse-bar');

  // ---- Drag state ----
  let dragging = false, dragStartX = 0, dragStartY = 0, panelStartX = 0, panelStartY = 0;

  // ---- Resize state ----
  let resizing = false, resizeStartX = 0, resizeStartY = 0, panelStartW = 0, panelStartH = 0;

  // ---- Rate limiting ----
  const HINT_COOLDOWN_MS = 60000;
  let lastHintTime = 0;
  let lastHintFingerprint = '';

  function maybeAutoHint(context) {
    var now = Date.now();
    if (now - lastHintTime < HINT_COOLDOWN_MS) return;
    fetchHint(context);
  }

  // ---- Typing indicator ----
  let typingEl = null;

  // ---- Per-role message storage ----
  function loadChatHistory() {
    try {
      return JSON.parse(localStorage.getItem(CHAT_HISTORY_KEY) || '{}');
    } catch(e) { return {}; }
  }

  function saveChatHistory(history) {
    try {
      // Keep only last 50 messages per role to avoid localStorage bloat
      var trimmed = {};
      Object.keys(history).forEach(function(role) {
        trimmed[role] = history[role].slice(-50);
      });
      localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(trimmed));
    } catch(e) {}
  }

  function getRoleMessages(role) {
    var history = loadChatHistory();
    return history[role] || [];
  }

  function setRoleMessages(role, msgs) {
    var history = loadChatHistory();
    history[role] = msgs;
    saveChatHistory(history);
  }

  // Debounced persistence — avoids blocking main thread on every message
  var _saveTimer = null;
  function _scheduleSave() {
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(function() { saveCurrentMessages(); _saveTimer = null; }, 2000);
  }

  // Save current DOM messages to role storage
  function saveCurrentMessages() {
    var msgs = [];
    messagesEl.querySelectorAll('.teammate-message').forEach(function(el) {
      var isUser = el.classList.contains('role-user');
      var textEl = el.querySelector('.msg-text');
      var text = textEl ? textEl.innerText : '';
      if (text.trim()) {
        msgs.push({ role: isUser ? 'user' : 'teammate', text: text });
      }
    });
    setRoleMessages(currentRole, msgs);
  }

  // Restore messages for the current role from storage
  function restoreMessages(role) {
    messagesEl.innerHTML = '';
    var msgs = getRoleMessages(role);
    // If first time for this role, show welcome
    if (msgs.length === 0) {
      showWelcome();
      return;
    }
    msgs.forEach(function(m) {
      renderMessage(m.role, m.text, []);
    });
    messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'instant' });
  }

  // Render a message without triggering save (used during restore)
  function renderMessage(role, text, actions) {
    if (!text) return;
    var config = ROLE_CONFIG[currentRole] || ROLE_CONFIG.generator;
    var el = document.createElement('div');
    el.className = 'teammate-message role-' + (role === 'user' ? 'user' : 'teammate');

    if (role === 'teammate') {
      try {
        var rendered = typeof marked !== 'undefined' ? marked.parse(text) : text;
        el.innerHTML = '<div class="msg-avatar-row">' + getRoleAvatarHtml(config.persona) + '<div class="msg-text">' + rendered + '</div></div>';
      } catch(e) {
        el.innerHTML = '<div class="msg-avatar-row">' + getRoleAvatarHtml(config.persona) + '<div class="msg-text">' + text + '</div></div>';
      }
    } else {
      el.innerHTML = '<div class="msg-text">' + text + '</div>';
    }

    if (actions && actions.length) {
      el.innerHTML += '<div class="msg-actions">' + actions.map(function(a) {
        return '<button class="msg-btn" data-payload="' + (a.payload || '') + '">' + (a.label || '') + '</button>';
      }).join('') + '</div>';
      setTimeout(function() {
        el.querySelectorAll('.msg-btn').forEach(function(b) {
          b.addEventListener('click', function() { handleAction(this.dataset.payload); });
        });
      }, 50);
    }

    messagesEl.appendChild(el);
  }

  function addMessage(role, text, actions) {
    if (!text) return;
    renderMessage(role, text, actions);
    messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });

    if (panelState !== 'open' && role !== 'user') {
      unreadCount++;
      if (badge) { badge.textContent = unreadCount; badge.hidden = false; }
    }

    // Persist to localStorage (debounced 2s)
    _scheduleSave();
  }

  // ---- Typing indicator ----
  function showTyping() {
    if (typingEl) return;
    typingEl = document.createElement('div');
    typingEl.className = 'teammate-message role-teammate typing-indicator';
    var config = ROLE_CONFIG[currentRole] || ROLE_CONFIG.generator;
    typingEl.innerHTML = '<div class="msg-avatar-row">' + getRoleAvatarHtml(config.persona) + '<div class="typing-dots"><span></span><span></span><span></span></div></div>';
    messagesEl.appendChild(typingEl);
    messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
  }

  function hideTyping() {
    if (typingEl) {
      typingEl.classList.add('typing-done');
      setTimeout(function() {
        if (typingEl) { typingEl.remove(); typingEl = null; }
      }, 150);
    }
  }

  function showWelcome() {
    var shown = sessionStorage.getItem(WELCOME_SHOWN_KEY);
    if (shown) return;
    sessionStorage.setItem(WELCOME_SHOWN_KEY, '1');

    addMessage('teammate',
      '你好，我是你的 **AI 竞赛队友**，会根据当前页面自动切换角色：\n\n' +
      '📐 **建模手** — Generator / Models 页面，分析题目、推荐模型\n' +
      '✍️ **写作手** — Paper 页面，优化论文结构、精修摘要\n' +
      '🎯 **教练** — Guide / Roles 页面，规划时间、检查进度\n\n' +
      '💡 拖拽顶部横条移动面板，双击横条恢复默认位置，点 − 收起面板。',
      [{ label: '知道了', payload: 'dismiss_welcome' }]
    );
  }

  // ---- Panel state management ----
  function expandPanel() {
    panel.classList.remove('collapsed');
    panel.hidden = false;
    panelState = 'open';
    unreadCount = 0;
    badge.hidden = true;
    loadPanelPrefs();
    restoreMessages(currentRole);
    // Show welcome if no messages after restore
    if (messagesEl.children.length === 0) showWelcome();
    setTimeout(function() { if (inputEl) inputEl.focus(); }, 300);
    updateCollapseBar();
  }

  function collapsePanel() {
    saveCurrentMessages();
    panel.classList.add('collapsed');
    panelState = 'collapsed';
    updateCollapseBar();
  }

  function hidePanel() {
    saveCurrentMessages();
    panel.hidden = true;
    panelState = 'hidden';
  }

  function togglePanel() {
    if (panelState === 'open') {
      collapsePanel();
    } else {
      expandPanel();
    }
  }

  function updateCollapseBar() {
    if (!collapseBar) return;
    var config = ROLE_CONFIG[currentRole] || ROLE_CONFIG.generator;
    collapseBar.innerHTML = getRoleAvatarHtml(config.persona) +
      '<span style="font-size:12px;font-weight:600;margin-left:8px;">' + config.name + '</span>' +
      '<span style="flex:1"></span>' +
      '<button class="teammate-expand-btn" title="展开" style="background:none;border:none;cursor:pointer;font-size:16px;color:var(--text-secondary);padding:4px;">+</button>';
  }

  // ---- Drag to move (rAF-throttled, handlers attached only while dragging) ----
  function initDrag() {
    if (!dragBar || isMobile) return;
    dragBar.style.cursor = 'grab';
    dragBar.addEventListener('mousedown', onDragStart);
    dragBar.addEventListener('touchstart', onDragStart, { passive: false });
    dragBar.addEventListener('dblclick', resetPanelPosition);
  }

  function onDragStart(e) {
    dragging = true;
    var clientX = e.touches ? e.touches[0].clientX : e.clientX;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    dragStartX = clientX;
    dragStartY = clientY;
    panelStartX = panel.offsetLeft;
    panelStartY = panel.offsetTop;
    panel.style.transition = 'none';
    dragBar.style.cursor = 'grabbing';
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
    document.addEventListener('touchmove', onDragMove, { passive: false });
    document.addEventListener('touchend', onDragEnd);
    if (e.preventDefault) e.preventDefault();
  }

  var _dragRaf = null;
  function onDragMove(e) {
    if (!dragging) return;
    if (_dragRaf) return;
    var clientX = e.touches ? e.touches[0].clientX : e.clientX;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    var dx = clientX - dragStartX;
    var dy = clientY - dragStartY;
    _dragRaf = requestAnimationFrame(function() {
      _dragRaf = null;
      var newLeft = panelStartX + dx;
      var newTop = panelStartY + dy;
      var maxLeft = window.innerWidth - panel.offsetWidth - 8;
      var maxTop = window.innerHeight - 80;
      newLeft = Math.max(8, Math.min(newLeft, maxLeft));
      newTop = Math.max(8, Math.min(newTop, maxTop));
      panel.style.left = newLeft + 'px';
      panel.style.right = 'auto';
      panel.style.top = newTop + 'px';
    });
    if (e.preventDefault) e.preventDefault();
  }

  function onDragEnd() {
    if (!dragging) return;
    dragging = false;
    _dragRaf = null;
    panel.style.transition = '';
    if (dragBar) dragBar.style.cursor = 'grab';
    document.removeEventListener('mousemove', onDragMove);
    document.removeEventListener('mouseup', onDragEnd);
    document.removeEventListener('touchmove', onDragMove);
    document.removeEventListener('touchend', onDragEnd);
    savePanelPrefs();
  }

  function resetPanelPosition() {
    panel.style.left = '';
    panel.style.right = DEFAULT_RIGHT + 'px';
    panel.style.top = DEFAULT_TOP + 'px';
    panel.style.width = '';
    panel.style.height = '';
    panel.style.maxHeight = '';
    localStorage.removeItem(PANEL_PREF_KEY);
    if (dragBar) dragBar.style.cursor = 'grab';
  }

  // ---- Resize handle (vertical-only, rAF-throttled) ----
  function initResize() {
    if (isMobile) return;
    var handle = document.createElement('div');
    handle.className = 'teammate-resize-handle';
    handle.title = '拖拽调整高度';
    panel.appendChild(handle);
    handle.addEventListener('mousedown', onResizeStart);
    handle.addEventListener('touchstart', onResizeStart, { passive: false });
  }

  function onResizeStart(e) {
    resizing = true;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    resizeStartY = clientY;
    panelStartH = panel.offsetHeight;
    panel.style.transition = 'none';
    document.addEventListener('mousemove', onResizeMove);
    document.addEventListener('mouseup', onResizeEnd);
    document.addEventListener('touchmove', onResizeMove, { passive: false });
    document.addEventListener('touchend', onResizeEnd);
    if (e.preventDefault) e.preventDefault();
    e.stopPropagation();
  }

  var _resizeRaf = null;
  function onResizeMove(e) {
    if (!resizing) return;
    if (_resizeRaf) return;
    var clientY = e.touches ? e.touches[0].clientY : e.clientY;
    var dh = resizeStartY - clientY; // drag up = taller
    _resizeRaf = requestAnimationFrame(function() {
      _resizeRaf = null;
      var newH = Math.max(300, Math.min(window.innerHeight * 0.85, panelStartH + dh));
      panel.style.height = newH + 'px';
      panel.style.maxHeight = 'none';
    });
  }

  function onResizeEnd() {
    if (!resizing) return;
    resizing = false;
    _resizeRaf = null;
    panel.style.transition = '';
    document.removeEventListener('mousemove', onResizeMove);
    document.removeEventListener('mouseup', onResizeEnd);
    document.removeEventListener('touchmove', onResizeMove);
    document.removeEventListener('touchend', onResizeEnd);
    savePanelPrefs();
  }

  // ---- Persistence ----
  function savePanelPrefs() {
    if (isMobile) return;
    var prefs = {
      left: panel.style.left || '',
      right: panel.style.right || '',
      top: panel.style.top || '',
      width: panel.style.width || '',
      height: panel.style.height || '',
    };
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
      if (prefs.top) { panel.style.top = prefs.top; }
      if (prefs.width) { panel.style.width = prefs.width; panel.style.maxHeight = 'none'; }
      if (prefs.height) { panel.style.height = prefs.height; panel.style.maxHeight = 'none'; }
    } catch(e) {}
  }

  // ---- Button handlers ----
  btn.addEventListener('click', function() {
    if (panelState === 'hidden' || panelState === 'collapsed') {
      expandPanel();
    } else {
      collapsePanel();
    }
  });

  // Collapse bar click → expand
  if (collapseBar) {
    collapseBar.addEventListener('click', function(e) {
      if (e.target.tagName === 'BUTTON') return;
      expandPanel();
    });
  }

  // Scroll detection
  var scrollTimer;
  window.addEventListener('scroll', function() {
    btn.classList.add('scrolling');
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(function() { btn.classList.remove('scrolling'); }, 200);
  }, { passive: true });

  // ---- Send message via LLM ----
  async function sendMessage() {
    var text = inputEl.value.trim();
    if (!text) return;
    addMessage('user', text);
    inputEl.value = '';
    inputEl.disabled = true;

    showTyping();

    try {
      var res = await fetch('/api/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section_title: '队友提问', section_content: text }),
      });
      var data = await res.json();
      hideTyping();
      if (data.content) {
        addMessage('teammate', data.content, []);
      } else {
        addMessage('teammate', '😅 抱歉，出错了：' + (data.error || '未知错误'), []);
      }
    } catch(e) {
      hideTyping();
      addMessage('teammate', '😅 网络好像不太行，稍等再试试？', []);
    }
    inputEl.disabled = false;
    inputEl.focus();
  }

  document.getElementById('teammate-send').addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
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

  // ---- Init ----
  setTimeout(function() {
    initDrag();
    initResize();
  }, 500);

  window.addEventListener('resize', function() {
    isMobile = window.innerWidth <= 768;
    if (micBtn) micBtn.hidden = !isMobile;
  });

  // ---- Role switching with history preservation ----
  function updateRole(tabName) {
    if (tabName === currentRole) return;
    // Save current messages to current role
    saveCurrentMessages();
    // Switch role
    var config = ROLE_CONFIG[tabName] || ROLE_CONFIG.generator;
    currentRole = tabName;
    if (btn) {
      var avatarEl = btn.querySelector('.teammate-avatar-icon');
      if (avatarEl) {
        avatarEl.className = 'teammate-avatar-icon ' + config.cssClass;
      }
    }
    updateCollapseBar();
    // Restore messages for new role if panel is open
    if (panelState === 'open') {
      restoreMessages(tabName);
    }

    var problemType = document.getElementById('problem-type')?.value || '';
    var problemText = document.getElementById('problem')?.value || '';
    // Only hint on tab switch when there's real content and the target tab can use it
    if (problemText.length > 20 && tabName !== 'generator') {
      maybeAutoHint({ tab: tabName, problem_type: problemType, problem_text: problemText, last_action: 'tab_switch', idle_seconds: 0 });
    }
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
    var now = Date.now();
    if (now - lastHintTime < HINT_COOLDOWN_MS) return;
    var fingerprint = JSON.stringify(context);
    if (fingerprint === lastHintFingerprint) return;
    lastHintTime = now;
    lastHintFingerprint = fingerprint;
    try {
      showTyping();
      var res = await fetch('/api/context-hint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(context),
      });
      var data = await res.json();
      hideTyping();
      if (data.hint_text) addMessage('teammate', data.hint_text, data.actions);
    } catch(e) { hideTyping(); }
  }

  // Expose global API
  window.Teammate = {
    updateRole: updateRole,
    addMessage: addMessage,
    fetchHint: fetchHint,
    expand: expandPanel,
    collapse: collapsePanel,
    toggle: togglePanel,
    handleAction: handleAction,
  };

  // ---- Hook into tab switching ----
  document.querySelectorAll('.nav-btn').forEach(function(b) {
    b.addEventListener('click', function() {
      updateRole(b.dataset.tab);
    });
  });

  document.querySelectorAll('.bottom-nav-btn').forEach(function(b) {
    b.addEventListener('click', function() {
      updateRole(b.dataset.tab);
    });
  });

  // ---- Hook into generation lifecycle (event-driven, no MutationObserver) ----
  window._teammateOnGenerationComplete = function(tab) {
    var problemText = document.getElementById('problem')?.value || '';
    // Don't hint if problem was cleared during generation
    if (problemText.length < 10) return;
    maybeAutoHint({
      tab: tab || 'generator',
      last_action: 'generation_complete',
      problem_type: document.getElementById('problem-type')?.value || '',
      problem_text: problemText,
      idle_seconds: 0,
    });
  };

})();
