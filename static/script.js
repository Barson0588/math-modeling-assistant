// ============================================================
// Dark Mode
// ============================================================
const THEME_KEY = 'mma-theme';
const themeToggle = document.getElementById('theme-toggle');

function getTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  if (themeToggle) themeToggle.textContent = theme === 'dark' ? '☀️' : '🌙';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

applyTheme(getTheme());
if (themeToggle) themeToggle.addEventListener('click', toggleTheme);

// ============================================================
// Eager preloading — fetch model & problem data immediately
// so tabs are ready when clicked
// ============================================================
let allModels = [];
let modelCategories = [];
let allProblems = [];
let modelsReady = false;
let problemsReady = false;

(async function preload() {
  try {
    const [mRes, pRes] = await Promise.all([
      fetch('/api/models'),
      fetch('/api/problems'),
    ]);
    const mData = await mRes.json();
    const pData = await pRes.json();
    allModels = mData.models;
    modelCategories = mData.categories;
    allProblems = pData.problems;
    modelsReady = true;
    problemsReady = true;

    // populate filters
    const catSelect = document.getElementById('model-category');
    if (catSelect) {
      catSelect.innerHTML = '<option value="">全部类别</option>' +
        modelCategories.map(c => `<option value="${c}">${c}</option>`).join('');
    }
    const probContest = document.getElementById('prob-contest');
    if (probContest) {
      probContest.innerHTML = '<option value="">全部竞赛</option>' +
        pData.contests.map(c => `<option value="${c}">${c}</option>`).join('');
    }
    const probYear = document.getElementById('prob-year');
    if (probYear) {
      probYear.innerHTML = '<option value="">全部年份</option>' +
        pData.years.map(y => `<option value="${y}">${y}</option>`).join('');
    }

    // Update stats bar with real numbers
    const statModels = document.getElementById('stat-models');
    const statProblems = document.getElementById('stat-problems');
    if (statModels) statModels.textContent = allModels.length;
    if (statProblems) statProblems.textContent = allProblems.length;

    // Pre-render into the grid so it's ready when user switches tabs
    renderModelGrid(allModels);
    updateModelCount(allModels.length);
    renderProblemListWithBookmarks(allProblems);
    updateProblemCount(allProblems.length);
  } catch (e) {
    // Preload failed — tabs will load on demand with retry
  }
})();

// ============================================================
// Quick Start Onboarding
// ============================================================
const ONBOARDING_KEY = 'mma-onboarding-done';
const onboardingDone = localStorage.getItem(ONBOARDING_KEY);
if (!onboardingDone) {
  const banner = document.createElement('div');
  banner.className = 'onboarding-banner';
  banner.id = 'onboarding-banner';
  banner.innerHTML = `
    <div class="onboarding-steps">
      <div class="onboarding-step done"><span class="step-num">1</span> 选择竞赛 & 题型</div>
      <div class="onboarding-arrow">→</div>
      <div class="onboarding-step"><span class="step-num">2</span> 粘贴题目描述</div>
      <div class="onboarding-arrow">→</div>
      <div class="onboarding-step"><span class="step-num">3</span> 点击生成论文方案</div>
    </div>
    <button class="onboarding-close" id="onboarding-dismiss">知道了</button>
  `;
  document.getElementById('tab-generator').insertBefore(banner, document.getElementById('tab-generator').firstChild);
  document.getElementById('onboarding-dismiss').addEventListener('click', () => {
    banner.style.animation = 'fadeOut .3s ease forwards';
    setTimeout(() => banner.remove(), 300);
    localStorage.setItem(ONBOARDING_KEY, '1');
  });
}

// ============================================================
// Tab switching — now with eager rendering if data is ready
// ============================================================
const loadedTabs = {};

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    const tabName = btn.dataset.tab;
    document.getElementById('tab-' + tabName).classList.add('active');

    if (!loadedTabs[tabName]) {
      loadedTabs[tabName] = true;
      switch (tabName) {
        case 'paper':
          syncGeneratorToPaper();
          break;
        case 'models':
          if (modelsReady) renderModelGrid(allModels);
          else loadModels();
          break;
        case 'problems':
          if (problemsReady) renderProblemListWithBookmarks(allProblems);
          else loadProblems();
          break;
        case 'guide': loadGuide(); break;
        case 'roles': loadRoles(); break;
      }
    } else {
      // Re-entry: always re-render data tabs so filter state stays fresh
      if (tabName === 'paper') syncGeneratorToPaper();
      if (tabName === 'models' && modelsReady) renderModelGrid(allModels);
      if (tabName === 'problems' && problemsReady) renderProblemListWithBookmarks(allProblems);
    }
  });
});

// ============================================================
// Toast
// ============================================================
function showToast(msg) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

// ============================================================
// Tab: Team Roles
// ============================================================
async function loadRoles() {
  const container = document.getElementById('roles-content');
  container.innerHTML = '<p class="empty-state"><span class="spinner spinner-dark"></span>加载中...</p>';
  try {
    const res = await fetch('/api/roles');
    const data = await res.json();
    container.innerHTML = marked.parse(data.content);
  } catch (e) {
    container.innerHTML = '<p class="error-msg">加载失败 <button class="btn-sm" onclick="loadedTabs.roles=false;loadRoles()">重试</button></p>';
  }
}

// ============================================================
// Tab: Model Library
// ============================================================
async function loadModels(retry = false) {
  const grid = document.getElementById('model-grid');
  if (!retry) grid.innerHTML = '<div class="skeleton-grid">' + Array(6).fill('<div class="skeleton-card"></div>').join('') + '</div>';

  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    allModels = data.models;
    modelCategories = data.categories;
    modelsReady = true;

    const catSelect = document.getElementById('model-category');
    if (catSelect && catSelect.options.length <= 1) {
      catSelect.innerHTML = '<option value="">全部类别</option>' +
        modelCategories.map(c => `<option value="${c}">${c}</option>`).join('');
    }

    renderModelGrid(allModels);
    updateModelCount(allModels.length);
  } catch (e) {
    grid.innerHTML = `<p class="error-msg">加载失败 <button class="btn-sm" onclick="loadModels(true)">重试</button></p>`;
  }
}

function getModelsFilters() {
  const category = document.getElementById('model-category').value;
  const mcmType = document.getElementById('model-type').value;
  const difficulty = document.getElementById('model-difficulty').value;
  const search = document.getElementById('model-search').value.trim().toLowerCase();
  return { category, mcmType, difficulty, search };
}

function filterModels() {
  if (!modelsReady) return;
  const { category, mcmType, difficulty, search } = getModelsFilters();
  let results = allModels;
  const hasActiveFilter = category || mcmType || difficulty || search;

  if (category) results = results.filter(m => m.category === category);
  if (mcmType) results = results.filter(m => m.mcm_type.includes(mcmType));
  if (difficulty) results = results.filter(m => m.difficulty === difficulty);
  if (search) {
    results = results.filter(m =>
      m.name.toLowerCase().includes(search) ||
      m.summary.toLowerCase().includes(search) ||
      m.tags.some(t => t.toLowerCase().includes(search))
    );
  }

  // When a problem type filter is active, boost matching models with a "推荐" flag
  if (mcmType) {
    results = results.map(m => ({ ...m, _recommended: true }));
  }

  // Sort: recommended first, then by difficulty (入门 → 进阶)
  const diffOrder = { '入门': 0, '简单': 1, '中等': 2, '进阶': 3 };
  results.sort((a, b) => {
    if (a._recommended && !b._recommended) return -1;
    if (!a._recommended && b._recommended) return 1;
    return (diffOrder[a.difficulty] || 99) - (diffOrder[b.difficulty] || 99);
  });

  renderModelGrid(results, hasActiveFilter);
  updateModelCount(results.length);
}

