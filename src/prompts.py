# ============================================================
# Team Roles — 升级版（4天时间线 + 每日任务 + 协作检查点）
# ============================================================

ROLES_INFO = """
## 数学建模竞赛 — 团队角色与 4 天协作指南

### 三位成员

#### 建模手 (Modeler)
- **核心任务**：理解题目本质 → 选择数学模型 → 推导公式 → 设计求解框架
- **每日重点**：
  - Day 1：评估所有题目的数学难度，确定选题 + 候选模型
  - Day 2：完整推导模型公式，与编程手对齐算法逻辑
  - Day 3：设计敏感性分析方案，判断是否需要修正模型
  - Day 4：审核全文数学正确性，确保公式符号统一
- **核心能力**：微积分、线性代数、概率统计、常微分方程、最优化理论

#### 编程手 (Programmer)
- **核心任务**：数据处理 → 模型实现 → 求解优化 → 可视化 → 敏感性分析
- **每日重点**：
  - Day 1：查找相关代码库和数据集，搭建开发环境
  - Day 2：实现核心算法，跑出第一版结果
  - Day 3：敏感性分析代码，可视化美化
  - Day 4：整理附录代码，确保可复现
- **核心能力**：Python(numpy/scipy/pandas/sklearn)、MATLAB、算法实现、数据可视化
- **代码规范**：
  - `numpy.random.seed(42)` 确保可复现
  - 每个函数写 docstring
  - 图表 300dpi、标注完整、灰度友好

#### 写作手 (Writer)
- **核心任务**：论文撰写 → 图表设计 → 排版美化 → 摘要打磨
- **每日重点**：
  - Day 1：准备 LaTeX 模板，写问题重述和背景草稿
  - Day 2：完成假设、符号说明，整理模型推导成论文格式
  - Day 3：写结果分析和敏感性分析章节，画流程图
  - Day 4：摘要至少修改 8 稿，全文润色，格式统一
- **核心能力**：学术写作、LaTeX 排版、逻辑表达、英文写作（美赛）

### 关键协作规则

1. **摘要三人共同打磨**：摘要是评审第一印象，占比 70%+
2. **建模与编程同步**：建模手推导公式时，编程手在旁边确认可实现性
3. **写作手从 Day 1 就参与**：边做边写，最后一天只做润色不写新内容
4. **每天 22:00 检查点**：三人对齐进度，解决分歧
5. **所有图表必须配文字解读**：揭示趋势机理，不只展示数字
"""

# ============================================================
# System Prompts — 按竞赛类型分化
# ============================================================

SYSTEM_MCM_EN = """You are an MCM/ICM Outstanding Winner coach. You help teams write competition papers that follow COMAP's strict standards.

Your task:
1. Analyze the problem and identify the mathematical essence
2. Recommend 2-3 viable models with trade-off comparison
3. Generate a complete paper framework following MCM format
4. Provide math-to-code transformation guidance
5. Provide complete, runnable Python code with comments

Critical MCM paper requirements:
- Summary (Abstract): standalone, 200-250 words, NO formulas, NO citations, include quantified results
- Introduction & Restatement
- Assumptions with Justification (5-7 assumptions, each with reason)
- Notation Table (alphabetical order)
- Model Development (conceptual → mathematical → computational three-layer narrative)
- Model Solution & Implementation
- Results Analysis (EVERY figure/table must have deep textual interpretation)
- Sensitivity Analysis (perturb key parameters ±15%, show stability)
- Model Evaluation (Strengths & Weaknesses with honest assessment)
- Conclusion
- References (APA 7th edition, 15-20 authoritative sources)
- Appendix (code, derivations — counts toward 25-page limit)
- AI Use Report (REQUIRED for 2024-2025)

Writing rules:
- Past tense for modeling process, present tense for conclusions
- Third-person passive voice preferred
- Figures: title BELOW, Tables: title ABOVE
- All axes labeled with quantity AND unit
- Times New Roman, ≥10pt, 300dpi charts
- NO Chinese characters — all English

Format all math formulas in LaTeX notation."""

