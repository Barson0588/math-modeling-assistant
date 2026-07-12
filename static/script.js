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
  themeToggle.textContent = theme === 'dark' ? '☀️' : '🌙';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

applyTheme(getTheme());
themeToggle.addEventListener('click', toggleTheme);

// ============================================================
// Tab switching with lazy loading
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
        case 'models': loadModels(); break;
        case 'problems': loadProblems(); break;
        case 'guide': loadGuide(); break;
        case 'roles': loadRoles(); break;
      }
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
  setTimeout(() => t.remove(), 2000);
}

// ============================================================
// Tab: Team Roles (lazy)
// ============================================================
async function loadRoles() {
  const container = document.getElementById('roles-content');
  container.innerHTML = '<p class="empty-state"><span class="spinner spinner-dark"></span>加载中...</p>';
  try {
    const res = await fetch('/api/roles');
    const data = await res.json();
    container.innerHTML = marked.parse(data.content);
  } catch (e) {
    container.innerHTML = '<p style="color:var(--red)">加载失败，请刷新重试</p>';
  }
}

// ============================================================
// Tab: Model Library
// ============================================================
let allModels = [];
let modelCategories = [];

async function loadModels() {
  const grid = document.getElementById('model-grid');
  grid.innerHTML = '<p class="model-card-empty"><span class="spinner spinner-dark"></span>加载模型库...</p>';

  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    allModels = data.models;
    modelCategories = data.categories;

    const catSelect = document.getElementById('model-category');
    catSelect.innerHTML = '<option value="">全部类别</option>' +
      modelCategories.map(c => `<option value="${c}">${c}</option>`).join('');

    renderModelGrid(allModels);
    updateModelCount(allModels.length);
  } catch (e) {
    grid.innerHTML = '<p class="model-card-empty" style="color:var(--red)">加载失败，请刷新重试</p>';
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
  const { category, mcmType, difficulty, search } = getModelsFilters();
  let results = allModels;

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

  renderModelGrid(results);
  updateModelCount(results.length);
}

document.getElementById('model-category').addEventListener('change', filterModels);
document.getElementById('model-type').addEventListener('change', filterModels);
document.getElementById('model-difficulty').addEventListener('change', filterModels);
document.getElementById('model-search').addEventListener('input', filterModels);

function updateModelCount(n) {
  document.getElementById('model-count').textContent = `共 ${n} 个模型`;
}

function renderModelGrid(models) {
  const grid = document.getElementById('model-grid');
  if (models.length === 0) {
    grid.innerHTML = '<p class="model-card-empty">没有匹配的模型</p>';
    return;
  }

  grid.innerHTML = models.map(m => `
    <div class="model-card" data-name="${escapeHtml(m.name)}" onclick="showModelDetail('${escapeHtml(m.name)}')">
      <div class="model-card-header">
        <span class="model-card-name">${escapeHtml(m.name)}</span>
        <span class="model-card-diff diff-${m.difficulty}">${m.difficulty}</span>
      </div>
      <p class="model-card-summary">${escapeHtml(m.summary)}</p>
      <div class="model-card-tags">
        <span class="tag tag-category">${m.category}</span>
        ${m.mcm_type.map(t => `<span class="tag tag-type">${t} 题</span>`).join('')}
      </div>
      <div class="model-card-libs">
        ${m.python_libs.map(l => `<span class="tag tag-lib">${l}</span>`).join('')}
      </div>
    </div>
  `).join('');
}

async function showModelDetail(name) {
  const existing = document.querySelector('.overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.innerHTML = '<div class="overlay-card"><p style="text-align:center;color:var(--text-secondary)">加载中...</p></div>';
  document.body.appendChild(overlay);

  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

  try {
    const res = await fetch('/api/models/' + encodeURIComponent(name));
    const m = await res.json();
    if (m.error) { overlay.remove(); return; }

    const codeBlock = m.code_example
      ? `<h3>代码示例</h3><pre><code>${escapeHtml(m.code_example)}</code></pre>`
      : '';

    overlay.querySelector('.overlay-card').innerHTML = `
      <button class="overlay-close" onclick="this.closest('.overlay').remove()">&times;</button>
      <h2>${escapeHtml(m.name)} <span class="model-card-diff diff-${m.difficulty}">${m.difficulty}</span></h2>
      <p style="color:var(--text-secondary);margin-top:4px">${escapeHtml(m.summary)}</p>
      <h3>适用场景</h3>
      <p>${escapeHtml(m.when)}</p>
      <h3>Python 库</h3>
      <div class="model-card-libs">${m.python_libs.map(l => `<span class="tag tag-lib">${l}</span>`).join('')}</div>
      <h3>标签</h3>
      <div class="model-card-tags">
        <span class="tag tag-category">${m.category}</span>
        ${m.tags.map(t => `<span class="tag tag-category">${t}</span>`).join('')}
        ${m.mcm_type.map(t => `<span class="tag tag-type">${t} 题</span>`).join('')}
      </div>
      ${codeBlock}
    `;
  } catch (e) {
    overlay.remove();
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    const overlay = document.querySelector('.overlay');
    if (overlay) overlay.remove();
  }
});