document.getElementById('model-category').addEventListener('change', filterModels);
document.getElementById('model-type').addEventListener('change', filterModels);
document.getElementById('model-difficulty').addEventListener('change', filterModels);
document.getElementById('model-search').addEventListener('input', filterModels);

function updateModelCount(n) {
  document.getElementById('model-count').textContent = `共 ${n} 个模型`;
}

function ensureList(v) {
  if (Array.isArray(v)) return v;
  if (typeof v === 'string') return v.split(',').map(s => s.trim()).filter(Boolean);
  return [];
}

function renderModelGrid(models, hasActiveFilter = false) {
  const grid = document.getElementById('model-grid');
  if (!models || models.length === 0) {
    grid.innerHTML = '<p class="model-card-empty">没有匹配的模型</p>';
    return;
  }

  const html = models.map((m, i) => {
    const libs = ensureList(m.python_libs);
    const types = ensureList(m.mcm_type);
    const isRecommended = m._recommended && hasActiveFilter;
    return `
    <div class="model-card${isRecommended ? ' model-card-recommended' : ''}" style="animation-delay:${i * 0.03}s" data-name="${escapeHtml(m.name)}">
      <input type="checkbox" class="compare-checkbox" data-name="${escapeHtml(m.name)}" ${selectedModels.has(m.name) ? 'checked' : ''} onclick="toggleModelSelection('${escapeHtml(m.name).replace(/'/g, "\\'")}', event)">
      ${isRecommended ? '<span class="tag tag-recommended">推荐</span>' : ''}
      <div onclick="showModelDetail('${escapeHtml(m.name)}')">
        <div class="model-card-header">
          <span class="model-card-name">${escapeHtml(m.name)}</span>
          <span class="model-card-diff diff-${m.difficulty}">${m.difficulty}</span>
        </div>
        <p class="model-card-summary">${escapeHtml(m.summary)}</p>
        <div class="model-card-tags">
          <span class="tag tag-category">${m.category}</span>
          ${types.map(t => `<span class="tag tag-type">${t} 题</span>`).join('')}
        </div>
        <div class="model-card-libs">
          ${libs.slice(0, 3).map(l => `<span class="tag tag-lib">${l}</span>`).join('')}
          ${libs.length > 3 ? `<span class="tag tag-lib">+${libs.length - 3}</span>` : ''}
        </div>
      </div>
    </div>
  `;
  }).join('');

  grid.innerHTML = html;
}

async function showModelDetail(name) {
  const existing = document.querySelector('.overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.innerHTML = '<div class="overlay-card"><div class="skeleton-card" style="height:200px"></div></div>';
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

  try {
    const res = await fetch('/api/models/' + encodeURIComponent(name));
    const m = await res.json();
    if (m.error) { overlay.remove(); return; }

    const codeBlock = m.code_example
      ? `<h3>代码示例 <button class="btn-sm" onclick="event.stopPropagation();navigator.clipboard.writeText(\`${m.code_example.replace(/`/g,'\\`').replace(/\$/g,'\\$')}\`);showToast('代码已复制')" style="margin-left:8px;font-size:11px">复制代码</button></h3><pre><code>${escapeHtml(m.code_example)}</code></pre>`
      : '';

    overlay.querySelector('.overlay-card').innerHTML = `
      <button class="overlay-close" onclick="this.closest('.overlay').remove()">&times;</button>
      <h2>${escapeHtml(m.name)} <span class="model-card-diff diff-${m.difficulty}">${m.difficulty}</span></h2>
      <p style="color:var(--text-secondary);margin-top:4px">${escapeHtml(m.summary)}</p>
      <h3>适用场景</h3>
      <p>${escapeHtml(m.when)}</p>
      <h3>Python 库</h3>
      <div class="model-card-libs">${ensureList(m.python_libs).map(l => `<span class="tag tag-lib">${l}</span>`).join('')}</div>
      <h3>标签</h3>
      <div class="model-card-tags">
        <span class="tag tag-category">${m.category}</span>
        ${ensureList(m.tags).map(t => `<span class="tag tag-category">${t}</span>`).join('')}
        ${ensureList(m.mcm_type).map(t => `<span class="tag tag-type">${t} 题</span>`).join('')}
      </div>
      ${codeBlock}
    `;
  } catch (e) {
    overlay.remove();
  }
}

// Global keyboard shortcuts (except when typing in inputs)
document.addEventListener('keydown', e => {
  const tag = document.activeElement?.tagName;
  const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || document.activeElement?.isContentEditable;

  // Escape: close overlays
  if (e.key === 'Escape') {
    const overlay = document.querySelector('.overlay');
    if (overlay) { overlay.remove(); return; }
  }

  // Ctrl+Enter / Cmd+Enter: generate (works even when typing in problem textarea)
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault();
    if (document.getElementById('tab-generator').classList.contains('active')) {
      generateBtn.click();
    }
    return;
  }

  // Don't trigger shortcuts when user is typing
  if (isInput) return;

  // Ctrl/Cmd+1-5: switch tabs
  const tabKeys = { '1': 'generator', '2': 'paper', '3': 'models', '4': 'problems', '5': 'guide', '6': 'roles' };
  if ((e.metaKey || e.ctrlKey) && tabKeys[e.key]) {
    e.preventDefault();
    const btn = document.querySelector(`[data-tab="${tabKeys[e.key]}"]`);
    if (btn) btn.click();
    return;
  }

  // Ctrl/Cmd+K: focus search
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    const activeTab = document.querySelector('.tab.active');
    if (activeTab) {
      const search = activeTab.querySelector('.search-input') || activeTab.querySelector('input[type="text"]');
      if (search) search.focus();
    }
    return;
  }

  // ?: show keyboard shortcuts
  if (e.key === '?') {
    showShortcuts();
    return;
  }
});

