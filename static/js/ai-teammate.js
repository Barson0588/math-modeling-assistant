// AI Teammate — floating panel with auto role-switching, proactive hints, voice input
(function() {
  const ROLE_CONFIG = {
    generator: { name: '建模手', icon: '📐' },
    paper: { name: '写作手', icon: '✍️' },
    models: { name: '建模手', icon: '📐' },
    problems: { name: '建模手', icon: '📐' },
    guide: { name: '教练', icon: '🎯' },
    roles: { name: '教练', icon: '🎯' },
  };

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

  function open() {
    panel.hidden = false;
    panelOpen = true;
    unreadCount = 0;
    badge.hidden = true;
    setTimeout(function() { if (inputEl) inputEl.focus(); }, 300);
  }

  function close() {
    panel.hidden = true;
    panelOpen = false;
  }

  function handleAction(payload) {
    if (!payload) return;
    switch(payload) {
      case 'recommend_continuous':
        document.querySelector('[data-tab="models"]')?.click();
        break;
      case 'recommend_discrete':
        document.querySelector('[data-tab="models"]')?.click();
        break;
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
  var origNavHandler = null;
  document.querySelectorAll('.nav-btn').forEach(function(btn) {
    var origClick = btn.onclick;
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
  // Watch for generation completions
  var genObserver = new MutationObserver(function(mutations) {
    mutations.forEach(function(m) {
      if (m.target.id === 'result-content' && m.target.children.length > 50) {
        // Content appeared - generation likely completed
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
        // Re-observe after 5s for next generation
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