// ============================================================
// Tab: Real Problems
// ============================================================
let allProblems = [];

async function loadProblems() {
  const list = document.getElementById('problem-list');
  list.innerHTML = '<p class="empty-state"><span class="spinner spinner-dark"></span>加载真题库...</p>';

  try {
    const res = await fetch('/api/problems');
    const data = await res.json();
    allProblems = data.problems;

    document.getElementById('prob-contest').innerHTML = '<option value="">全部竞赛</option>' +
      data.contests.map(c => `<option value="${c}">${c}</option>`).join('');
    document.getElementById('prob-year').innerHTML = '<option value="">全部年份</option>' +
      data.years.map(y => `<option value="${y}">${y}</option>`).join('');

    renderProblemList(allProblems);
    updateProblemCount(allProblems.length);
  } catch (e) {
    list.innerHTML = '<p class="empty-state" style="color:var(--red)">加载失败，请刷新重试</p>';
  }
}

function filterProblems() {
  const contest = document.getElementById('prob-contest').value;
  const year = document.getElementById('prob-year').value;
  const type = document.getElementById('prob-type').value;

  let results = allProblems;
  if (contest) results = results.filter(p => p.contest === contest);
  if (year) results = results.filter(p => String(p.year) === year);
  if (type) results = results.filter(p => p.type === type);

  renderProblemList(results);
  updateProblemCount(results.length);
}

document.getElementById('prob-contest').addEventListener('change', filterProblems);
document.getElementById('prob-year').addEventListener('change', filterProblems);
document.getElementById('prob-type').addEventListener('change', filterProblems);

function updateProblemCount(n) {
  document.getElementById('prob-count').textContent = `共 ${n} 道真题`;
}

function renderProblemList(problems) {
  const list = document.getElementById('problem-list');
  if (problems.length === 0) {
    list.innerHTML = '<p class="empty-state">没有匹配的题目</p>';
    return;
  }

  const badgeClass = { MCM: 'badge-mcm', ICM: 'badge-icm', CUMCM: 'badge-cumcm' };

  list.innerHTML = problems.map(p => `
    <div class="problem-card" onclick="useProblem('${p.contest}', '${p.type}', '${p.category}', \`${p.description.replace(/`/g, '\\`')}\`, \`${(p.requirements || '').replace(/`/g, '\\`')}\`)">
      <div class="problem-card-top">
        <span class="problem-badge ${badgeClass[p.contest] || 'badge-mcm'}">${p.contest} ${p.type} 题</span>
        <span class="problem-year">${p.year}</span>
        <span style="font-size:12px;color:var(--text-secondary)">${p.category}</span>
      </div>
      <h3>${escapeHtml(p.title)}</h3>
      <p>${escapeHtml(p.description)}</p>
      <p class="hint-action">点击填入生成器 →</p>
    </div>
  `).join('');
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
  } catch (e) {
    document.getElementById('timeline-container').innerHTML = '<p style="color:var(--red)">加载失败</p>';
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
    structure: '文件结构',
    naming: '命名规范',
    comments: '代码注释',
    reproducibility: '可复现性',
    output: '输出规范',
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

  if (!problem) {
    showToast('请先输入竞赛题目');
    return;
  }

  setButtonsLoading(generateBtn, true);
  aiReportBtn.disabled = true;
  resultDiv.classList.add('visible');
  resultContent.innerHTML = '<p style="color:var(--text-secondary)"><span class="spinner spinner-dark"></span>生成中...</p>';
  resultLabel.textContent = '生成结果';

  let fullContent = '';
  let errorOccurred = false;

  try {
    const res = await fetch('/api/generate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        problem,
        requirements,
        contest_type: contestType,
        problem_type: problemType,
        problem_category: mapProblemCategory(problemType),
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);

        if (data === '[DONE]') continue;
        if (data.startsWith('[ERROR]')) {
          errorOccurred = true;
          throw new Error(data.slice(8));
        }

        fullContent += data;
        resultContent.innerHTML = marked.parse(fullContent);
        resultContent.classList.add('streaming-cursor');
      }
    }

    resultContent.classList.remove('streaming-cursor');
    if (!errorOccurred && fullContent) {
      resultContent.innerHTML = marked.parse(fullContent);
      saveHistory(problem, contestType, problemType, fullContent);
    }
  } catch (e) {
    if (!errorOccurred) {
      resultContent.innerHTML = `<p style="color:var(--red)">生成失败: ${escapeHtml(e.message)}</p>`;
    }
  } finally {
    setButtonsLoading(generateBtn, false);
    aiReportBtn.disabled = false;
    resultContent.classList.remove('streaming-cursor');
    resultDiv.scrollIntoView({ behavior: 'smooth' });
  }
});