function showShortcuts() {
  const existing = document.querySelector('.shortcuts-overlay');
  if (existing) { existing.remove(); return; }
  const overlay = document.createElement('div');
  overlay.className = 'overlay shortcuts-overlay';
  overlay.innerHTML = `
    <div class="overlay-card shortcuts-card">
      <button class="overlay-close" onclick="this.closest('.overlay').remove()">&times;</button>
      <h2>键盘快捷键</h2>
      <div class="shortcuts-grid">
        <div class="shortcut-row"><kbd>Ctrl + Enter</kbd><span>生成论文方案</span></div>
        <div class="shortcut-row"><kbd>Ctrl + 1-6</kbd><span>切换标签页</span></div>
        <div class="shortcut-row"><kbd>Ctrl + K</kbd><span>聚焦搜索框</span></div>
        <div class="shortcut-row"><kbd>Esc</kbd><span>关闭弹窗</span></div>
        <div class="shortcut-row"><kbd>?</kbd><span>显示此帮助</span></div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

// ============================================================
// Tab: Real Problems
// ============================================================
async function loadProblems(retry = false) {
  const list = document.getElementById('problem-list');
  if (!retry) list.innerHTML = '<div class="skeleton-grid">' + Array(4).fill('<div class="skeleton-card"></div>').join('') + '</div>';

  try {
    const res = await fetch('/api/problems');
    const data = await res.json();
    allProblems = data.problems;
    problemsReady = true;

    const probContest = document.getElementById('prob-contest');
    if (probContest && probContest.options.length <= 1) {
      probContest.innerHTML = '<option value="">全部竞赛</option>' +
        data.contests.map(c => `<option value="${c}">${c}</option>`).join('');
    }
    const probYear = document.getElementById('prob-year');
    if (probYear && probYear.options.length <= 1) {
      probYear.innerHTML = '<option value="">全部年份</option>' +
        data.years.map(y => `<option value="${y}">${y}</option>`).join('');
    }

    renderProblemListWithBookmarks(allProblems);
    updateProblemCount(allProblems.length);
  } catch (e) {
    list.innerHTML = `<p class="error-msg">加载失败 <button class="btn-sm" onclick="loadProblems(true)">重试</button></p>`;
  }
}

function updateProblemCount(n) {
  document.getElementById('prob-count').textContent = `共 ${n} 道真题`;
}

function useProblem(contest, type, category, description, requirements) {
  const contestMap = { MCM: 'MCM/ICM', ICM: 'MCM/ICM', CUMCM: 'CUMCM' };
  document.getElementById('contest-type').value = contestMap[contest] || 'MCM/ICM';
  document.getElementById('problem-type').value = type;
  document.getElementById('problem').value = description;
  document.getElementById('requirements').value = requirements || '';

  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="generator"]').classList.add('active');
  document.getElementById('tab-generator').classList.add('active');
  document.getElementById('tab-generator').scrollIntoView({ behavior: 'smooth' });
  showToast('题目已填入，可开始生成');
}

// ============================================================
// Tab: Competition Guide
// ============================================================
async function loadGuide() {
  try {
    const res = await fetch('/api/guide');
    const data = await res.json();
    renderTimeline(data.timeline);
    renderTools(data.tools);
    renderCodeStandards(data.code_standards);
    if (data.submission_checklist) renderSubmissionChecklist(data.submission_checklist);
  } catch (e) {
    document.getElementById('timeline-container').innerHTML = '<p class="error-msg">加载失败 <button class="btn-sm" onclick="loadedTabs.guide=false;loadGuide()">重试</button></p>';
  }
}

function renderTimeline(timeline) {
  document.getElementById('timeline-container').innerHTML = `
    <div class="timeline">
      ${timeline.map(d => `
        <div class="timeline-day">
          <h3>${escapeHtml(d.day)}</h3>
          <p class="timeline-goal">目标：${escapeHtml(d.goal)}</p>
          <div class="timeline-roles">
            <div class="timeline-role"><strong>建模手</strong>${escapeHtml(d.modeler)}</div>
            <div class="timeline-role"><strong>编程手</strong>${escapeHtml(d.programmer)}</div>
            <div class="timeline-role"><strong>写作手</strong>${escapeHtml(d.writer)}</div>
          </div>
          <div class="timeline-checkpoint">检查点：${escapeHtml(d.checkpoint)}</div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderTools(tools) {
  document.getElementById('tools-container').innerHTML = `
    <div class="tools-grid">
      ${tools.map(t => `
        <div class="tool-card">
          <h3>${escapeHtml(t.name)}</h3>
          <p class="tool-use">${escapeHtml(t.use)}</p>
          <p class="tool-pkgs">${escapeHtml(t.pkgs)}</p>
        </div>
      `).join('')}
    </div>
  `;
}

function renderCodeStandards(standards) {
  const labels = {
    structure: '文件结构', naming: '命名规范', comments: '代码注释',
    reproducibility: '可复现性', output: '输出规范',
  };
  document.getElementById('code-standards-container').innerHTML = `
    <div class="standards-list">
      ${Object.entries(standards).map(([k, v]) => `
        <div class="standard-item">
          <span class="standard-label">${labels[k] || k}</span>
          <span class="standard-text">${escapeHtml(v)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

// ============================================================
// Tab: Generator — SSE Streaming
// ============================================================
const generateBtn = document.getElementById('generate-btn');
const aiReportBtn = document.getElementById('ai-report-btn');
const resultDiv = document.getElementById('result');
const resultContent = document.getElementById('result-content');
const resultLabel = document.getElementById('result-label');
const historyCard = document.getElementById('history-card');
const historyList = document.getElementById('history-list');

function setButtonsLoading(btn, loading) {
  btn.querySelector('.btn-text').hidden = loading;
  btn.querySelector('.btn-loading').hidden = !loading;
  btn.disabled = loading;
}

function mapProblemCategory(type) {
  const map = { A: '连续型', B: '离散型', C: '数据洞察', D: '网络科学', E: '可持续性', F: '政策研究' };
  return map[type] || '连续型';
}

generateBtn.addEventListener('click', async () => {
  const problem = document.getElementById('problem').value.trim();
  const requirements = document.getElementById('requirements').value.trim();
  const contestType = document.getElementById('contest-type').value;
  const problemType = document.getElementById('problem-type').value;

  if (!problem) { showToast('请先输入竞赛题目'); return; }

  setButtonsLoading(generateBtn, true);
  aiReportBtn.disabled = true;
  resultDiv.classList.add('visible');
  resultContent.innerHTML = '<div class="stage-indicator"><span class="stage-dot"></span>准备中...</div>';
  resultLabel.textContent = '生成结果';
  resultDiv.scrollIntoView({ behavior: 'smooth' });
  const stageEl = resultContent.querySelector('.stage-indicator');

  let fullContent = '';
  let errorOccurred = false;

  try {
    const res = await fetch('/api/generate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ problem, requirements, contest_type: contestType, problem_type: problemType, problem_category: mapProblemCategory(problemType) }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let chunkCount = 0;
    let msgLines = [];  // accumulate data: lines for current SSE message

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        // SSE message boundary: empty line (or just \r)
        if (line === '' || line === '\r') {
          if (msgLines.length > 0) {
            const data = msgLines.join('\n');
            msgLines = [];
            if (data === '[DONE]') continue;
            if (data.startsWith('[ERROR]')) { errorOccurred = true; throw new Error(data.slice(8)); }
            fullContent += data;
            chunkCount++;
            if (stageEl) stageEl.innerHTML = '<span class="stage-dot"></span>' + detectStage(fullContent);
            if (chunkCount % 10 === 0 || fullContent.length < 200) {
              resultContent.innerHTML = marked.parse(fullContent) + '<span class="streaming-cursor"></span>';
              injectCodeCopyButtons(resultContent);
            }
          }
        } else if (line.startsWith('data: ')) {
          msgLines.push(line.slice(6));
        }
        // ignore comment lines (starting with :)
      }
    }

    // Final render
    resultContent.innerHTML = marked.parse(fullContent);
    injectCodeCopyButtons(resultContent);
    buildTOC(resultContent);
    injectDisclaimer(resultContent);
    injectVerificationChecklist(resultContent);
    injectExplainButtons(resultContent);
    injectScholarButton();
    if (!errorOccurred && fullContent) {
      saveHistory(problem, contestType, problemType, fullContent);
      saveDraft(problem, contestType, problemType, fullContent);
    }
  } catch (e) {
    if (!errorOccurred) {
      resultContent.innerHTML = `<p class="error-msg">生成失败: ${escapeHtml(e.message)} <button class="btn-sm" onclick="generateBtn.click()">重试</button></p>`;
    }
  } finally {
    setButtonsLoading(generateBtn, false);
    aiReportBtn.disabled = false;
  }
});

// AI Use Report
aiReportBtn.addEventListener('click', async () => {
  const problem = document.getElementById('problem').value.trim();
  if (!problem) { showToast('请先输入竞赛题目'); return; }

  setButtonsLoading(aiReportBtn, true);
  generateBtn.disabled = true;
  resultDiv.classList.add('visible');
  resultContent.innerHTML = '<p class="empty-state"><span class="spinner spinner-dark"></span>生成 AI 使用报告...</p>';
  resultLabel.textContent = 'AI 使用报告';
  resultDiv.scrollIntoView({ behavior: 'smooth' });

  try {
    const res = await fetch('/api/ai-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ problem }),
    });
    const data = await res.json();
    if (data.error) {
      resultContent.innerHTML = `<p class="error-msg">${escapeHtml(data.error)}</p>`;
    } else {
      resultContent.innerHTML = marked.parse(data.content);
      injectCodeCopyButtons(resultContent);
      buildTOC(resultContent);
    }
  } catch (e) {
    resultContent.innerHTML = '<p class="error-msg">网络错误，请检查服务器是否运行 <button class="btn-sm" onclick="aiReportBtn.click()">重试</button></p>';
  } finally {
    setButtonsLoading(aiReportBtn, false);
    generateBtn.disabled = false;
  }
});

// ============================================================
// Copy & Download
// ============================================================
document.getElementById('copy-btn').addEventListener('click', () => {
  const text = resultContent.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('copy-btn');
    btn.textContent = '已复制';
    setTimeout(() => btn.textContent = '复制全文', 1500);
  }).catch(() => showToast('复制失败'));
});

function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Add download buttons dynamically
(function addDownloadButtons() {
  const actions = document.querySelector('.result-actions');
  if (!actions) return;

  const mdBtn = document.createElement('button');
  mdBtn.className = 'btn-sm'; mdBtn.textContent = '下载 .md';
  mdBtn.addEventListener('click', () => {
    const text = resultContent.innerText;
    if (!text.trim()) { showToast('没有可下载的内容'); return; }
    downloadFile(text, 'paper-framework.md', 'text/markdown;charset=utf-8');
    showToast('已下载 Markdown 文件');
  });

  const texBtn = document.createElement('button');
  texBtn.className = 'btn-sm'; texBtn.textContent = '下载 .tex';
  texBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/latex');
      const data = await res.json();
      if (data.content) {
        downloadFile(data.content, 'paper-template.tex', 'application/x-tex;charset=utf-8');
        showToast('已下载 LaTeX 模板');
      }
    } catch (e) { showToast('下载失败'); }
  });

  actions.appendChild(mdBtn);
  actions.appendChild(texBtn);
})();

// LaTeX template viewer
document.getElementById('latex-btn').addEventListener('click', async () => {
  const btn = document.getElementById('latex-btn');
  const orig = btn.textContent;
  btn.textContent = '加载中...'; btn.disabled = true;

  try {
    const res = await fetch('/api/latex');
    const data = await res.json();
    resultDiv.classList.add('visible');
    resultContent.innerHTML = data.content ? `<pre><code>${escapeHtml(data.content)}</code></pre>` : '<p class="empty-state">暂无模板</p>';
    resultLabel.textContent = 'LaTeX 模板';
    resultDiv.scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    showToast('加载 LaTeX 模板失败');
  } finally {
    btn.textContent = orig; btn.disabled = false;
  }
});

// ============================================================
// Paper Tab — Full Paper Generation & Preview
// ============================================================
const paperGenerateBtn = document.getElementById('paper-generate-btn');
const paperResult = document.getElementById('paper-result');
const paperContent = document.getElementById('paper-content');
const paperResultLabel = document.getElementById('paper-result-label');

function syncGeneratorToPaper() {
  // Copy problem from generator if paper fields are empty
  const genProblem = document.getElementById('problem').value.trim();
  const genReq = document.getElementById('requirements').value.trim();
  const genContest = document.getElementById('contest-type').value;
  const genType = document.getElementById('problem-type').value;

  const paperProblem = document.getElementById('paper-problem');
  const paperReq = document.getElementById('paper-requirements');
  const paperContest = document.getElementById('paper-contest-type');
  const paperType = document.getElementById('paper-problem-type');

  if (!paperProblem.value.trim() && genProblem) {
    paperProblem.value = genProblem;
    paperContest.value = genContest;
    paperType.value = genType;
  }
  if (!paperReq.value.trim() && genReq) {
    paperReq.value = genReq;
  }
}

// Also sync when generator inputs change
['problem', 'requirements', 'contest-type', 'problem-type'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', () => {
    // Don't auto-sync if paper already has content
  });
});

paperGenerateBtn.addEventListener('click', async () => {
  const problem = document.getElementById('paper-problem').value.trim();
  const requirements = document.getElementById('paper-requirements').value.trim();
  const contestType = document.getElementById('paper-contest-type').value;
  const problemType = document.getElementById('paper-problem-type').value;

  if (!problem) { showToast('请先输入竞赛题目'); return; }

  setButtonsLoading(paperGenerateBtn, true);
  paperResult.classList.add('visible');
  paperContent.innerHTML = '<div class="stage-indicator"><span class="stage-dot"></span>准备中...</div>';
  paperResultLabel.textContent = '论文预览';
  paperResult.scrollIntoView({ behavior: 'smooth' });
  const stageEl = paperContent.querySelector('.stage-indicator');

  let fullContent = '';
  let errorOccurred = false;

  try {
    const res = await fetch('/api/generate-paper/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ problem, requirements, contest_type: contestType, problem_type: problemType, problem_category: mapProblemCategory(problemType) }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let chunkCount = 0;
    let msgLines = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line === '' || line === '\r') {
          if (msgLines.length > 0) {
            const data = msgLines.join('\n');
            msgLines = [];
            if (data === '[DONE]') continue;
            if (data.startsWith('[ERROR]')) { errorOccurred = true; throw new Error(data.slice(8)); }
            fullContent += data;
            chunkCount++;
            if (stageEl) stageEl.innerHTML = '<span class="stage-dot"></span>' + detectStage(fullContent);
            if (chunkCount % 10 === 0 || fullContent.length < 300) {
              paperContent.innerHTML = marked.parse(fullContent) + '<span class="streaming-cursor"></span>';
              injectCodeCopyButtons(paperContent);
            }
          }
        } else if (line.startsWith('data: ')) {
          msgLines.push(line.slice(6));
        }
      }
    }

    paperContent.innerHTML = marked.parse(fullContent);
    injectCodeCopyButtons(paperContent);
    injectDisclaimer(paperContent);
    injectVerificationChecklist(paperContent);
    injectExplainButtons(paperContent);
    if (!errorOccurred && fullContent) {
      showToast('论文生成完成');
    }
  } catch (e) {
    if (!errorOccurred) {
      paperContent.innerHTML = `<p class="error-msg">生成失败: ${escapeHtml(e.message)} <button class="btn-sm" onclick="paperGenerateBtn.click()">重试</button></p>`;
    }
  } finally {
    setButtonsLoading(paperGenerateBtn, false);
  }
});

// Paper copy button
document.getElementById('paper-copy-btn').addEventListener('click', () => {
  const text = paperContent.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('paper-copy-btn');
    btn.textContent = '已复制';
    setTimeout(() => btn.textContent = '复制全文', 1500);
  }).catch(() => showToast('复制失败'));
});

// Paper PDF download (print to PDF)
document.getElementById('paper-pdf-btn').addEventListener('click', () => {
  window.print();
});

// Paper LaTeX download — fetch from LaTeX generation endpoint
document.getElementById('paper-tex-btn').addEventListener('click', async () => {
  const problem = document.getElementById('paper-problem').value.trim();
  const requirements = document.getElementById('paper-requirements').value.trim();
  const contestType = document.getElementById('paper-contest-type').value;
  const problemType = document.getElementById('paper-problem-type').value;

  if (!problem) { showToast('请先输入竞赛题目'); return; }

  const btn = document.getElementById('paper-tex-btn');
  const orig = btn.textContent;
  btn.textContent = '生成中...'; btn.disabled = true;

  try {
    const res = await fetch('/api/generate-paper/latex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ problem, requirements, contest_type: contestType, problem_type: problemType, problem_category: mapProblemCategory(problemType) }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || '生成失败');
    }

    // Collect SSE stream
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let latexContent = '';
    let msgLines = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line === '' || line === '\r') {
          if (msgLines.length > 0) {
            const data = msgLines.join('\n');
            msgLines = [];
            if (data === '[DONE]') continue;
            if (data.startsWith('[ERROR]')) throw new Error(data.slice(8));
            latexContent += data;
          }
        } else if (line.startsWith('data: ')) {
          msgLines.push(line.slice(6));
        }
      }
    }

    if (latexContent.trim()) {
      downloadFile(latexContent, 'competition-paper.tex', 'application/x-tex;charset=utf-8');
      showToast('已下载 LaTeX 源文件');
    } else {
      showToast('LaTeX 生成失败');
    }
  } catch (e) {
    showToast('LaTeX 生成失败: ' + e.message);
  } finally {
    btn.textContent = orig; btn.disabled = false;
  }
});

// Paper DOCX download (as .md file for easy import)
document.getElementById('paper-docx-btn').addEventListener('click', () => {
  const text = paperContent.innerText;
  if (!text.trim()) { showToast('没有可下载的内容'); return; }
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'competition-paper.md';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast('已下载 Markdown 文件（可用 Pandoc 转 .docx）');
});

// ============================================================
// History (localStorage)
// ============================================================
const HISTORY_KEY = 'mma-history';
const MAX_HISTORY = 20;

function getHistory() {
  try {
    const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    // Migrate old records (string time → ISO format, add missing fields)
    return raw.map(h => ({
      problem: h.problem || '',
      contestType: h.contestType || 'MCM/ICM',
      problemType: h.problemType || 'A',
      content: h.content || '',
      time: h.time || new Date().toISOString(),
      tags: h.tags || [],
      starred: h.starred || false,
    }));
  }
  catch { return []; }
}

function saveHistory(problem, contestType, problemType, content) {
  const history = getHistory();
  history.unshift({
    problem: problem.slice(0, 120),
    contestType,
    problemType,
    content,
    time: new Date().toISOString(),
    tags: [],
    starred: false,
  });
  // Keep starred + most recent unstarred (up to MAX_HISTORY unstarred)
  const starred = history.filter(h => h.starred);
  const unstarred = history.filter(h => !h.starred).slice(0, MAX_HISTORY);
  const merged = [...starred, ...unstarred].sort((a, b) => new Date(b.time) - new Date(a.time));
  localStorage.setItem(HISTORY_KEY, JSON.stringify(merged));
  renderHistory();
}

function timeAgo(isoString) {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return new Date(isoString).toLocaleDateString('zh-CN');
}

let historyFilter = '';

function renderHistory() {
  const history = getHistory();
  if (!historyCard || !historyList) return;
  if (history.length === 0) { historyCard.hidden = true; return; }

  let filtered = history;
  if (historyFilter) {
    const q = historyFilter.toLowerCase();
    filtered = history.filter(h =>
      h.problem.toLowerCase().includes(q) ||
      h.tags.some(t => t.toLowerCase().includes(q)) ||
      h.contestType.toLowerCase().includes(q)
    );
  }

  historyCard.hidden = false;
  historyList.innerHTML = `
    <input type="text" class="history-search" placeholder="搜索历史记录..." value="${escapeHtml(historyFilter)}" oninput="historyFilter=this.value;renderHistory()">
  ` + (filtered.length === 0 ? '<p class="history-empty">没有匹配的历史记录</p>' :
    filtered.map((h, i) => `
    <div class="history-item">
      <div class="history-item-top">
        <button class="history-item-star${h.starred ? ' starred' : ''}" onclick="event.stopPropagation();toggleStar(${history.indexOf(h)})" title="${h.starred ? '取消收藏' : '收藏'}">${h.starred ? '★' : '☆'}</button>
        <span class="history-item-problem" onclick="restoreHistory(${history.indexOf(h)})">${escapeHtml(h.problem)}</span>
        <span class="history-time-rel">${timeAgo(h.time)}</span>
      </div>
      <div class="history-item-meta">${h.contestType} · ${h.problemType} 题 · ${h.content.length} 字</div>
      <div class="history-item-tags">
        ${h.tags.map(t => `<span class="history-tag" onclick="event.stopPropagation();removeTag(${history.indexOf(h)},'${escapeHtml(t)}')">${escapeHtml(t)}<span class="tag-remove">&times;</span></span>`).join('')}
        <button class="history-tag-add" onclick="event.stopPropagation();addTagPrompt(${history.indexOf(h)})">+ 标签</button>
      </div>
    </div>
  `).join('')) + `
    <div class="history-actions">
      <button class="btn-sm" onclick="event.stopPropagation();clearHistory()">清除未收藏记录</button>
    </div>
  `;
}

function toggleStar(index) {
  const history = getHistory();
  if (index < 0 || index >= history.length) return;
  history[index].starred = !history[index].starred;
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  renderHistory();
}

function addTagPrompt(index) {
  const history = getHistory();
  if (index < 0 || index >= history.length) return;
  const tag = prompt('输入标签名（如"优化模型"、"微分方程"）:');
  if (tag && tag.trim()) {
    if (!history[index].tags.includes(tag.trim())) {
      history[index].tags.push(tag.trim());
    }
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    renderHistory();
  }
}

function removeTag(index, tag) {
  const history = getHistory();
  if (index < 0 || index >= history.length) return;
  history[index].tags = history[index].tags.filter(t => t !== tag);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  renderHistory();
}

function restoreHistory(index) {
  const item = getHistory()[index];
  if (!item) return;
  resultDiv.classList.add('visible');
  resultLabel.textContent = '历史记录';
  resultContent.innerHTML = marked.parse(item.content);
  injectCodeCopyButtons(resultContent);
  buildTOC(resultContent);
  resultDiv.scrollIntoView({ behavior: 'smooth' });
  showToast('已恢复历史生成结果');
}

function clearHistory() {
  const history = getHistory();
  const starred = history.filter(h => h.starred);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(starred));
  historyFilter = '';
  renderHistory();
  if (starred.length === 0) historyCard.hidden = true;
  showToast(starred.length > 0 ? `已清除未收藏记录，保留 ${starred.length} 条收藏` : '历史记录已清除');
}

renderHistory();

// ============================================================
// Session Restore — auto-save draft to survive page refresh
// ============================================================
const DRAFT_KEY = 'mma-draft';

function saveDraft(problem, contestType, problemType, content) {
  localStorage.setItem(DRAFT_KEY, JSON.stringify({
    problem, contestType, problemType, content,
    time: new Date().toLocaleString('zh-CN'),
  }));
}

function clearDraft() {
  localStorage.removeItem(DRAFT_KEY);
  const banner = document.getElementById('draft-restore-banner');
  if (banner) banner.remove();
}

function checkDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return;
    const draft = JSON.parse(raw);
    if (!draft.content) return;

    const banner = document.createElement('div');
    banner.className = 'draft-banner';
    banner.id = 'draft-restore-banner';
    banner.innerHTML = `
      <span>上次生成结果尚未查看（${draft.time}）</span>
      <button class="btn-sm" id="draft-restore-btn">恢复结果</button>
      <button class="btn-sm" id="draft-dismiss-btn">忽略</button>
    `;
    const hero = document.querySelector('#tab-generator .hero');
    hero.insertAdjacentElement('afterend', banner);

    document.getElementById('draft-restore-btn').addEventListener('click', () => {
      document.getElementById('problem').value = draft.problem || '';
      document.getElementById('requirements').value = '';
      document.getElementById('contest-type').value = draft.contestType || 'MCM/ICM';
      document.getElementById('problem-type').value = draft.problemType || 'A';
      resultDiv.classList.add('visible');
      resultLabel.textContent = '恢复的结果';
      resultContent.innerHTML = marked.parse(draft.content);
      injectCodeCopyButtons(resultContent);
      buildTOC(resultContent);
      resultDiv.scrollIntoView({ behavior: 'smooth' });
      banner.remove();
      showToast('已恢复上次生成结果');
    });

    document.getElementById('draft-dismiss-btn').addEventListener('click', () => {
      clearDraft();
      showToast('草稿已清除');
    });
  } catch (e) {
    localStorage.removeItem(DRAFT_KEY);
  }
}

// Check for saved draft on page load
checkDraft();

// ============================================================
// Utilities
// ============================================================
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ============================================================
// TOC — floating table of contents for generated results
// ============================================================
let tocObserver = null;

function buildTOC(container) {
  // Remove old TOC
  const old = document.querySelector('.toc-sidebar');
  if (old) old.remove();
  if (tocObserver) { tocObserver.disconnect(); tocObserver = null; }

  const headings = container.querySelectorAll('h1, h2, h3');
  if (headings.length < 3) return;

  const toc = document.createElement('nav');
  toc.className = 'toc-sidebar';

  const title = document.createElement('div');
  title.className = 'toc-title';
  title.textContent = '目录';
  toc.appendChild(title);

  const items = [];
  headings.forEach((h, i) => {
    const id = 'section-' + i;
    h.id = id;
    const item = document.createElement('a');
    item.className = 'toc-item toc-' + h.tagName.toLowerCase();
    item.href = '#' + id;
    item.textContent = h.textContent;
    item.addEventListener('click', e => {
      e.preventDefault();
      h.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    toc.appendChild(item);
    items.push({ el: item, heading: h });
  });

  document.body.appendChild(toc);

  // Scroll spy
  tocObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        items.forEach(({ el }) => el.classList.remove('toc-active'));
        const match = items.find(({ heading }) => heading === entry.target);
        if (match) match.el.classList.add('toc-active');
      }
    });
  }, { rootMargin: '-80px 0px -70% 0px' });
  headings.forEach(h => tocObserver.observe(h));
}

// ============================================================
// Inject copy buttons into code blocks (called after render)
// ============================================================
function injectCodeCopyButtons(container) {
  container.querySelectorAll('pre').forEach(pre => {
    if (pre.closest('.code-block-wrapper')) return; // already wrapped
    const wrapper = document.createElement('div');
    wrapper.className = 'code-block-wrapper';
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);
    const btn = document.createElement('button');
    btn.className = 'code-copy-btn';
    btn.textContent = '复制';
    btn.addEventListener('click', () => {
      const code = pre.querySelector('code') ? pre.querySelector('code').innerText : pre.innerText;
      navigator.clipboard.writeText(code).then(() => {
        btn.textContent = '已复制';
        setTimeout(() => btn.textContent = '复制', 1500);
      });
    });
    wrapper.appendChild(btn);
  });
}

// ============================================================
// Model Comparison
// ============================================================
const selectedModels = new Set();
const compareBar = document.getElementById('compare-bar');
const compareCount = document.getElementById('compare-count');

function updateCompareBar() {
  if (selectedModels.size > 0) {
    compareBar.hidden = false;
    compareCount.textContent = `已选 ${selectedModels.size} 个模型（最多 3 个）`;
  } else {
    compareBar.hidden = true;
  }
  // update checkbox states in the grid
  document.querySelectorAll('.compare-checkbox').forEach(cb => {
    cb.checked = selectedModels.has(cb.dataset.name);
    cb.closest('.model-card')?.classList.toggle('selected', cb.checked);
  });
}

function toggleModelSelection(name, e) {
  e.stopPropagation();
  if (selectedModels.has(name)) {
    selectedModels.delete(name);
  } else {
    if (selectedModels.size >= 3) {
      showToast('最多对比 3 个模型');
      return;
    }
    selectedModels.add(name);
  }
  updateCompareBar();
}

document.getElementById('compare-clear-btn').addEventListener('click', () => {
  selectedModels.clear();
  updateCompareBar();
});

document.getElementById('compare-btn').addEventListener('click', () => {
  if (selectedModels.size < 2) { showToast('请至少选择 2 个模型进行对比'); return; }
  showCompareOverlay([...selectedModels]);
});

function showCompareOverlay(names) {
  const existing = document.querySelector('.overlay');
  if (existing) existing.remove();

  const models = allModels.filter(m => names.includes(m.name));

  const overlay = document.createElement('div');
  overlay.className = 'overlay compare-overlay';
  overlay.innerHTML = `
    <div class="overlay-card">
      <button class="overlay-close" onclick="this.closest('.overlay').remove()">&times;</button>
      <h2>模型对比</h2>
      <div class="compare-grid">
        ${models.map(m => `
          <div class="compare-col">
            <h3>${escapeHtml(m.name)} <span class="model-card-diff diff-${m.difficulty}">${m.difficulty}</span></h3>
            <div class="compare-row"><div class="compare-label">类别</div><div class="compare-value">${m.category}</div></div>
            <div class="compare-row"><div class="compare-label">原理</div><div class="compare-value">${escapeHtml(m.summary)}</div></div>
            <div class="compare-row"><div class="compare-label">适用场景</div><div class="compare-value">${escapeHtml(m.when)}</div></div>
            <div class="compare-row"><div class="compare-label">题型</div><div class="compare-value">${m.mcm_type.join(', ')} 题</div></div>
            <div class="compare-row"><div class="compare-label">Python 库</div><div class="compare-value" style="font-family:var(--mono);font-size:12px">${m.python_libs.join(', ')}</div></div>
            ${m.code_example ? `<div class="compare-row"><div class="compare-label">代码示例</div><pre><code>${escapeHtml(m.code_example)}</code></pre></div>` : ''}
          </div>
        `).join('')}
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

// ============================================================
// Problem Bookmarks
// ============================================================
const BOOKMARK_KEY = 'mma-bookmarks';

function getBookmarks() {
  try { return new Set(JSON.parse(localStorage.getItem(BOOKMARK_KEY) || '[]')); }
  catch { return new Set(); }
}

function toggleBookmark(problemId, e) {
  e.stopPropagation();
  const bookmarks = getBookmarks();
  if (bookmarks.has(problemId)) bookmarks.delete(problemId);
  else bookmarks.add(problemId);
  localStorage.setItem(BOOKMARK_KEY, JSON.stringify([...bookmarks]));
  if (problemsReady) {
    const activeFilter = document.getElementById('prob-bookmark-filter').classList.contains('active');
    if (activeFilter) filterProblems();
    else renderProblemListWithBookmarks(allProblems);
  }
}

let bookmarkFilterActive = false;
document.getElementById('prob-bookmark-filter').addEventListener('click', function() {
  bookmarkFilterActive = !bookmarkFilterActive;
  this.classList.toggle('active', bookmarkFilterActive);
  if (problemsReady) filterProblems();
});

function filterProblems() {
  if (!problemsReady) return;
  const contest = document.getElementById('prob-contest').value;
  const year = document.getElementById('prob-year').value;
  const type = document.getElementById('prob-type').value;
  let results = allProblems;
  if (contest) results = results.filter(p => p.contest === contest);
  if (year) results = results.filter(p => String(p.year) === year);
  if (type) results = results.filter(p => p.type === type);
  if (bookmarkFilterActive) {
    const bookmarks = getBookmarks();
    results = results.filter(p => bookmarks.has(p.title));
  }
  renderProblemListWithBookmarks(results);
  updateProblemCount(results.length);
}

function renderProblemListWithBookmarks(problems) {
  const list = document.getElementById('problem-list');
  if (!problems || problems.length === 0) {
    list.innerHTML = '<p class="empty-state">没有匹配的题目</p>';
    return;
  }

  const bookmarks = getBookmarks();
  const badgeClass = { MCM: 'badge-mcm', ICM: 'badge-icm', CUMCM: 'badge-cumcm' };
  list.innerHTML = problems.map((p, i) => `
    <div class="problem-card" style="animation-delay:${i * 0.05}s">
      <div class="problem-card-top">
        <span class="problem-badge ${badgeClass[p.contest] || 'badge-mcm'}">${p.contest} ${p.type} 题</span>
        <span class="problem-year">${p.year}</span>
        <span style="font-size:12px;color:var(--text-secondary)">${p.category}</span>
        <button class="bookmark-btn ${bookmarks.has(p.title) ? 'bookmarked' : ''}" onclick="toggleBookmark('${p.title.replace(/'/g, "\\'")}', event)" title="收藏">${bookmarks.has(p.title) ? '★' : '☆'}</button>
        <span style="flex:1"></span>
        <span class="hint-action" style="cursor:pointer" onclick="useProblem('${p.contest}', '${p.type}', '${p.category}', \`${p.description.replace(/`/g, '\\`')}\`, \`${(p.requirements || '').replace(/`/g, '\\`')}\`)">点击填入 →</span>
      </div>
      <h3 style="cursor:pointer" onclick="useProblem('${p.contest}', '${p.type}', '${p.category}', \`${p.description.replace(/`/g, '\\`')}\`, \`${(p.requirements || '').replace(/`/g, '\\`')}\`)">${escapeHtml(p.title)}</h3>
      <p style="cursor:pointer" onclick="useProblem('${p.contest}', '${p.type}', '${p.category}', \`${p.description.replace(/`/g, '\\`')}\`, \`${(p.requirements || '').replace(/`/g, '\\`')}\`)">${escapeHtml(p.description)}</p>
    </div>
  `).join('');
}

