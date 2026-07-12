# Math Modeling Assistant (MMA)

面向数学建模竞赛（美赛 MCM/ICM + 国赛 CUMCM）的智能辅助工具。

输入竞赛题目 → 获取完整论文框架、数学转编程思路、可运行 Python 代码。

## 功能

- **团队角色指南** — 建模手 / 编程手 / 写作手的职责分工与协作建议
- **论文生成器** — 输入题目，生成竞赛论文完整框架
- **数学→编程转化** — 逐条说明数学概念如何用 Python 实现
- **可运行代码** — 数据预处理、模型求解、可视化、敏感性分析

## 技术架构

```
用户输入 (题目 + 要求)
       ↓
Flask API → DeepSeek API
       ↓
Markdown 渲染 (论文框架 + 代码)
```

- **前端**: 原生 HTML/CSS/JS，零依赖框架，极简设计
- **后端**: Python Flask
- **LLM**: DeepSeek Chat，数学推理 + 代码生成，性价比极高

## 快速开始

### 1. 环境要求

- Python 3.10+
- DeepSeek API Key（在 [platform.deepseek.com](https://platform.deepseek.com) 获取，新用户送免费额度）

### 2. 安装

```bash
cd math-modeling-assistant
pip install -r requirements.txt
```

### 3. 配置 API Key

编辑 `config.py`，将 key 替换为你的 DeepSeek API Key：

```python
DEEPSEEK_API_KEY = "sk-xxx..."  # 替换为你的 key
```

### 4. 启动

```bash
python app.py
```

浏览器打开 `http://localhost:8080`

### 5. 使用

1. 在 **Paper Generator** 页面输入竞赛题目和具体要求
2. 点击「生成方案」
3. 等待约 15-30 秒，获取完整论文框架和代码
4. 切换到 **Team Roles** 页面查看团队分工指南

## 论文生成内容

每次生成包含五大部分：

| 部分 | 内容 |
|------|------|
| 问题分析 | 数学本质、涉及领域、解决思路 |
| 推荐模型 | 2-3 个候选方案对比 + 推荐 |
| 论文框架 | 摘要→重述→假设→建模→求解→结果→敏感性→评价→参考文献 |
| 数学→编程 | 数学概念与 Python 实现的对应表 |
| 完整代码 | 可运行的 Python 代码（含注释） |

## 项目结构

```
math-modeling-assistant/
├── app.py              # Flask 主程序
├── config.py           # API Key 配置
├── requirements.txt    # 依赖
├── src/
│   ├── llm_client.py   # DeepSeek API 封装 (OpenAI 兼容)
│   └── prompts.py      # System Prompt + 角色信息
├── templates/
│   └── index.html      # 前端页面
├── static/
│   ├── style.css       # 样式
│   └── script.js       # 交互逻辑
└── README.md
```

## 美赛 vs 国赛 使用建议

| 竞赛 | 特点 | 使用建议 |
|------|------|---------|
| 美赛 MCM/ICM | 英文论文，重视创意和写作 | 将生成的框架翻译为英文，补充文献综述 |
| 国赛 CUMCM | 中文论文，重视模型严谨性 | 直接使用生成框架，重点打磨模型推导部分 |

## License

MIT