SYSTEM_MCM_CN = """你是一位美赛(MCM/ICM) O奖指导教练，同时也是国赛(CUMCM)国奖教练。

任务：
1. 分析题目的数学本质并确定所属领域
2. 推荐 2-3 个可行模型方案，对比优劣
3. 生成完整论文框架（符合对应竞赛格式）
4. 提供数学问题 → 编程实现的详细转化思路
5. 提供可直接运行的 Python 代码

美赛 vs 国赛关键差异：
- 美赛：英文论文，重视创新与写作表达，25页限制（含附录），需要 AI Use Report
- 国赛：中文论文，重视模型严谨性和推导过程，无页数限制但讲究精炼

论文核心要求：
- 摘要单独成页，无公式无引用，必须包含量化结果
- 模型假设每次一个，附带合理性解释
- 所有图表必须有深度文字解读
- 必须做敏感性分析（参数 ±15% 扰动）
- 数学公式使用 LaTeX 格式

这是{contest_type}的{problem_type}题型。{language_instruction}"""

SYSTEM_AI_REPORT = """You are helping a team write the AI Use Report required by COMAP for MCM/ICM 2024-2025.

According to COMAP's new rules, teams using generative AI MUST submit a detailed AI Use Report that does NOT count toward the 25-page limit.

Generate a complete AI Use Report that covers:

1. **AI Tools Used**: List all AI tools used (ChatGPT, Claude, DeepSeek, etc.) with specific model names
2. **Purpose of Use**: For each tool, describe exactly what it was used for (brainstorming, code debugging, translation, literature search, etc.)
3. **How AI Output Was Used**: Explain how the team verified, modified, and integrated AI-generated content
4. **What AI Was NOT Used For**: Explicitly state that AI was NOT used for core modeling decisions, innovative arguments, or conclusions
5. **Team's Own Contributions**: Emphasize that all mathematical derivations, model choices, result interpretations, and conclusions are the team's original work

The report should be honest, transparent, and demonstrate responsible AI use. Format in formal English."""

# ============================================================
# Generation Prompts
# ============================================================

PAPER_PROMPT = """请根据以下数学建模竞赛题目，生成完整的解决方案。

## 竞赛类型
{contest_type}

## 题目类型
{problem_type} — {problem_category}

## 题目
{problem}

## 具体要求
{requirements}

{language_block}

请按以下结构输出（Markdown 格式）：

### 一、问题分析
- 问题的核心数学本质
- 涉及的数学领域（微分方程 / 优化 / 统计 / 图论 / ...）
- 整体解决思路概述

### 二、推荐模型方案

给出 2~3 个可行方案，每个方案说明：
- **模型原理**（一句话）
- **优势**
- **劣势**
- **适用性**

最后给出**推荐方案**及理由。

### 三、论文框架（逐章详细指导）

**1. 摘要**
- 一句话概括问题
- 简述使用的方法
- 给出核心量化结果（用占位符 [待填充]）
- {abstract_note}

**2. 问题重述**
- 用自己的话重新表述问题
- 明确需要解决的关键子问题
- 说明问题的重要性和实际背景

**3. 模型假设与符号说明**
- 列出 5-7 个关键假设，每个附合理性解释
- 符号表（按字母顺序）

**4. 模型建立**
- 概念模型：输入 → 处理 → 输出的逻辑链
- 数学模型：公式推导（LaTeX 格式）
- 计算模型：算法步骤

**5. 模型求解**
- 算法流程图逻辑（文字描述）
- 使用的软件和库
- 关键参数设置

**6. 结果分析**
- 数据可视化建议（图表类型和内容）
- 结果解读方向
- 横向对比建议

**7. 敏感性分析**
- 关键参数的敏感性检验方案
- 单因素分析和多因素分析建议
- 如何判断模型鲁棒性

**8. 模型评价与改进**
- 模型的优点（3-4 条）
- 模型的局限性（诚实评价 3-4 条）
- 改进方向

**9. 参考文献**
- 建议引用的文献类型和数量
- {ref_note}

### 四、数学问题 → 编程转化

| 数学概念 | 编程实现 | Python 库/方法 |
|----------|---------|---------------|
| （逐条列出） | （算法描述） | （具体库和函数） |

### 五、完整 Python 代码

提供可直接运行的 Python 代码，要求：
- 包含必要的 import 语句
- 数据预处理部分（模拟合理数据）
- 模型核心实现（函数分离，有 docstring）
- 求解与优化
- 可视化（规范的图表标注）
- 敏感性分析代码
- 设置随机种子确保可复现

代码需有清晰的中文或英文注释，可直接复制到 Jupyter Notebook 运行。
"""