// Print / PDF
document.getElementById('print-btn').addEventListener('click', () => {
  window.print();
});

// Keyboard shortcuts handled in unified handler above (line ~330)

// ============================================================
// Stage Detection — parse streaming content for current section
// ============================================================
function detectStage(content) {
  const headings = content.match(/^#{1,3}\s+(.+)$/gm);
  if (!headings || headings.length === 0) return '正在分析问题...';
  const last = headings[headings.length - 1].replace(/^#+\s*/, '').trim();
  if (last.length > 60) return '正在撰写 ' + last.slice(0, 57) + '...';
  return '正在撰写 ' + last + '...';
}

// ============================================================
// Disclaimer Banner — inject into results
// ============================================================
function injectDisclaimer(container) {
  if (container.querySelector('.disclaimer-banner')) return;
  const banner = document.createElement('div');
  banner.className = 'disclaimer-banner';
  banner.innerHTML = '<span class="disclaimer-icon">⚠️</span><span>AI 生成内容仅供学习参考。所有数学推导、数据和引用需人工验证后使用，不可直接作为竞赛提交材料。</span>';
  container.insertBefore(banner, container.firstChild);
}

// ============================================================
// Verification Checklist — inject into results
// ============================================================
const VERIFY_KEY = 'mma-verify-checks';

function getVerifyChecks() {
  try { return JSON.parse(localStorage.getItem(VERIFY_KEY) || '{}'); }
  catch { return {}; }
}

function injectVerificationChecklist(container) {
  if (container.querySelector('.verify-checklist')) return;
  const items = [
    { id: 'math', text: '数学推导已验证 — 公式、符号、逻辑正确' },
    { id: 'refs', text: '参考文献已核实 — 引用真实存在且格式正确' },
    { id: 'code', text: '代码可运行 — 已测试并输出预期结果' },
    { id: 'abstract', text: '摘要符合要求 — 字数、格式、无公式引用' },
  ];
  const checks = getVerifyChecks();
  const done = items.filter(i => checks[i.id]).length;

  const wrapper = document.createElement('div');
  wrapper.className = 'verify-checklist';
  wrapper.innerHTML = `
    <div class="verify-title">
      验证清单
      <span class="verify-progress">${done}/${items.length}</span>
    </div>
    ${items.map(i => `
      <label class="verify-item${checks[i.id] ? ' checked' : ''}" data-id="${i.id}">
        <input type="checkbox" ${checks[i.id] ? 'checked' : ''} onchange="toggleVerifyCheck('${i.id}', this)">
        <span class="verify-check-text">${i.text}</span>
      </label>
    `).join('')}
    <div class="verify-ready${done === items.length ? ' show' : ''}">✓ 所有检查项已完成，论文已就绪</div>
  `;
  container.appendChild(wrapper);
}

function toggleVerifyCheck(id, checkbox) {
  const checks = getVerifyChecks();
  checks[id] = checkbox.checked;
  localStorage.setItem(VERIFY_KEY, JSON.stringify(checks));
  // Re-render to update progress
  const container = checkbox.closest('.verify-checklist');
  if (container) {
    const allDone = Object.values(checks).filter(Boolean).length >= 4;
    const progress = container.querySelector('.verify-progress');
    if (progress) progress.textContent = `${Object.values(checks).filter(Boolean).length}/4`;
    const ready = container.querySelector('.verify-ready');
    if (ready) ready.classList.toggle('show', allDone);
    const item = checkbox.closest('.verify-item');
    if (item) item.classList.toggle('checked', checkbox.checked);
  }
}

// ============================================================
// Explain Buttons — inject ? buttons on section headings
// ============================================================
function injectExplainButtons(container) {
  const headings = container.querySelectorAll('h2, h3');
  headings.forEach(h => {
    if (h.querySelector('.explain-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'explain-btn';
    btn.textContent = '?';
    btn.title = '用通俗语言解释此章节';
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const section = h;
      // Collect content until next heading
      let content = '';
      let el = section.nextElementSibling;
      while (el && !['H1', 'H2', 'H3'].includes(el.tagName)) {
        content += el.textContent + '\n';
        el = el.nextElementSibling;
      }
      showExplainPanel(section.textContent, content.slice(0, 2000));
    });
    h.appendChild(btn);
  });
}

function showExplainPanel(title, content) {
  // Remove existing panel
  const existing = document.querySelector('.explain-panel');
  if (existing) existing.remove();

  const panel = document.createElement('div');
  panel.className = 'explain-panel';
  panel.innerHTML = `
    <div class="explain-panel-header">
      <h3>通俗解释</h3>
      <button class="explain-panel-close" onclick="this.closest('.explain-panel').remove()">&times;</button>
    </div>
    <div class="explain-panel-body">
      <p style="color:var(--text-secondary);font-size:13px">章节: ${escapeHtml(title).slice(0, 80)}</p>
      <div style="margin-top:12px"><span class="spinner spinner-dark"></span> 生成通俗解释...</div>
    </div>
    <div class="explain-panel-actions">
      <button class="btn-sm" onclick="const t=this.closest('.explain-panel').querySelector('.explain-panel-body').innerText;navigator.clipboard.writeText(t);showToast('已复制')">复制解释</button>
      <button class="btn-sm" onclick="this.closest('.explain-panel').remove()">关闭</button>
    </div>
  `;
  document.body.appendChild(panel);

  // Fetch explanation
  fetch('/api/explain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ section_title: title, section_content: content }),
  })
  .then(res => res.json())
  .then(data => {
    const body = panel.querySelector('.explain-panel-body');
    if (data.error) {
      body.innerHTML = `<p class="error-msg">${escapeHtml(data.error)}</p>`;
    } else {
      body.innerHTML = marked.parse(data.content);
    }
  })
  .catch(() => {
    panel.querySelector('.explain-panel-body').innerHTML = '<p class="error-msg">网络错误，请重试</p>';
  });

  // Close on Escape
  const escHandler = e => { if (e.key === 'Escape') { panel.remove(); document.removeEventListener('keydown', escHandler); } };
  document.addEventListener('keydown', escHandler);
}

// ============================================================
// Scholar Search Button — fetch real references
// ============================================================
function injectScholarButton() {
  const actions = document.querySelector('.result-actions');
  if (!actions || actions.querySelector('.scholar-btn')) return;

  const btn = document.createElement('button');
  btn.className = 'btn-sm scholar-btn';
  btn.textContent = '检索真实文献';
  btn.addEventListener('click', async () => {
    const resultContent = document.getElementById('result-content');
    // Extract keywords from the generated content
    const text = resultContent.innerText;
    const modelSection = text.match(/模型.*?方案|Model.*?Development/i);
    const keywords = modelSection ? modelSection[0].slice(0, 100) : text.slice(200, 400);

    btn.textContent = '检索中...';
    btn.disabled = true;

    try {
      const res = await fetch('/api/scholar/search?q=' + encodeURIComponent(keywords.slice(0, 200)));
      const data = await res.json();

      let existing = resultContent.querySelector('.scholar-results');
      if (existing) existing.remove();

      const div = document.createElement('div');
      div.className = 'scholar-results';
      if (data.papers && data.papers.length > 0) {
        div.innerHTML = '<h3>真实参考文献 (Semantic Scholar)</h3>' +
          data.papers.map(p => `
            <div class="scholar-paper">
              <div class="scholar-title">${escapeHtml(p.title)}</div>
              <div class="scholar-meta">${p.authors.slice(0, 3).join(', ')}${p.authors.length > 3 ? ', et al.' : ''} (${p.year || 'n.d.'})</div>
              ${p.citationCount ? `<span class="scholar-citations">被引 ${p.citationCount} 次</span>` : ''}
              ${p.url ? ` <a href="${p.url}" target="_blank" rel="noopener" style="font-size:11px">查看</a>` : ''}
            </div>
          `).join('');
      } else {
        div.innerHTML = '<div class="scholar-results"><h3>真实参考文献</h3><p style="color:var(--text-secondary);font-size:13px">未找到相关文献，建议调整关键词或手动检索</p></div>';
      }
      resultContent.appendChild(div);
    } catch (e) {
      showToast('文献检索失败');
    } finally {
      btn.textContent = '检索真实文献';
      btn.disabled = false;
    }
  });
  actions.appendChild(btn);
}

// ============================================================
// Submission Checklist — render in Guide tab
// ============================================================
function renderSubmissionChecklist(checklist) {
  const container = document.getElementById('submission-checklist');
  if (!container) return;

  const saved = JSON.parse(localStorage.getItem('mma-checklist') || '{}');

  function render() {
    const done = Object.values(saved).filter(Boolean).length;
    const total = Object.keys(saved).length || Object.values(checklist.mcm).length + Object.values(checklist.cumcm).length;
    const pct = total > 0 ? Math.round(done / total * 100) : 0;

    container.innerHTML = `
      <div class="checklist-progress">
        <div class="checklist-progress-bar"><div class="checklist-progress-fill" style="width:${pct}%"></div></div>
        <div class="checklist-progress-text">${done}/${total} (${pct}%)</div>
      </div>
      <div class="checklist-section">
        <h3>美赛 MCM/ICM</h3>
        ${checklist.mcm.map(item => `
          <label class="verify-item${saved[item.id] ? ' checked' : ''}">
            <input type="checkbox" ${saved[item.id] ? 'checked' : ''} onchange="toggleChecklistItem('${item.id}', this.checked)">
            <span class="verify-check-text">${item.text}</span>
          </label>
        `).join('')}
      </div>
      <div class="checklist-section">
        <h3>国赛 CUMCM</h3>
        ${checklist.cumcm.map(item => `
          <label class="verify-item${saved[item.id] ? ' checked' : ''}">
            <input type="checkbox" ${saved[item.id] ? 'checked' : ''} onchange="toggleChecklistItem('${item.id}', this.checked)">
            <span class="verify-check-text">${item.text}</span>
          </label>
        `).join('')}
      </div>
    `;
  }

  window.toggleChecklistItem = function(id, checked) {
    saved[id] = checked;
    localStorage.setItem('mma-checklist', JSON.stringify(saved));
    render();
  };

  render();
}

// ============================================================
// Update keyboard shortcut — add Paper tab (6)
// ============================================================
// Monkey-patch the existing handler: add '6': 'paper' to tabKeys
// Already handled in the unified handler — update tabKeys object
(function updateShortcuts() {
  const handler = document.addEventListener.toString();
  // We redefine the keydown listener — actually just add paper in the
  // existing tabKeys object. Since it's already registered, we override.
  const origHandler = document.onkeydown;
})();

// Actually the tab keys are defined inline in the event listener.
// We need to update it. Let's find and update via a different approach:
// Add explicit paper tab switching via Ctrl+6
document.addEventListener('keydown', function paperShortcut(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === '6') {
    e.preventDefault();
    const btn = document.querySelector('[data-tab="paper"]');
    if (btn) btn.click();
  }
});
