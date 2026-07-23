"""Context-aware hint engine (keyword matching, NO LLM). Returns <200ms."""
import random
from flask import Blueprint, request, jsonify

context_hint_bp = Blueprint('context_hint', __name__)

# Hint templates keyed by problem_type
HINTS = {
    'A': {
        'keywords': ['differential', 'ode', 'pde', 'continuous', 'calculus',
                     'optimization', '微分', '偏微分', '常微分', '优化', '连续'],
        'hint': '这是连续型问题。常见建模路径：1) 微分方程描述动力学 2) 变分法优化 3) 有限元数值求解。建议从 ODE/PDE 入手。',
        'actions': [{'label': '推荐连续型模型', 'payload': 'recommend_continuous'}],
    },
    'B': {
        'keywords': ['discrete', 'integer', 'combinatorial', 'scheduling', 'graph',
                     '离散', '整数规划', '组合', '调度', '路径', '图论'],
        'hint': '这是离散优化问题。推荐：整数规划 + 遗传算法/模拟退火组合使用，先求精确解再全局寻优。',
        'actions': [{'label': '推荐离散模型', 'payload': 'recommend_discrete'}],
    },
    'C': {
        'keywords': ['data', 'prediction', 'classification', 'regression', 'clustering',
                     'machine learning', '数据', '预测', '分类', '回归', '聚类', '机器学习'],
        'hint': '数据洞察题！关键步骤：1) 数据清洗和探索性分析 2) 特征工程 3) 模型选择（从简单到复杂）。建议先做 EDA 再用线性模型做 baseline。',
        'actions': [{'label': '推荐数据分析模型', 'payload': 'recommend_data'}],
    },
    'D': {
        'keywords': ['network', 'graph', 'node', 'social', '网络', '图', '节点', '社交', '传播'],
        'hint': '网络科学问题。核心：构建图模型 → 分析拓扑指标（度分布、聚类系数）→ 应用网络算法（社区检测、最短路径）。',
        'actions': [{'label': '推荐网络模型', 'payload': 'recommend_network'}],
    },
    'E': {
        'keywords': ['environment', 'sustainability', 'climate', 'pollution',
                     '环境', '可持续', '生态', '污染', '气候', '资源'],
        'hint': '可持续性问题通常需要多目标优化。建议：建立指标体系 → TOPSIS/AHP 综合评价 → 情景分析。',
        'actions': [{'label': '推荐评价模型', 'payload': 'recommend_evaluation'}],
    },
    'F': {
        'keywords': ['policy', 'economic', 'social', '政策', '经济', '社会', '管理', '评估'],
        'hint': '政策题重在论证逻辑。建议：1) 建立评价指标体系 2) AHP/DEA 分析 3) 情景模拟和敏感性分析。',
        'actions': [{'label': '推荐政策分析模型', 'payload': 'recommend_policy'}],
    },
}

COMPLETION_HINTS = [
    '框架已生成。建议检查"模型假设"部分是否包含了数据来源说明。',
    '生成完成！要不要我帮你验证一下参考文献的真实性？',
    '框架生成完毕。下一阶段可以生成完整论文，或者先做敏感性分析。',
]


@context_hint_bp.route('/api/context-hint', methods=['POST'])
def get_hint():
    data = request.get_json() or {}
    tab = data.get('tab', 'generator')
    problem_type = data.get('problem_type', '')
    problem_text = data.get('problem_text', '').lower()
    last_action = data.get('last_action', '')
    idle_seconds = data.get('idle_seconds', 0)

    hint_text = ''
    actions = []

    # 1. Problem filled but not generated
    if tab == 'generator' and problem_text and last_action == 'problem_filled':
        type_info = HINTS.get(problem_type, {})
        if type_info:
            matched = any(kw in problem_text for kw in type_info.get('keywords', []))
            if matched:
                hint_text = type_info['hint']
                actions = type_info.get('actions', [])

    # 2. Generation just completed
    if last_action == 'generation_complete':
        hint_text = random.choice(COMPLETION_HINTS)
        actions = [
            {'label': '去检查', 'payload': 'open_paper_tab'},
            {'label': '生成完整论文', 'payload': 'generate_full_paper'},
        ]

    # 3. Inactivity
    if idle_seconds > 90:
        hint_text = '看起来遇到困难了？需要我帮忙分析问题、推荐模型、或者解释某个概念吗？直接问我吧。'
        actions = [{'label': '帮我分析题目', 'payload': 'analyze_problem'}]

    # 4. Tab switch to models
    if tab == 'models' and last_action == 'tab_switch':
        hint_text = f'你正在处理 {problem_type} 题，以下是推荐模型。点击可查看详细说明和代码示例。'
        actions = [{'label': '自动筛选推荐模型', 'payload': 'filter_recommended'}]

    if not hint_text:
        hint_text = ''
        actions = []

    return jsonify({'hint_text': hint_text, 'actions': actions})