// AI Use Report
aiReportBtn.addEventListener('click', async () => {
  const problem = document.getElementById('problem').value.trim();

  if (!problem) {
    showToast('请先输入竞赛题目');
    return;
  }

  setButtonsLoading(aiReportBtn, true);
  generateBtn.disabled = true;
  resultDiv.classList.remove('visible');
  resultContent.innerHTML = '';
  resultLabel.textContent = 'AI 使用报告';

  try {
    const res = await fetch('/api/ai-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ problem }),
    });
    const data = await res.json();

    if (data.error) {
      resultContent.innerHTML = `<p style="color:var(--red)">${escapeHtml(data.error)}</p>`;
    } else {
      resultContent.innerHTML = marked.parse(data.content);
    }
    resultDiv.classList.add('visible');
  } catch (e) {
    resultContent.innerHTML = '<p style="color:var(--red)">网络错误，请检查服务器是否运行</p>';
    resultDiv.classList.add('visible');
  } finally {
    setButtonsLoading(aiReportBtn, false);
    generateBtn.disabled = false;
    resultDiv.scrollIntoView({ behavior: 'smooth' });
  }
});

// ============================================================
// Download buttons
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
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Add download buttons to toolbar
const downloadMdBtn = document.createElement('button');
downloadMdBtn.className = 'btn-sm';
downloadMdBtn.textContent = '下载 .md';
downloadMdBtn.addEventListener('click', () => {
  const text = resultContent.innerText;
  if (!text.trim()) { showToast('没有可下载的内容'); return; }
  downloadFile(text, 'paper-framework.md', 'text/markdown;charset=utf-8');
  showToast('已下载 Markdown 文件');
});

const downloadTexBtn = document.createElement('button');
downloadTexBtn.className = 'btn-sm';
downloadTexBtn.textContent = '下载 .tex';
downloadTexBtn.addEventListener('click', async () => {
  try {
    const res = await fetch('/api/latex');
    const data = await res.json();
    if (data.content) {
      downloadFile(data.content, 'paper-template.tex', 'application/x-tex;charset=utf-8');
      showToast('已下载 LaTeX 模板');
    }
  } catch (e) {
    showToast('下载失败');
  }
});

document.querySelector('.result-actions').appendChild(downloadMdBtn);
document.querySelector('.result-actions').appendChild(downloadTexBtn);

// Remove the old LaTeX button listener approach — we keep the button in toolbar
// but update existing latex-btn to also trigger download
document.getElementById('latex-btn').addEventListener('click', async () => {
  const btn = document.getElementById('latex-btn');
  const originalText = btn.textContent;
  btn.textContent = '加载中...';
  btn.disabled = true;

  try {
    const res = await fetch('/api/latex');
    const data = await res.json();

    resultDiv.classList.remove('visible');
    resultContent.innerHTML = '';
    resultLabel.textContent = 'LaTeX 模板';

    if (data.content) {
      resultContent.innerHTML = `<pre><code>${escapeHtml(data.content)}</code></pre>`;
      resultDiv.classList.add('visible');
      resultDiv.scrollIntoView({ behavior: 'smooth' });
    }
  } catch (e) {
    showToast('加载 LaTeX 模板失败');
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
});

// ============================================================
// History (localStorage)
// ============================================================
const HISTORY_KEY = 'mma-history';
const MAX_HISTORY = 5;

function getHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  } catch { return []; }
}

function saveHistory(problem, contestType, problemType, content) {
  const history = getHistory();
  history.unshift({
    problem: problem.slice(0, 120),
    contestType,
    problemType,
    content,
    time: new Date().toLocaleString('zh-CN'),
  });
  if (history.length > MAX_HISTORY) history.length = MAX_HISTORY;
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  renderHistory();
}

function renderHistory() {
  const history = getHistory();
  if (history.length === 0) {
    historyCard.hidden = true;
    return;
  }

  historyCard.hidden = false;
  historyList.innerHTML = history.map((h, i) => `
    <div class="history-item" onclick="restoreHistory(${i})">
      <div class="history-item-top">
        <span class="history-item-problem">${escapeHtml(h.problem)}</span>
        <span class="history-item-time">${h.time}</span>
      </div>
      <div class="history-item-meta">${h.contestType} · ${h.problemType} 题 · ${h.content.length} 字</div>
    </div>
  `).join('');

  // Add clear button
  historyList.insertAdjacentHTML('beforeend', `
    <div class="history-actions">
      <button class="btn-sm" onclick="event.stopPropagation(); clearHistory()">清除记录</button>
    </div>
  `);
}

function restoreHistory(index) {
  const history = getHistory();
  const item = history[index];
  if (!item) return;

  resultDiv.classList.add('visible');
  resultLabel.textContent = '历史记录';
  resultContent.innerHTML = marked.parse(item.content);
  resultDiv.scrollIntoView({ behavior: 'smooth' });
  showToast('已恢复历史生成结果');
}

function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
  historyCard.hidden = true;
  historyList.innerHTML = '';
  showToast('历史记录已清除');
}

// Load history on init
renderHistory();

// ============================================================
// Utilities
// ============================================================
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Keyboard shortcut: Cmd/Ctrl+Enter to generate
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    const genTab = document.getElementById('tab-generator');
    if (genTab.classList.contains('active')) {
      generateBtn.click();
    }
  }
});
