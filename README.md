# Math Modeling Assistant (MMA)

面向数学建模竞赛（美赛 MCM/ICM + 国赛 CUMCM）的完整备赛工具。

输入竞赛题目 → 获取论文框架、数学转编程思路、可运行 Python 代码。附带 33 个模型参考库、历年真题、4 天竞赛时间线指南。

## 使用方式

支持三种使用方式，按推荐度排序：

| 方式 | 适合 | 说明 |
|------|------|------|
| **云端网页** | 任何人 | 无需安装，打开浏览器即用 |
| **手机 PWA** | iOS / Android | 网页添加到主屏幕，像 App 一样使用 |
| **桌面打包** | macOS / Windows | 离线使用，无需 Python 环境 |

---

## 方式一：云端网页（推荐）

访问部署在 Railway 上的公开地址即可使用。

> 需要自行配置 DeepSeek API Key（首次访问时会弹出配置窗口）。
> Key 存储在浏览器本地，不会上传到服务器。
>
> 免费获取 Key：[platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys)

---

## 方式二：手机端使用（PWA）

### iPhone / iPad

1. Safari 打开云端网页地址
2. 点击底部 **分享按钮**（方框箭头图标）
3. 滑动找到 **添加到主屏幕** → 点击"添加"
4. 主屏幕出现 MMA 图标，点击即可像 App 一样使用

### Android

1. Chrome 打开云端网页地址
2. 第 3 次访问时会弹出安装横幅，点击 **"将此应用添加到主屏幕"**
3. 或手动：右上角菜单 → **添加到主屏幕**

> PWA 特性：支持离线访问（模型库、真题库、指南页断网仍可查看）、全屏模式、自动适配手机屏幕。

---

## 方式三：桌面打包

### macOS

[**下载 MathModelingAssistant.dmg (v1.1.0)**](https://github.com/Barson0588/math-modeling-assistant/releases/download/v1.1.0/MathModelingAssistant-1.0.0.dmg)

1. 下载 DMG，双击打开，将 `MathModelingAssistant.app` 拖入 `Applications`
2. 首次启动时填入 [DeepSeek API Key](https://platform.deepseek.com/api_keys)
3. 如遇到"无法验证开发者"提示，前往 **系统设置 → 隐私与安全性 → 仍要打开**

### Windows — 一键打包

```bash
# 1. 克隆仓库
git clone https://github.com/Barson0588/math-modeling-assistant.git
cd math-modeling-assistant

# 2. 安装依赖
pip install pyinstaller -r requirements.txt

# 3. 一键打包（自动检测平台，生成单个 .exe）
python build.py

# 4. 在 dist\ 目录下找到 MathModelingAssistant.exe，双击运行
```

> `build.py` 会自动选择 `win_build.spec`，输出到 `dist/` 目录。首次运行时会弹出配置窗口填入 API Key。

**或使用传统方式：**

```bash
pip install pyinstaller -r requirements.txt
win_build.bat
# 在 dist\MathModelingAssistant\ 中找到 .exe
```

---

## 功能

| Tab | 功能 |
|-----|------|
| **Generator** | 选择竞赛类型和题型，输入题目 → 生成完整论文方案 + AI 使用报告 + LaTeX 模板 |
| **Paper** | 生成完整学术论文，A4 排版预览，支持编辑、AI 查重、引用验证、数学推导复核 |
| **Models** | 33 个数学模型速查库，支持按类别/题型/难度筛选和关键词搜索 |
| **Problems** | 2000-2024 美赛 & 国赛真题，点击即可填入生成器 |
| **Guide** | 4 天竞赛时间线、推荐工具链、代码规范、提交前检查清单 |
| **Roles** | 建模手/编程手/写作手的分工 + 每日详细任务 + 协作检查点 |

---

## 技术架构

```
用户输入 → Flask API → DeepSeek API (deepseek-chat)
                           ↓
              Markdown 渲染（论文框架 + 数学转编程 + Python 代码）
```

- **前端**：原生 HTML/CSS/JS，零框架依赖，6-tab 单页应用，PWA 支持
- **后端**：Python Flask + gunicorn，25+ RESTful API 路由
- **LLM**：DeepSeek Chat，OpenAI 兼容接口
- **部署**：Railway（云端）+ PyInstaller（桌面）

---

## 本地开发

### 环境要求

- Python 3.10+
- DeepSeek API Key（[免费获取](https://platform.deepseek.com/api_keys)）

### 启动

```bash
git clone https://github.com/Barson0588/math-modeling-assistant.git
cd math-modeling-assistant
pip install -r requirements.txt

# 配置 API Key（二选一）
echo 'DEEPSEEK_API_KEY=sk-你的密钥' > .env   # 方式1：.env 文件
# 或启动后在网页设置弹窗中填入                           # 方式2：网页配置

python app.py
# 浏览器打开 http://localhost:8080
```

---

## 项目结构

```
math-modeling-assistant/
├── app.py                 # Flask 主程序
├── build.py               # 统一打包脚本（自动检测 macOS/Windows）
├── Procfile               # Railway 部署配置
├── railway.json           # Railway 构建配置
├── requirements.txt       # Python 依赖
├── src/
│   ├── llm_client.py      # DeepSeek API 封装
│   ├── prompts.py         # System Prompt + 生成 Prompt（COMAP 评审标准对齐）
│   ├── models_data.py     # 33 个数学模型数据
│   ├── problems_data.py   # 历年真题数据
│   ├── guide_data.py      # 竞赛指南 + 提交检查清单
│   └── scholar.py         # Semantic Scholar API（真实文献检索）
├── templates/
│   └── index.html         # 前端页面（6-tab SPA + API Key 弹窗 + PWA）
├── static/
│   ├── style.css          # 样式（暗色模式 + 响应式 + 动画系统）
│   ├── script.js          # 交互逻辑（历史管理 / 流式生成 / Explain / Scholar）
│   ├── sw.js              # Service Worker（PWA 离线缓存）
│   ├── manifest.json      # PWA manifest
│   └── offline.html       # 离线回退页面
└── README.md
```

---

## License

MIT