AI_REPORT_PROMPT = """Generate a complete AI Use Report for an MCM/ICM paper about the following problem:

## Problem
{problem}

The team used {tools_used} during the competition.

Generate a formal AI Use Report that:
1. Lists each AI tool used and its specific purpose
2. Describes how AI outputs were verified and modified
3. Clearly states what AI was NOT used for
4. Affirms the team's ownership of all core intellectual contributions

The report should be honest, transparent, and follow COMAP's AI Use Report guidelines.
"""

# ============================================================
# LaTeX Template
# ============================================================

LATEX_TEMPLATE = r"""\documentclass[12pt]{article}
\usepackage[utf8]{inputenc}
\usepackage{amsmath, amssymb, amsthm}
\usepackage{graphicx, subcaption}
\usepackage{booktabs, multirow, array}
\usepackage{hyperref, geometry, setspace, enumerate}
\usepackage[numbers]{natbib}
\usepackage{fancyhdr}
\geometry{margin=1in}
\setlength{\parskip}{0.5em}
\setlength{\parindent}{0em}
\pagestyle{fancy}
\fancyhf{}
\rhead{Team \#\rule{1.5cm}{0.15mm}}
\lhead{\thepage}
\renewcommand{\headrulewidth}{0.4pt}

\title{REPLACE_WITH_TITLE}
\author{}
\date{}

\begin{document}
\maketitle
\begin{center}
\textbf{Summary}
\end{center}

% === SUMMARY (200-250 words, no formulas, no citations) ===
REPLACE_WITH_SUMMARY

\newpage
\tableofcontents
\newpage

% === 1. INTRODUCTION ===
\section{Introduction}
REPLACE_WITH_INTRODUCTION

% === 2. ASSUMPTIONS AND JUSTIFICATIONS ===
\section{Assumptions and Justifications}
\begin{enumerate}
    \item \textbf{Assumption 1:} REPLACE \textit{Justification:} REPLACE
    \item \textbf{Assumption 2:} REPLACE \textit{Justification:} REPLACE
\end{enumerate}

% === 3. NOTATION ===
\section{Notation}
\begin{table}[h]
\centering
\begin{tabular}{c | l | l}
    \toprule
    \textbf{Symbol} & \textbf{Definition} & \textbf{Unit} \\
    \midrule
    $x$ & REPLACE & REPLACE \\
    \bottomrule
\end{tabular}
\end{table}

% === 4. MODEL DEVELOPMENT ===
\section{Model Development}
\subsection{Conceptual Model}
REPLACE

\subsection{Mathematical Formulation}
\begin{align}
    \text{Objective:} \quad & \min \; f(x) \\
    \text{Subject to:} \quad & g_i(x) \leq 0, \quad i = 1, 2, \ldots, m
\end{align}

% === 5. MODEL SOLUTION ===
\section{Model Solution and Implementation}
REPLACE

% === 6. RESULTS ANALYSIS ===
\section{Results and Analysis}
REPLACE

% === 7. SENSITIVITY ANALYSIS ===
\section{Sensitivity Analysis}
REPLACE

% === 8. MODEL EVALUATION ===
\section{Model Evaluation}
\subsection{Strengths}
\begin{itemize}
    \item REPLACE
\end{itemize}
\subsection{Weaknesses and Improvements}
\begin{itemize}
    \item REPLACE
\end{itemize}

% === 9. CONCLUSION ===
\section{Conclusion}
REPLACE

% === REFERENCES ===
\bibliographystyle{plainnat}
\begin{thebibliography}{99}
\bibitem{ref1} REPLACE
\end{thebibliography}

% === APPENDIX ===
\appendix
\section{Code Listing}
REPLACE_WITH_CODE

\end{document}
"""
