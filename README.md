# Math Modeling Assistant (MMA)

面向数学建模竞赛（美赛 MCM/ICM + 国赛 CUMCM）的完整备赛工具。

输入竞赛题目 → 获取论文框架、数学转编程思路、可运行 Python 代码。附带 33 个模型参考库、历年真题、4 天竞赛时间线指南。

## 下载

### macOS

[**下载 MathModelingAssistant.dmg (v1.1.0)**](https://github.com/Barson0588/math-modeling-assistant/releases/download/v1.1.0/MathModelingAssistant-1.0.0.dmg)

1. 下载 DMG，双击打开，将 `MathModelingAssistant.app` 拖入 `Applications`
2. 首次启动时，应用会自动打开配置文件，填入 [DeepSeek API Key](https://platform.deepseek.com/api_keys) 后重启应用
3. 如遇到"无法验证开发者"提示，前往 **系统设置 → 隐私与安全性 → 仍要打开**

### Windows

1. 克隆仓库: `git clone https://github.com/Barson0588/math-modeling-assistant.git`
2. 安装依赖: `pip install pyinstaller -r requirements.txt`
3. 运行 `win_build.bat`
4. 在 `dist\MathModelingAssistant\` 中找到 `MathModelingAssistant.exe`，双击运行
5. 首次启动时会弹出配置文件，填入 [DeepSeek API Key](https://platform.deepseek.com/api_keys) 后重启应用

> 更多版本见 [Releases 页面](https://github.com/Barson0588/math-modeling-assistant/releases)

## 功能

| Tab | 功能 |
|-----|------|
| **Generator** | 选择竞赛类型和题型，输入题目 → 生成完整论文方案 + AI 使用报告 + LaTeX 模板 |
| **Paper** | 生成完整学术论文，A4 排版预览，支持编辑、AI 查重、引用验证、数学推导复核 |
| **Models** | 33 个数学模型速查库，支持按类别/题型/难度筛选和关键词搜索 |
| **Problems** | 2000-2024 美赛 & 国赛真题，点击即可填入生成器 |
| **Guide** | 4 天竞赛时间线、推荐工具链、提交前检查清单 |
| **Roles** | 建模手/编程手/写作手的分工 + 每日详细任务 + 协作检查点 |

## 技术架构

```
用户输入 (题目 + 要求)
       ↓
Flask API → DeepSeek API (deepseek-chat)
       ↓
Markdown 渲染 (论文框架 + 数学转编程 + Python 代码)
```

- **前端**: 原生 HTML/CSS/JS，零框架依赖，5-tab 单页应用
- **后端**: Python Flask，8 个 RESTful API 路由
- **LLM**: DeepSeek Chat，OpenAI 兼容接口，数学推理 + 代码生成

## 快速开始

### 1. 环境要求

- Python 3.10+
- DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com) 注册即送免费额度）

### 2. 克隆并安装

```bash
git clone https://github.com/Barson0588/math-modeling-assistant.git
cd math-modeling-assistant
pip install -r requirements.txt
```

### 3. 配置 API Key

在项目根目录创建 `.env` 文件：

```bash
echo 'DEEPSEEK_API_KEY=sk-你的密钥' > .env
```

或手动新建 `.env`，写入：

```
DEEPSEEK_API_KEY=sk-你的密钥
```

### 4. 启动

```bash
python app.py
```

浏览器打开 **http://localhost:8080**。

### 5. 使用流程

1. **Generator** — 选择竞赛类型（美赛/国赛）和题型（A-F），粘贴题目，点击「生成论文方案」
2. 等待 15-30 秒，获取完整论文框架、数学→编程转化表、Python 代码
3. 点击「生成 AI 使用报告」获取 COMAP 要求的 AI Use Report
4. 点击「LaTeX 模板」获取论文排版模板
5. **Models** 页面可速查 33 个模型的原理、适用场景、Python 库
6. **Problems** 页面点击任意真题可自动填入生成器

## 生成内容

| 部分 | 内容 |
|------|------|
| 问题分析 | 数学本质、涉及领域、整体思路 |
| 推荐模型方案 | 2-3 个候选方案对比 + 推荐理由 |
| 论文框架 | 摘要→重述→假设→符号→建模→求解→结果→敏感性→评价→结论→参考文献 |
| 数学→编程转化 | 数学概念与 Python 实现的逐条对应表 |
| 完整 Python 代码 | 数据预处理、模型实现、可视化、敏感性分析（含注释） |

## 项目结构

```
math-modeling-assistant/
├── app.py                 # Flask 主程序
├── config.py              # 配置 (从 .env 读取 API Key)
├── launcher.py            # macOS App 启动器
├── mac_build.spec         # macOS PyInstaller 打包配置
├── mac_build.sh           # macOS DMG 构建脚本
├── launcher_win.pyw       # Windows 启动器 (无控制台)
├── win_build.spec         # Windows PyInstaller 打包配置
├── win_build.bat          # Windows EXE 构建脚本
├── requirements.txt       # Python 依赖
├── .env                   # API Key (git ignored)
├── src/
│   ├── llm_client.py      # DeepSeek API 封装 (OpenAI 兼容)
│   ├── prompts.py         # System Prompt + 生成 Prompt
│   ├── models_data.py     # 33 个数学模型数据
│   ├── problems_data.py   # 历年真题数据
│   ├── guide_data.py      # 竞赛指南数据
│   └── scholar.py         # Semantic Scholar API 封装
├── templates/
│   └── index.html         # 前端页面 (6-tab SPA)
├── static/
│   ├── style.css          # 样式 (深色模式)
│   ├── script.js          # 交互逻辑
│   ├── sw.js              # Service Worker (PWA)
│   └── manifest.json      # PWA manifest
└── README.md
```

## 美赛 vs 国赛

| 竞赛 | 语言 | 特点 | 使用建议 |
|------|------|------|---------|
| MCM/ICM | 英文 | 重视创新与写作，25 页限制，需 AI Use Report | 选择 MCM/ICM 选项，生成英文框架 |
| CUMCM | 中文 | 重视模型严谨性和推导，无页数限制 | 选择 CUMCM 选项，生成中文框架 |

## License

MIT
