// Tab switching
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');

    if (btn.dataset.tab === 'roles' && !document.getElementById('roles-content').innerHTML.trim()) {
      loadRoles();
    }
  });
});

// Load team roles
async function loadRoles() {
  const container = document.getElementById('roles-content');
  container.innerHTML = '<p style="color:var(--text-secondary)">加载中...</p>';
  try {
    const res = await fetch('/api/roles');
    const data = await res.json();
    container.innerHTML = marked.parse(data.content);
  } catch (e) {
    container.innerHTML = '<p style="color:red">加载失败，请刷新重试</p>';
  }
}

// Generate paper
const generateBtn = document.getElementById('generate-btn');
const btnText = generateBtn.querySelector('.btn-text');
const btnLoading = generateBtn.querySelector('.btn-loading');
const resultDiv = document.getElementById('result');
const resultContent = document.getElementById('result-content');

generateBtn.addEventListener('click', async () => {
  const problem = document.getElementById('problem').value.trim();
  const requirements = document.getElementById('requirements').value.trim();

  if (!problem) {
    alert('请先输入竞赛题目');
    return;
  }

  generateBtn.disabled = true;
  btnText.hidden = true;
  btnLoading.hidden = false;
  resultDiv.classList.remove('visible');
  resultContent.innerHTML = '';

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ problem, requirements }),
    });
    const data = await res.json();

    if (data.error) {
      resultContent.innerHTML = `<p style="color:red">${data.error}</p>`;
    } else {
      resultContent.innerHTML = marked.parse(data.content);
    }
    resultDiv.classList.add('visible');
  } catch (e) {
    resultContent.innerHTML = '<p style="color:red">网络错误，请检查服务器是否运行</p>';
    resultDiv.classList.add('visible');
  } finally {
    generateBtn.disabled = false;
    btnText.hidden = false;
    btnLoading.hidden = true;
    resultDiv.scrollIntoView({ behavior: 'smooth' });
  }
});

// Copy button
document.getElementById('copy-btn').addEventListener('click', () => {
  const text = resultContent.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('copy-btn');
    btn.textContent = '已复制';
    setTimeout(() => btn.textContent = '复制全文', 1500);
  });
});
