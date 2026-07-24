import json
import logging
import os
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from src.prompts import (
    ROLES_INFO, SYSTEM_MCM_EN, SYSTEM_MCM_CN, SYSTEM_AI_REPORT,
    PAPER_PROMPT, AI_REPORT_PROMPT, LATEX_TEMPLATE,
    SYSTEM_PAPER, PAPER_FULL_PROMPT, SYSTEM_EXPLAIN, PAPER_LATEX_PROMPT,
    SYSTEM_MATH_VERIFY, SYSTEM_PLAGIARISM,
    SYSTEM_ABSTRACT_REFINE, ABSTRACT_REFINE_PROMPT,
    SYSTEM_SENSITIVITY, SENSITIVITY_PROMPT,
    SYSTEM_PAPER_SCORING, PAPER_SCORING_PROMPT,
    SYSTEM_MODEL_RECOMMEND, MODEL_RECOMMEND_PROMPT,
    SYSTEM_FIGURE_SUGGEST, FIGURE_SUGGEST_PROMPT,
    SYSTEM_PAPER_COMPARE, PAPER_COMPARE_PROMPT,
    SYSTEM_PAPER_ANALYZE, PAPER_ANALYZE_PROMPT,
    SYSTEM_MOCK_REVIEW, MOCK_REVIEW_PROMPT,
    SYSTEM_DEDUP,
    SYSTEM_BLUEPRINT, USER_BLUEPRINT,
    SYSTEM_MATH_CORE, USER_MATH_CORE,
    SYSTEM_PAPER_FINAL, USER_PAPER_FINAL,
    SYSTEM_POST_VALIDATE, USER_POST_VALIDATE,
)
from datetime import date
from src.llm_client import generate_response, generate_stream, run_tool_loop
from src.models_data import MODELS
from src.problems_data import PROBLEMS
from src.guide_data import GUIDE
from src.scholar import search_by_keywords, search_papers, format_reference_apa, format_references_apa
from src.auth import auth_bp, get_current_user, decrypt_api_key
from src.db import init_db
from src.dedup_ast import LayoutPreservingDeduper
from src.citation_grounding import (
    CitationGroundingAgent,
    SEARCH_ACADEMIC_PAPER_TOOL,
    CITATION_TOOL_EXECUTORS,
    SYSTEM_CITATION_AGENT,
)
from src.paper_pipeline import run_pipeline
import config  # load .env and provide DEEPSEEK_API_KEY fallback

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB 请求体限制

from flask_cors import CORS
CORS(app, supports_credentials=True, origins=["https://math-modeling-assistant.up.railway.app"])

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per minute", "600 per hour"],
    storage_uri="memory://",
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app.register_blueprint(auth_bp)

from src.routes.history import history_bp
from src.routes.context_hint import context_hint_bp
app.register_blueprint(history_bp)
app.register_blueprint(context_hint_bp)

# Initialize database on startup
init_db()


# ── Background Task Manager ──────────────────────────────────────────────
# Heavy operations (AST dedup, plagiarism check) run as background tasks
# so they survive page closes and report progress in real-time.

import uuid
import threading
import time as _time

class TaskManager:
    def __init__(self):
        self._tasks = {}
        self._lock = threading.Lock()

    def create(self, task_type, run_fn, *args, **kwargs):
        task_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._tasks[task_id] = {
                'type': task_type,
                'status': 'running',
                'progress': 0,
                'stage': '准备中...',
                'result': None,
                'error': None,
                'created_at': _time.time(),
            }
        thread = threading.Thread(target=self._run, args=(task_id, run_fn, args, kwargs), daemon=True)
        thread.start()
        return task_id

    def _run(self, task_id, run_fn, args, kwargs):
        try:
            result = run_fn(*args, **kwargs, _task_id=task_id, _update_progress=self._make_updater(task_id))
            with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id]['status'] = 'done'
                    self._tasks[task_id]['progress'] = 100
                    self._tasks[task_id]['stage'] = '完成'
                    self._tasks[task_id]['result'] = result
        except Exception as e:
            with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id]['status'] = 'error'
                    self._tasks[task_id]['error'] = str(e)[:500]

    def _make_updater(self, task_id):
        def update(progress, stage):
            with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id]['progress'] = progress
                    self._tasks[task_id]['stage'] = stage
        return update

    def get(self, task_id):
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                return None
            return {
                'status': t['status'],
                'progress': t['progress'],
                'stage': t['stage'],
                'result': t['result'],
                'error': t['error'],
            }

    def cleanup_old(self, max_age=3600):
        now = _time.time()
        with self._lock:
            stale = [tid for tid, t in self._tasks.items() if now - t['created_at'] > max_age]
            for tid in stale:
                del self._tasks[tid]

task_manager = TaskManager()


def _heartbeat_progress(_update_progress, start_pct, end_pct, duration_sec, stage_text):
    """Spawn a daemon thread that slowly increments progress from start_pct
    to end_pct over duration_sec, so the user sees continuous movement
    during long-blocking API calls.

    Returns a threading.Event — set it to stop the heartbeat early.
    """
    if not _update_progress:
        return None
    stop = threading.Event()
    steps = max(1, int(duration_sec / 1.2))  # update ~every 1.2s
    increment = (end_pct - start_pct) / steps

    def _beat():
        current = start_pct
        for _ in range(steps):
            if stop.is_set():
                return
            current += increment
            try:
                _update_progress(min(int(current), end_pct), stage_text)
            except Exception:
                pass
            stop.wait(1.2)
        try:
            _update_progress(end_pct, stage_text)
        except Exception:
            pass

    threading.Thread(target=_beat, daemon=True).start()
    return stop


def _get_api_key():
    """Read API key from request header, server-side stored key, or env var."""
    header_key = request.headers.get("X-API-Key", "").strip()
    if header_key:
        return header_key
    # Try server-side stored key for logged-in users
    user = get_current_user()
    if user and user['encrypted_api_key']:
        key = decrypt_api_key(user['encrypted_api_key'])
        if key:
            return key
    # Fallback: local .env for desktop builds
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _get_language_config(contest_type):
    """根据竞赛类型返回语言相关配置，消除各路由中的重复代码。"""
    if contest_type == "CUMCM":
        return {
            "language_instruction": "使用中文撰写论文框架，按国赛格式。",
            "language_block": "",
            "abstract_note": "中文摘要 300 字左右，单独成页",
            "ref_note": "建议引用 10-15 篇中文核心文献",
            "system_prompt_template": SYSTEM_MCM_CN,
            "paper_title_placeholder": "数学建模竞赛论文",
        }
    else:
        return {
            "language_instruction": "Write the complete paper in ENGLISH. Follow MCM/ICM standards strictly.",
            "language_block": "**IMPORTANT: Generate the paper framework in ENGLISH. Follow MCM/ICM standards strictly.**",
            "abstract_note": "English summary, 200-250 words, standalone page, NO formulas or citations",
            "ref_note": "Suggest 15-20 authoritative English references in APA 7th edition",
            "system_prompt_template": None,
            "paper_title_placeholder": "MCM/ICM Competition Paper",
        }


def _strip_code_fences(text):
    """Remove markdown code fences from AI-generated text that wraps content in ``` or ```text blocks."""
    import re
    text = text.strip()
    # Remove leading ```text or ```language and trailing ```
    text = re.sub(r'^```(?:text|markdown|plain|md)?\s*\n', '', text)
    text = re.sub(r'\n```\s*$', '', text)
    return text.strip()


# ===== Context Processor =====

@app.context_processor
def inject_globals():
    offline = not os.environ.get('RAILWAY_ENV') and not os.environ.get('DEEPSEEK_API_KEY')
    return {'offline_mode': offline}


# ===== Page Routes =====

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/register")
def register_page():
    return render_template("register.html")

# ===== API: Background Tasks =====

@app.route("/api/tasks/<task_id>")
def get_task_status(task_id):
    info = task_manager.get(task_id)
    if info is None:
        return jsonify({"error": "任务不存在或已过期"}), 404
    return jsonify(info)


@app.route("/api/tasks/deduplicate-ast", methods=["POST"])
@limiter.limit("8 per minute")
def create_dedup_ast_task():
    data = request.get_json()
    content = data.get("content", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400
    if len(content) < 200:
        return jsonify({"error": "论文内容过短，至少需要 200 字"}), 400

    def _run_dedup_ast(content, contest_type, _task_id=None, _update_progress=None):
        deduper = LayoutPreservingDeduper()
        deduper.parse(content)
        segments = deduper.extract_text_segments()
        if not segments:
            return {"content": content, "note": "No text segments to rewrite."}

        lang = "Chinese" if contest_type == "CUMCM" else "English"
        rewritten_map = {}
        batch_size = 5
        total_batches = (len(segments) + batch_size - 1) // batch_size

        import re as _re4
        for batch_idx, batch_start in enumerate(range(0, len(segments), batch_size)):
            batch = segments[batch_start:batch_start + batch_size]
            progress = int((batch_idx / total_batches) * 95)
            if _update_progress:
                _update_progress(progress, f'正在改写第 {batch_idx + 1}/{total_batches} 批 ({batch_start + 1}-{min(batch_start + len(batch), len(segments))}/{len(segments)} 段)')

            prompt_parts = []
            for seg in batch:
                header = seg.get('context_header', '')
                header_info = f" (section: {header})" if header else ""
                prompt_parts.append(f"<segment id={seg['id']}{header_info}>\n{seg['text']}\n</segment>")

            user_prompt = f"""Rewrite the following text segments from a mathematical modeling paper to reduce plagiarism risk.

Language: {lang}

CRITICAL RULES:
1. Rewrite each segment thoroughly — restructure sentences, use different vocabulary, vary academic phrasing.
2. Preserve ALL placeholders of the form ⟨⟨PROTECTED_N⟩⟩ exactly as they appear — these are atomic tokens representing formulas, images, or code. NEVER modify, remove, or reorder them.
3. Keep the original meaning and technical accuracy.
4. Output each rewritten segment in the same order, wrapped in <segment id=N>...</segment> tags.

Segments to rewrite:

{chr(10).join(prompt_parts)}"""

            result = generate_response(
                "You are an academic writing expert. Rewrite text to reduce plagiarism risk while preserving meaning. Always preserve ⟨⟨PROTECTED_N⟩⟩ markers verbatim.",
                user_prompt, max_tokens=4000, api_key=_get_api_key()
            )

            seg_pattern = _re4.compile(r'<segment\s+id\s*=\s*(\d+)\s*>(.*?)</segment\s*>', _re4.DOTALL)
            for m in seg_pattern.finditer(result):
                sid = int(m.group(1))
                rewritten_map[sid] = m.group(2).strip()
            for seg in batch:
                if seg['id'] not in rewritten_map:
                    rewritten_map[seg['id']] = seg['text']

        if _update_progress:
            _update_progress(97, '正在重新组装文档...')
        final = deduper.apply_and_render(rewritten_map)
        return {"content": final, "mode": "ast"}

    task_id = task_manager.create('dedup-ast', _run_dedup_ast, content, contest_type)
    return jsonify({"task_id": task_id})


@app.route("/api/tasks/check-plagiarism", methods=["POST"])
@limiter.limit("8 per minute")
def create_plagiarism_task():
    data = request.get_json()
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "请提供论文内容"}), 400
    if len(content) < 200:
        return jsonify({"error": "论文内容过短，至少需要 200 字"}), 400

    analysis_text = content[:5000]
    user_prompt = f"""Please analyze the following mathematical modeling paper for originality and plagiarism risks.

{analysis_text}

Provide a section-by-section originality assessment with specific flagged passages and rewrite suggestions."""

    def _run_plagiarism(content, analysis_text, user_prompt, _task_id=None, _update_progress=None):
        if _update_progress:
            _update_progress(10, '正在提取文本片段...')
        result = generate_response(SYSTEM_PLAGIARISM, user_prompt, max_tokens=2000, api_key=_get_api_key())
        if _update_progress:
            _update_progress(100, '分析完成')
        return {"content": result}

    task_id = task_manager.create('plagiarism', _run_plagiarism, content, analysis_text, user_prompt)
    return jsonify({"task_id": task_id})


# ===== API: Team Roles =====

@app.route("/api/roles")
def get_roles():
    return jsonify({"content": ROLES_INFO})


# ===== API: Model Library =====

@app.route("/api/models")
def get_models():
    category = request.args.get("category", "")
    mcm_type = request.args.get("mcm_type", "")
    difficulty = request.args.get("difficulty", "")
    search = request.args.get("search", "").lower()

    results = MODELS
    if category:
        results = [m for m in results if m["category"] == category]
    if mcm_type:
        results = [m for m in results if mcm_type in m["mcm_type"]]
    if difficulty:
        results = [m for m in results if m["difficulty"] == difficulty]
    if search:
        results = [
            m for m in results
            if search in m["name"].lower()
            or search in m["summary"].lower()
            or any(search in t.lower() for t in m["tags"])
        ]

    categories = sorted(set(m["category"] for m in MODELS))
    return jsonify({
        "models": results,
        "categories": categories,
        "total": len(results),
    })


@app.route("/api/models/<model_name>")
def get_model_detail(model_name):
    for m in MODELS:
        if m["name"] == model_name:
            return jsonify(m)
    return jsonify({"error": "模型未找到"}), 404


# ===== API: Real Problems =====

@app.route("/api/problems")
def get_problems():
    contest = request.args.get("contest", "")
    year = request.args.get("year", "")
    mcm_type = request.args.get("type", "")

    results = PROBLEMS
    if contest:
        results = [p for p in results if p["contest"] == contest]
    if year:
        results = [p for p in results if str(p["year"]) == year]
    if mcm_type:
        results = [p for p in results if p["type"] == mcm_type]

    contests = sorted(set(p["contest"] for p in PROBLEMS))
    years = sorted(set(p["year"] for p in PROBLEMS), reverse=True)
    return jsonify({
        "problems": results,
        "contests": contests,
        "years": years,
        "total": len(results),
    })


# ===== API: Competition Guide =====

@app.route("/api/guide")
def get_guide():
    return jsonify(GUIDE)


# ===== API: Paper Generation =====

@app.route("/api/generate", methods=["POST"])
@limiter.limit("5 per minute")
def generate():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    requirements = data.get("requirements", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    problem_type = data.get("problem_type", "A")
    problem_category = data.get("problem_category", "连续型")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    lc = _get_language_config(contest_type)
    if lc["system_prompt_template"]:
        system_prompt = lc["system_prompt_template"].format(
            contest_type="国赛 CUMCM",
            problem_type=problem_type,
            language_instruction=lc["language_instruction"],
        )
    else:
        system_prompt = SYSTEM_MCM_EN

    user_prompt = PAPER_PROMPT.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=problem,
        requirements=requirements or "无特殊要求",
        language_block=lc["language_block"],
        abstract_note=lc["abstract_note"],
        ref_note=lc["ref_note"],
    )

    try:
        result = generate_response(system_prompt, user_prompt, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("generate failed: %s", e, exc_info=True)
        return jsonify({"error": "生成失败，请稍后重试"}), 500


@app.route("/api/generate/stream", methods=["POST"])
@limiter.limit("3 per minute")
def generate_stream_endpoint():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    requirements = data.get("requirements", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    problem_type = data.get("problem_type", "A")
    problem_category = data.get("problem_category", "连续型")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    lc = _get_language_config(contest_type)
    if lc["system_prompt_template"]:
        system_prompt = lc["system_prompt_template"].format(
            contest_type="国赛 CUMCM",
            problem_type=problem_type,
            language_instruction=lc["language_instruction"],
        )
    else:
        system_prompt = SYSTEM_MCM_EN

    user_prompt = PAPER_PROMPT.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=problem,
        requirements=requirements or "无特殊要求",
        language_block=lc["language_block"],
        abstract_note=lc["abstract_note"],
        ref_note=lc["ref_note"],
    )

    def generate():
        try:
            # Yield stage markers so frontend can show progress cards
            stages = [
                "分析题目类型", "匹配合适模型", "构建论文框架",
                "撰写假设与符号说明", "生成 Python 代码", "生成敏感性分析",
            ]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"

            for chunk in generate_stream(system_prompt, user_prompt, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("stream generation failed: %s", e, exc_info=True)
            yield "data: [ERROR] 生成失败，请稍后重试\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ===== API: Full Paper Generation =====

@app.route("/api/generate-paper/stream", methods=["POST"])
@limiter.limit("2 per minute")
def generate_paper_stream_endpoint():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    requirements = data.get("requirements", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    problem_type = data.get("problem_type", "A")
    problem_category = data.get("problem_category", "连续型")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    lc = _get_language_config(contest_type)
    api_key = _get_api_key()

    def generate():
        try:
            yield from run_pipeline(
                problem=problem,
                requirements=requirements,
                contest_type=contest_type,
                problem_type=problem_type,
                problem_category=problem_category,
                api_key=api_key,
                language_instruction=lc["language_instruction"],
                language_block=lc["language_block"],
                paper_title_placeholder=lc["paper_title_placeholder"],
            )
        except Exception as e:
            logger.error("stream generation failed: %s", e, exc_info=True)
            yield "data: [ERROR] 生成失败，请稍后重试\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ===== API: AI Use Report =====

@app.route("/api/ai-report", methods=["POST"])
@limiter.limit("10 per minute")
def ai_report():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    tools_used = data.get("tools_used", "DeepSeek Chat for brainstorming and code generation")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    user_prompt = AI_REPORT_PROMPT.format(problem=problem, tools_used=tools_used)

    try:
        result = generate_response(SYSTEM_AI_REPORT, user_prompt, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("generate failed: %s", e, exc_info=True)
        return jsonify({"error": "生成失败，请稍后重试"}), 500


@app.route("/api/ai-report/stream", methods=["POST"])
@limiter.limit("8 per minute")
def ai_report_stream():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    tools_used = data.get("tools_used", "DeepSeek Chat for brainstorming and code generation")
    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400
    user_prompt = AI_REPORT_PROMPT.format(problem=problem, tools_used=tools_used)
    def generate():
        try:
            stages = ["正在分析题目...", "正在生成报告...", "正在整理格式..."]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"
            for chunk in generate_stream(SYSTEM_AI_REPORT, user_prompt, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("ai-report stream failed: %s", e, exc_info=True)
            yield "data: [ERROR] 生成失败，请稍后重试\n\n"
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


# ===== API: LaTeX Template =====

@app.route("/api/latex")
def get_latex():
    return jsonify({"content": LATEX_TEMPLATE})


# ===== API: Semantic Scholar =====

@app.route("/api/scholar/search")
def scholar_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "请输入搜索关键词"}), 400
    keywords = [kw.strip() for kw in q.split(",") if kw.strip()]
    papers = search_by_keywords(keywords, limit=10)
    return jsonify({"papers": papers, "total": len(papers)})


@app.route("/api/scholar/references", methods=["POST"])
@limiter.limit("10 per minute")
def scholar_references():
    data = request.get_json()
    titles = data.get("titles", [])
    if not titles:
        return jsonify({"error": "请提供论文标题列表"}), 400
    papers = []
    for t in titles[:5]:
        results = search_by_keywords([t], limit=1)
        if results:
            papers.extend(results)
    refs = format_references_apa(papers) if papers else []
    return jsonify({"references": refs})


# ===== API: Interactive Explanation =====

@app.route("/api/explain", methods=["POST"])
@limiter.limit("10 per minute")
def explain_section():
    data = request.get_json()
    section_title = data.get("section_title", "").strip()
    section_content = data.get("section_content", "").strip()

    if not section_title or not section_content:
        return jsonify({"error": "请提供章节标题和内容"}), 400

    user_prompt = f"""请用通俗易懂的语言解释以下论文章节，适合大一新生理解。

## 章节标题
{section_title}

## 章节内容
{section_content[:2000]}

请用生活类比和简单语言解释核心概念，避免复杂数学公式。最后用一句话总结核心要点。"""

    try:
        result = generate_response(SYSTEM_EXPLAIN, user_prompt, max_tokens=1500, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("explain failed: %s", e, exc_info=True)
        return jsonify({"error": "解释生成失败，请稍后重试"}), 500


@app.route("/api/explain/stream", methods=["POST"])
@limiter.limit("10 per minute")
def explain_section_stream():
    data = request.get_json()
    section_title = data.get("section_title", "").strip()
    section_content = data.get("section_content", "").strip()
    if not section_title or not section_content:
        return jsonify({"error": "请提供章节标题和内容"}), 400
    user_prompt = f"""请用通俗易懂的语言解释以下论文章节，适合大一新生理解。

## 章节标题
{section_title}

## 章节内容
{section_content[:2000]}

请用生活类比和简单语言解释核心概念，避免复杂数学公式。最后用一句话总结核心要点。"""
    def generate():
        try:
            stages = ["正在阅读章节内容...", "正在生成通俗解释...", "正在总结要点..."]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"
            for chunk in generate_stream(SYSTEM_EXPLAIN, user_prompt, max_tokens=1500, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("explain stream failed: %s", e, exc_info=True)
            yield "data: [ERROR] 解释生成失败，请稍后重试\n\n"
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


# ===== API: LaTeX Paper Generation =====

@app.route("/api/generate-paper/latex", methods=["POST"])
@limiter.limit("3 per minute")
def generate_paper_latex():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    requirements = data.get("requirements", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    problem_type = data.get("problem_type", "A")
    problem_category = data.get("problem_category", "连续型")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    lc = _get_language_config(contest_type)
    system_prompt = SYSTEM_PAPER.format(
        contest_type=contest_type,
        language_instruction=lc["language_instruction"],
    )

    user_prompt = PAPER_LATEX_PROMPT.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=problem,
        requirements=requirements or "无特殊要求",
        language_block=lc["language_block"],
    )

    def generate():
        try:
            for chunk in generate_stream(system_prompt, user_prompt, max_tokens=12000, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("stream generation failed: %s", e, exc_info=True)
            yield "data: [ERROR] 生成失败，请稍后重试\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ===== API: Reference Verification =====

def _extract_title_for_search(ref_text):
    """Extract a meaningful search query from a reference string for Semantic Scholar."""
    import re
    # Try to extract the paper title — typically between authors and journal/volume
    # Patterns: "Author (Year). Title. Journal." or "Author, Title, Journal, Year"

    # Remove bracketed numbers at start
    cleaned = re.sub(r'^\[\d+\]\s*', '', ref_text)

    # Strategy 1: Look for quoted title
    quoted = re.findall(r'[""]([^""]{20,})[""]', cleaned)
    if quoted:
        return quoted[0][:150]

    # Strategy 2: Extract between year and the journal info
    # "Author. (2020). Title of the paper. Journal Name, 10(2), 100-120."
    year_match = re.search(r'\((\d{4})\)', cleaned)
    if year_match:
        after_year = cleaned[year_match.end():].strip()
        # The title is typically between the year and the journal name
        # Split by "Journal" or "In:" or "Vol." or by the pattern ", 10(" which indicates volume
        title_parts = re.split(
            r'(?:[Jj]ournal|[Vv]ol\.?\s*\d|pp?\.\s*\d|In:\s|Proceedings of|'
            r'[A-Z][a-z]+,\s*\d+\(\d+\)|,\s*\d+\(\d+\))',
            after_year, maxsplit=1
        )
        candidate = title_parts[0].strip().rstrip('.').strip()
        if len(candidate) >= 20:
            return candidate[:150]

    # Strategy 3: Find the longest segment between periods (likely the title)
    segments = [s.strip() for s in cleaned.split('.') if len(s.strip()) > 15]
    if segments:
        # Skip author name segments (typically short, with commas)
        candidates = [s for s in segments if ',' not in s or len(s) > 40]
        if candidates:
            return max(candidates, key=len)[:150]

    # Strategy 4: Remove author patterns and take the remaining text
    # "Last, F., Last, F. (year)." → remove this prefix
    author_stripped = re.sub(
        r'^[A-Z][a-z]+,\s*[A-Z]\.(?:\s*,\s*[A-Z]\.)*\s*(?:and\s+[A-Z][a-z]+,\s*[A-Z]\.)?\s*(?:\(\d{4}\)\.?)?\s*',
        '', cleaned, count=1
    ).strip()
    if len(author_stripped) > 30:
        return author_stripped[:150]

    return cleaned[:150]


@app.route("/api/verify-references", methods=["POST"])
@limiter.limit("10 per minute")
def verify_references():
    data = request.get_json()
    content = data.get("content", "").strip()

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400

    import re

    try:
        ref_section = content
        ref_header = re.search(
            r'(?:^|\n)#{1,3}\s*(?:References?|参考文献|Bibliography|Works?\s*Cited)\s*\n',
            content, re.IGNORECASE
        )
        if ref_header:
            ref_section = content[ref_header.end():]

        # Extract individual references
        ref_patterns = [
            r'\[(\d+)\]\s+(.+?)(?=\[\d+\]|\Z)',  # [1] Author. Title...
            r'^\d+\.\s+(.+?)(?=\n\d+\.\s|\Z)',    # 1. Author. Title...
        ]
        refs_found = []  # list of (ref_number, ref_text)
        for pattern in ref_patterns:
            matches = re.findall(pattern, ref_section, re.DOTALL | re.MULTILINE)
            for match in matches:
                num, text = (match[0], match[1]) if isinstance(match, tuple) else (str(len(refs_found) + 1), match)
                if len(text.strip()) > 30:
                    refs_found.append((num, text.strip()[:300]))

        if not refs_found:
            return jsonify({"error": "未在论文中找到参考文献"}), 400

        # Parallel search all references for speed
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _search_one_ref(ref_info):
            ref_num, ref_text = ref_info
            search_query = _extract_title_for_search(ref_text)
            papers = search_by_keywords([search_query], limit=5)
            if papers:
                best = papers[0]
                return {
                    "ref_num": ref_num, "original": ref_text[:200], "status": "verified",
                    "match_title": best.get("title", ""), "match_authors": best.get("authors", []),
                    "match_year": best.get("year"), "match_citations": best.get("citationCount", 0),
                    "match_doi": best.get("doi", ""), "match_url": best.get("url", ""),
                    "match_apa": format_reference_apa(best),
                    "alternatives": [format_reference_apa(p) for p in papers[1:3]] if papers[1:] else [],
                }
            else:
                fallback_query = search_query[:80]
                alt_papers = search_papers(fallback_query, limit=3) if len(fallback_query) > 20 else []
                return {
                    "ref_num": ref_num, "original": ref_text[:200], "status": "not_found",
                    "match_title": "", "match_authors": [], "match_year": None,
                    "match_citations": 0, "match_doi": "", "match_url": "", "match_apa": "",
                    "suggested_replacements": [
                        {"apa": format_reference_apa(p), "title": p.get("title", ""),
                         "citationCount": p.get("citationCount", 0), "year": p.get("year")}
                        for p in alt_papers
                    ] if alt_papers else [],
                }

        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_search_one_ref, ref): ref for ref in refs_found}
            for future in as_completed(futures):
                results.append(future.result())

        # Sort by ref number
        results.sort(key=lambda r: r["ref_num"])
        verified_count = sum(1 for r in results if r["status"] == "verified")
        fake_count = len(results) - verified_count
        return jsonify({
            "total": len(results),
            "verified": verified_count,
            "fake": fake_count,
            "results": results,
            "ref_section_start": ref_header.start() if ref_header else -1,
        })
    except Exception as e:
        logger.error("reference verification failed: %s", e, exc_info=True)
        return jsonify({"error": "引用验证失败，请稍后重试"}), 500


# ===== API: Math Self-Consistency Check =====

@app.route("/api/verify-math", methods=["POST"])
@limiter.limit("10 per minute")
def verify_math():
    data = request.get_json()
    content = data.get("content", "").strip()

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400

    # Extract math-heavy sections: formulas and surrounding text
    import re
    # Find sections with LaTeX formulas
    formula_blocks = re.findall(
        r'(?:#{1,3}\s+[^\n]+|Model\s+Development|模型建立|Mathematical\s+Formulation|数学模型).*?(?=#{1,3}\s+|$)',
        content, re.DOTALL | re.IGNORECASE
    )

    if not formula_blocks:
        # Fallback: use content sections that contain $$ or $
        parts = content.split('\n\n')
        formula_blocks = [p for p in parts if '$$' in p or '$' in p or '\\begin' in p or '\\frac' in p]

    if not formula_blocks:
        return jsonify({"error": "未在论文中找到数学公式"}), 400

    # Take the most formula-dense sections (up to ~3000 chars total)
    math_text = '\n\n'.join(formula_blocks[:3])[:4000]

    user_prompt = f"""Please verify the mathematical correctness of the following paper section.

For each formula or derivation, independently re-derive it and check for errors.

## Paper Section

{math_text}

Please provide a structured verification report."""

    try:
        result = generate_response(SYSTEM_MATH_VERIFY, user_prompt, max_tokens=2000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("math verify failed: %s", e, exc_info=True)
        return jsonify({"error": "数学验证失败，请稍后重试"}), 500


@app.route("/api/verify-math/stream", methods=["POST"])
@limiter.limit("8 per minute")
def verify_math_stream():
    data = request.get_json()
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "请提供论文内容"}), 400
    import re as _re2
    formula_blocks = _re2.findall(
        r'(?:#{1,3}\s+[^\n]+|Model\s+Development|模型建立|Mathematical\s+Formulation|数学模型).*?(?=#{1,3}\s+|$)',
        content, _re2.DOTALL | _re2.IGNORECASE
    )
    if not formula_blocks:
        parts = content.split('\n\n')
        formula_blocks = [p for p in parts if '$$' in p or '$' in p or '\\begin' in p or '\\frac' in p]
    if not formula_blocks:
        return jsonify({"error": "未在论文中找到数学公式"}), 400
    math_text = '\n\n'.join(formula_blocks[:3])[:4000]
    user_prompt = f"""Please verify the mathematical correctness of the following paper section.

For each formula or derivation, independently re-derive it and check for errors.

## Paper Section

{math_text}

Please provide a structured verification report."""
    def generate():
        try:
            stages = ["正在提取公式...", "正在独立推导验证...", "正在生成验证报告..."]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"
            for chunk in generate_stream(SYSTEM_MATH_VERIFY, user_prompt, max_tokens=2000, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("math verify stream failed: %s", e, exc_info=True)
            yield "data: [ERROR] 数学验证失败，请稍后重试\n\n"
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


# ===== API: Plagiarism / Originality Check =====

@app.route("/api/check-plagiarism", methods=["POST"])
@limiter.limit("10 per minute")
def check_plagiarism():
    data = request.get_json()
    content = data.get("content", "").strip()

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400

    if len(content) < 200:
        return jsonify({"error": "论文内容过短，至少需要 200 字"}), 400

    # Take first ~5000 chars for analysis
    analysis_text = content[:5000]

    user_prompt = f"""Please analyze the following mathematical modeling paper for originality and plagiarism risks.

{analysis_text}

Provide a section-by-section originality assessment with specific flagged passages and rewrite suggestions."""

    try:
        result = generate_response(SYSTEM_PLAGIARISM, user_prompt, max_tokens=2000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("plagiarism check failed: %s", e, exc_info=True)
        return jsonify({"error": "查重分析失败，请稍后重试"}), 500


@app.route("/api/check-plagiarism/stream", methods=["POST"])
@limiter.limit("8 per minute")
def check_plagiarism_stream():
    data = request.get_json()
    content = data.get("content", "").strip()

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400
    if len(content) < 200:
        return jsonify({"error": "论文内容过短，至少需要 200 字"}), 400

    analysis_text = content[:5000]
    user_prompt = f"""Please analyze the following mathematical modeling paper for originality and plagiarism risks.

{analysis_text}

Provide a section-by-section originality assessment with specific flagged passages and rewrite suggestions."""

    def generate():
        try:
            stages = ["正在提取文本片段...", "正在比对分析...", "正在生成查重报告..."]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"

            for chunk in generate_stream(SYSTEM_PLAGIARISM, user_prompt, max_tokens=2000, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("plagiarism stream failed: %s", e, exc_info=True)
            yield "data: [ERROR] 查重分析失败，请稍后重试\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ===== API: AI Deduplication / Paraphrasing =====

@app.route("/api/deduplicate", methods=["POST"])
@limiter.limit("10 per minute")
def deduplicate():
    data = request.get_json()
    passages = data.get("passages", "").strip()
    full_content = data.get("full_content", "").strip()
    mode = data.get("mode", "full")  # "full" or "targeted"
    contest_type = data.get("contest_type", "MCM/ICM")

    if mode == "targeted":
        if not full_content:
            return jsonify({"error": "请提供完整论文内容"}), 400
        if not passages:
            return jsonify({"error": "请提供需要降重的文本段落"}), 400
        if len(passages) < 50:
            return jsonify({"error": "文本过短，至少需要 50 字"}), 400

        lang = "Chinese" if contest_type == "CUMCM" else "English"
        user_prompt = f"""I have a mathematical modeling paper that needs targeted plagiarism reduction.

Target language: {lang}

=== FULL PAPER (KEEP INTACT except for flagged sections below) ===
{full_content[:6000]}

=== FLAGGED PASSAGES TO REWRITE ===
{passages[:3000]}

IMPORTANT INSTRUCTIONS:
1. Return the COMPLETE paper with ALL sections intact
2. ONLY rewrite the flagged passages — keep everything else WORD-FOR-WORD identical
3. For each flagged passage, restructure sentences, use different vocabulary, vary academic phrasing
4. Keep ALL mathematical formulas, LaTeX expressions, data values, and technical conclusions exactly as they are
5. The output should be the full paper, ready to use as-is

Return the complete rewritten paper."""
    else:
        if not passages:
            return jsonify({"error": "请提供需要降重的文本段落"}), 400
        if len(passages) < 50:
            return jsonify({"error": "文本过短，至少需要 50 字"}), 400

        lang = "Chinese" if contest_type == "CUMCM" else "English"
        user_prompt = f"""Please rewrite the following mathematical modeling paper to reduce plagiarism risk.

Target language: {lang}

Original paper:
{passages[:5000]}

Please provide the complete rewritten paper that says the same thing differently."""

    try:
        result = generate_response(SYSTEM_DEDUP, user_prompt, max_tokens=3000, api_key=_get_api_key())
        result = _strip_code_fences(result)
        return jsonify({"content": result, "mode": mode})
    except Exception as e:
        logger.error("dedup failed: %s", e, exc_info=True)
        return jsonify({"error": "降重改写失败，请稍后重试"}), 500


@app.route("/api/deduplicate/stream", methods=["POST"])
@limiter.limit("8 per minute")
def deduplicate_stream():
    data = request.get_json()
    passages = data.get("passages", "").strip()
    full_content = data.get("full_content", "").strip()
    mode = data.get("mode", "full")
    contest_type = data.get("contest_type", "MCM/ICM")
    lang = "Chinese" if contest_type == "CUMCM" else "English"

    if mode == "targeted":
        if not full_content or not passages:
            return jsonify({"error": "请提供完整论文内容和需要降重的段落"}), 400
        user_prompt = f"""I have a mathematical modeling paper that needs targeted plagiarism reduction.

Target language: {lang}

=== FULL PAPER (KEEP INTACT except for flagged sections below) ===
{full_content[:6000]}

=== FLAGGED PASSAGES TO REWRITE ===
{passages[:3000]}

IMPORTANT INSTRUCTIONS:
1. Return the COMPLETE paper with ALL sections intact
2. ONLY rewrite the flagged passages — keep everything else WORD-FOR-WORD identical
3. For each flagged passage, restructure sentences, use different vocabulary, vary academic phrasing
4. Keep ALL mathematical formulas, LaTeX expressions, data values, and technical conclusions exactly as they are
5. The output should be the full paper, ready to use as-is

Return the complete rewritten paper."""
    else:
        if not passages or len(passages) < 50:
            return jsonify({"error": "文本过短，至少需要 50 字"}), 400
        user_prompt = f"""Please rewrite the following mathematical modeling paper to reduce plagiarism risk.

Target language: {lang}

Original paper:
{passages[:5000]}

Please provide the complete rewritten paper that says the same thing differently."""

    def generate():
        try:
            stages = ["正在分析文本结构...", "正在重述改写...", "正在校核公式数据..."]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"
            for chunk in generate_stream(SYSTEM_DEDUP, user_prompt, max_tokens=3000, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("dedup stream failed: %s", e, exc_info=True)
            yield "data: [ERROR] 降重改写失败，请稍后重试\n\n"
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


# ===== API: AST-based Layout-Preserving Deduplication =====

@app.route("/api/deduplicate-ast", methods=["POST"])
@limiter.limit("10 per minute")
def deduplicate_ast():
    """Layout-preserving deduplication using markdown AST parsing.

    Only natural-language text paragraphs are sent to the LLM for rewriting.
    Code fences, tables, images, LaTeX math, and horizontal rules are
    completely isolated and pass through untouched.
    """
    data = request.get_json()
    content = data.get("content", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400
    if len(content) < 200:
        return jsonify({"error": "论文内容过短，至少需要 200 字"}), 400

    try:
        # Phase 1: AST parse & extract text segments
        deduper = LayoutPreservingDeduper()
        deduper.parse(content)
        segments = deduper.extract_text_segments()

        if not segments:
            return jsonify({"content": content, "note": "No text segments found to rewrite."})

        # Phase 2: Batch-send to LLM for rewriting
        lang = "Chinese" if contest_type == "CUMCM" else "English"
        rewritten_map: dict[int, str] = {}

        batch_size = 5
        for batch_start in range(0, len(segments), batch_size):
            batch = segments[batch_start:batch_start + batch_size]

            # Build a prompt that shows each segment with its context
            prompt_parts = []
            for seg in batch:
                header = seg.get('context_header', '')
                header_info = f" (section: {header})" if header else ""
                prompt_parts.append(
                    f"<segment id={seg['id']}{header_info}>\n{seg['text']}\n</segment>"
                )

            user_prompt = f"""Rewrite the following text segments from a mathematical modeling paper to reduce plagiarism risk.

Language: {lang}

CRITICAL RULES:
1. Rewrite each segment thoroughly — restructure sentences, use different vocabulary, vary academic phrasing.
2. Preserve ALL placeholders of the form ⟨⟨PROTECTED_N⟩⟩ exactly as they appear — these are atomic tokens representing formulas, images, or code. NEVER modify, remove, or reorder them.
3. Keep the original meaning and technical accuracy.
4. Output each rewritten segment in the same order, wrapped in <segment id=N>...</segment> tags.

Segments to rewrite:

{chr(10).join(prompt_parts)}"""

            result = generate_response(
                "You are an academic writing expert. Rewrite text to reduce plagiarism risk while preserving meaning. Always preserve ⟨⟨PROTECTED_N⟩⟩ markers verbatim.",
                user_prompt,
                max_tokens=4000,
                api_key=_get_api_key(),
            )

            # Parse <segment id=N>...</segment> from LLM response
            import re as _re
            seg_pattern = _re.compile(
                r'<segment\s+id\s*=\s*(\d+)\s*>(.*?)</segment\s*>',
                _re.DOTALL,
            )
            for m in seg_pattern.finditer(result):
                sid = int(m.group(1))
                rw_text = m.group(2).strip()
                rewritten_map[sid] = rw_text

            # Fallback: if parsing failed, use original texts
            for seg in batch:
                if seg['id'] not in rewritten_map:
                    rewritten_map[seg['id']] = seg['text']

        # Phase 3: Reassemble document with rewritten text
        final = deduper.apply_and_render(rewritten_map)
        return jsonify({"content": final, "mode": "ast"})

    except Exception as e:
        logger.error("AST dedup failed: %s", e, exc_info=True)
        return jsonify({"error": f"降重改写失败: {str(e)[:200]}"}), 500


@app.route("/api/deduplicate-ast/stream", methods=["POST"])
@limiter.limit("8 per minute")
def deduplicate_ast_stream():
    """Streaming version — reports batch progress, returns final result."""
    data = request.get_json()
    content = data.get("content", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400
    if len(content) < 200:
        return jsonify({"error": "论文内容过短，至少需要 200 字"}), 400

    import re as _re3
    def generate():
        try:
            deduper = LayoutPreservingDeduper()
            deduper.parse(content)
            segments = deduper.extract_text_segments()

            if not segments:
                yield "data: [DONE]\n\n"
                return

            lang = "Chinese" if contest_type == "CUMCM" else "English"
            rewritten_map = {}
            batch_size = 5
            total_batches = (len(segments) + batch_size - 1) // batch_size

            for batch_idx, batch_start in enumerate(range(0, len(segments), batch_size)):
                batch = segments[batch_start:batch_start + batch_size]
                yield f"data: [PROGRESS:正在改写 {batch_idx + 1}/{total_batches} 批 ({batch_start + 1}-{min(batch_start + len(batch), len(segments))}/{len(segments)} 段)]\n\n"

                prompt_parts = []
                for seg in batch:
                    header = seg.get('context_header', '')
                    header_info = f" (section: {header})" if header else ""
                    prompt_parts.append(f"<segment id={seg['id']}{header_info}>\n{seg['text']}\n</segment>")

                user_prompt = f"""Rewrite the following text segments from a mathematical modeling paper to reduce plagiarism risk.

Language: {lang}

CRITICAL RULES:
1. Rewrite each segment thoroughly — restructure sentences, use different vocabulary, vary academic phrasing.
2. Preserve ALL placeholders of the form ⟨⟨PROTECTED_N⟩⟩ exactly as they appear — these are atomic tokens representing formulas, images, or code. NEVER modify, remove, or reorder them.
3. Keep the original meaning and technical accuracy.
4. Output each rewritten segment in the same order, wrapped in <segment id=N>...</segment> tags.

Segments to rewrite:

{chr(10).join(prompt_parts)}"""

                result = generate_response(
                    "You are an academic writing expert. Rewrite text to reduce plagiarism risk while preserving meaning. Always preserve ⟨⟨PROTECTED_N⟩⟩ markers verbatim.",
                    user_prompt,
                    max_tokens=4000,
                    api_key=_get_api_key(),
                )

                seg_pattern = _re3.compile(r'<segment\s+id\s*=\s*(\d+)\s*>(.*?)</segment\s*>', _re3.DOTALL)
                for m in seg_pattern.finditer(result):
                    sid = int(m.group(1))
                    rw_text = m.group(2).strip()
                    rewritten_map[sid] = rw_text
                for seg in batch:
                    if seg['id'] not in rewritten_map:
                        rewritten_map[seg['id']] = seg['text']

            final = deduper.apply_and_render(rewritten_map)
            yield f"data: [RESULT:{final}]\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("AST dedup stream failed: %s", e, exc_info=True)
            yield f"data: [ERROR] 降重改写失败: {str(e)[:200]}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


# ===== API: RAG Citation Grounding =====

@app.route("/api/ground-citations", methods=["POST"])
@limiter.limit("5 per minute")
def ground_citations():
    """Autonomous citation verification and correction.

    Uses function-calling tool use to let the DeepSeek model search for
    real academic papers, verify references, and replace hallucinated ones
    with verified alternatives.
    """
    data = request.get_json()
    content = data.get("content", "").strip()

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400

    try:
        agent = CitationGroundingAgent()

        # Phase 1: Extract references
        refs = agent.extract_references(content)
        if not refs:
            return jsonify({
                "content": content,
                "summary": "未在论文中找到参考文献。",
                "corrections": [],
            })

        # Phase 2: Build verification prompt and run tool loop
        user_prompt = agent.build_verification_prompt()

        def _run_tool_loop(system_prompt, user_prompt, tools, tool_executors):
            return run_tool_loop(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tools=tools,
                tool_executors=tool_executors,
                max_turns=3,
                api_key=_get_api_key(),
            )

        response_text = _run_tool_loop(
            SYSTEM_CITATION_AGENT,
            user_prompt,
            [SEARCH_ACADEMIC_PAPER_TOOL],
            CITATION_TOOL_EXECUTORS,
        )

        # Phase 3: Parse verification results
        agent.verification_results = agent.parse_verification_response(response_text)

        # Phase 4: Apply corrections
        corrected_paper, corrections_log = agent.apply_corrections(content)

        # Phase 5: Generate summary
        summary = agent.generate_correction_summary(corrections_log)

        return jsonify({
            "content": corrected_paper,
            "summary": summary,
            "corrections": corrections_log,
            "total_refs": len(refs),
        })

    except Exception as e:
        logger.error("citation grounding failed: %s", e, exc_info=True)
        return jsonify({"error": f"引用验证失败: {str(e)[:200]}"}), 500


# ===== Unified RAG Originality Check (Task-based, AST-Safe) =====

@app.route("/api/tasks/rag-check", methods=["POST"])
@limiter.limit("5 per minute")
def create_rag_check_task():
    """Unified RAG originality check: plagiarism analysis + citation grounding.

    Runs as a background task with progress reporting (survives page close).
    Returns a task_id immediately for polling via GET /api/tasks/<task_id>.
    """
    data = request.get_json()
    content = data.get("content", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400
    if len(content) < 200:
        return jsonify({"error": "论文内容过短，至少需要 200 字"}), 400

    def _run_rag_check(content, contest_type, _task_id=None, _update_progress=None):
        results = {}

        # Phase 1: Plagiarism check (5% → 30% via heartbeat)
        if _update_progress:
            _update_progress(5, 'Phase 1/3: 正在启动原创性分析...')
        analysis_text = content[:5000]
        plag_prompt = f"""Please analyze the following mathematical modeling paper for originality and plagiarism risks.

{analysis_text}

Provide a section-by-section originality assessment with specific flagged passages and rewrite suggestions."""
        # Start heartbeat: 5% → 28% over ~25s while LLM runs
        hb1 = _heartbeat_progress(_update_progress, 5, 28, 25,
                                   'Phase 1/3: AI 正在逐段分析论文原创性...')
        plag_result = generate_response(SYSTEM_PLAGIARISM, plag_prompt, max_tokens=2000, api_key=_get_api_key())
        if hb1:
            hb1.set()
        if _update_progress:
            _update_progress(30, 'Phase 1/3: 原创性分析完成')
        results['plagiarism'] = plag_result

        # Phase 2: Citation grounding (30% → 85%)
        if _update_progress:
            _update_progress(32, 'Phase 2/3: 正在提取参考文献...')
        try:
            agent = CitationGroundingAgent()
            refs = agent.extract_references(content)
            if refs:
                if _update_progress:
                    _update_progress(40, f'Phase 2/3: 提取到 {len(refs)} 条引用，准备验证...')
                user_prompt = agent.build_verification_prompt()

                def _run_tool_loop(system_prompt, user_prompt, tools, tool_executors):
                    return run_tool_loop(
                        system_prompt=system_prompt, user_prompt=user_prompt,
                        tools=tools, tool_executors=tool_executors,
                        max_turns=3, api_key=_get_api_key(),
                    )

                # Start heartbeat: 40% → 78% over ~55s while tool loop runs
                if _update_progress:
                    _update_progress(42, f'Phase 2/3: 正在 Crossref + Semantic Scholar 验证 {len(refs)} 条引用...')
                hb2 = _heartbeat_progress(_update_progress, 42, 78, 55,
                                           f'Phase 2/3: AI 自主检索验证 {len(refs)} 条引用中...')
                response_text = _run_tool_loop(
                    SYSTEM_CITATION_AGENT, user_prompt,
                    [SEARCH_ACADEMIC_PAPER_TOOL], CITATION_TOOL_EXECUTORS,
                )
                if hb2:
                    hb2.set()
                agent.verification_results = agent.parse_verification_response(response_text)

                # AST-safe correction: only modify reference section text
                if _update_progress:
                    _update_progress(82, 'Phase 3/3: 正在对比差异，生成 AST 安全替换...')
                corrected_paper, corrections_log = _apply_corrections_ast_safe(content, agent)
                summary = agent.generate_correction_summary(corrections_log)
                results['grounded_content'] = corrected_paper
                results['corrections'] = corrections_log
                results['summary'] = summary
                results['total_refs'] = len(refs)
                if _update_progress:
                    _update_progress(95, 'Phase 3/3: 修正方案生成完毕')
            else:
                results['grounded_content'] = content
                results['corrections'] = []
                results['summary'] = '未在论文中找到参考文献。'
                results['total_refs'] = 0
                if _update_progress:
                    _update_progress(90, '未找到参考文献，跳过验证阶段')
        except Exception as e:
            logger.error("citation grounding in rag-check failed: %s", e, exc_info=True)
            results['grounded_content'] = content
            results['corrections'] = []
            results['summary'] = f'引用验证失败: {str(e)[:200]}'
            results['total_refs'] = 0

        if _update_progress:
            _update_progress(100, 'RAG 原创性检验完成')
        return results

    task_id = task_manager.create('rag-check', _run_rag_check, content, contest_type)
    return jsonify({"task_id": task_id})


def _apply_corrections_ast_safe(markdown_text, agent):
    """Apply citation corrections with AST-level safety.

    Uses LayoutPreservingDeduper to ensure corrections only touch
    text paragraphs — never code fences, tables, math blocks, or images.
    """
    corrected, corrections_log = agent.apply_corrections(markdown_text)

    # AST safety verification: ensure protected blocks are untouched
    try:
        from src.dedup_ast import LayoutPreservingDeduper
        original_deduper = LayoutPreservingDeduper()
        original_deduper.parse(markdown_text)
        original_segs = original_deduper.extract_text_segments()

        corrected_deduper = LayoutPreservingDeduper()
        corrected_deduper.parse(corrected)
        corrected_segs = corrected_deduper.extract_text_segments()

        # Verify: protected segments (non-text) should be identical
        # If they differ, fall back to original text for protected segments
        if len(original_segs) != len(corrected_segs):
            logger.warning("AST safety: segment count changed after corrections (%d vs %d), using original for safety",
                           len(original_segs), len(corrected_segs))
            # Rebuild with AST safety — only apply corrections through the dedup pipeline
            safe_corrections = []
            for c in corrections_log:
                if c.get('is_corrected') and c.get('old_text') and c.get('new_text'):
                    safe_corrections.append(c)
            # Trust the simple string replacement but verify it didn't break fences/math
            # by checking that fence/math counts match
            import re
            orig_fences = len(re.findall(r'```', markdown_text))
            corr_fences = len(re.findall(r'```', corrected))
            orig_math = len(re.findall(r'\$\$', markdown_text))
            corr_math = len(re.findall(r'\$\$', corrected))
            if orig_fences != corr_fences or orig_math != corr_math:
                logger.error("AST safety: protected content modified! Fences: %d→%d, Math: %d→%d. Rolling back.",
                            orig_fences, corr_fences, orig_math, corr_math)
                return markdown_text, [{
                    "ref_id": 0, "old_text": "", "new_text": "", "is_corrected": False,
                    "note": "AST safety rollback — protected content was modified"
                }]
    except Exception as e:
        logger.warning("AST safety check skipped: %s", e)

    return corrected, corrections_log


# ===== API: Abstract Refinement =====

@app.route("/api/refine-abstract", methods=["POST"])
@limiter.limit("10 per minute")
def refine_abstract():
    data = request.get_json()
    abstract = data.get("abstract", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not abstract:
        return jsonify({"error": "请输入摘要内容"}), 400

    if contest_type == "CUMCM":
        language_instruction = "使用中文进行检查和建议。"
    else:
        language_instruction = "Provide all feedback in English."

    user_prompt = ABSTRACT_REFINE_PROMPT.format(
        abstract=abstract,
        contest_type=contest_type,
        language_instruction=language_instruction,
    )

    try:
        result = generate_response(SYSTEM_ABSTRACT_REFINE, user_prompt, max_tokens=2000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("abstract refine failed: %s", e, exc_info=True)
        return jsonify({"error": "摘要优化失败，请稍后重试"}), 500


@app.route("/api/refine-abstract/stream", methods=["POST"])
@limiter.limit("8 per minute")
def refine_abstract_stream():
    data = request.get_json()
    abstract = data.get("abstract", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    if not abstract:
        return jsonify({"error": "请输入摘要内容"}), 400
    if contest_type == "CUMCM":
        language_instruction = "使用中文进行检查和建议。"
    else:
        language_instruction = "Provide all feedback in English."
    user_prompt = ABSTRACT_REFINE_PROMPT.format(
        abstract=abstract, contest_type=contest_type, language_instruction=language_instruction
    )
    def generate():
        try:
            stages = ["正在分析摘要结构...", "正在对照 COMAP 标准...", "正在生成精修建议..."]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"
            for chunk in generate_stream(SYSTEM_ABSTRACT_REFINE, user_prompt, max_tokens=2000, api_key=_get_api_key()):
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("abstract refine stream failed: %s", e, exc_info=True)
            yield "data: [ERROR] 摘要优化失败，请稍后重试\n\n"
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    )


# ===== API: Sensitivity Analysis Code Generation =====

@app.route("/api/generate-sensitivity", methods=["POST"])
@limiter.limit("10 per minute")
def generate_sensitivity():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    model_description = data.get("model_description", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not problem:
        return jsonify({"error": "请输入问题描述"}), 400
    if not model_description:
        model_description = "The mathematical model described in the paper"

    if contest_type == "CUMCM":
        language_instruction = "使用中文注释。"
    else:
        language_instruction = "Use English comments."

    user_prompt = SENSITIVITY_PROMPT.format(
        problem=problem,
        model_description=model_description,
        contest_type=contest_type,
        language_instruction=language_instruction,
    )

    try:
        result = generate_response(SYSTEM_SENSITIVITY, user_prompt, max_tokens=3000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("sensitivity analysis failed: %s", e, exc_info=True)
        return jsonify({"error": "敏感性分析生成失败，请稍后重试"}), 500


# ===== API: AI Paper Scoring =====

@app.route("/api/score-paper", methods=["POST"])
@limiter.limit("10 per minute")
def score_paper():
    data = request.get_json()
    content = data.get("content", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400

    if contest_type == "CUMCM":
        language_instruction = "使用中文进行评估。"
    else:
        language_instruction = "Provide all feedback in English."

    user_prompt = PAPER_SCORING_PROMPT.format(
        content=content[:8000],
        contest_type=contest_type,
        language_instruction=language_instruction,
    )

    try:
        result = generate_response(SYSTEM_PAPER_SCORING, user_prompt, max_tokens=2500, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("paper scoring failed: %s", e, exc_info=True)
        return jsonify({"error": "论文评分失败，请稍后重试"}), 500


# ===== API: Smart Model Recommendation =====

@app.route("/api/recommend-models", methods=["POST"])
@limiter.limit("10 per minute")
def recommend_models():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    problem_type = data.get("problem_type", "A")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    if contest_type == "CUMCM":
        language_instruction = "使用中文回答。"
    else:
        language_instruction = "Answer in English."

    user_prompt = MODEL_RECOMMEND_PROMPT.format(
        problem=problem,
        contest_type=contest_type,
        problem_type=problem_type,
        language_instruction=language_instruction,
    )

    try:
        result = generate_response(SYSTEM_MODEL_RECOMMEND, user_prompt, max_tokens=2000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("model recommend failed: %s", e, exc_info=True)
        return jsonify({"error": "模型推荐失败，请稍后重试"}), 500


# ===== API: Figure Suggestion =====

@app.route("/api/suggest-figures", methods=["POST"])
@limiter.limit("10 per minute")
def suggest_figures():
    data = request.get_json()
    content = data.get("content", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400

    if contest_type == "CUMCM":
        language_instruction = "使用中文注释。"
    else:
        language_instruction = "Use English comments."

    user_prompt = FIGURE_SUGGEST_PROMPT.format(
        content=content[:6000],
        contest_type=contest_type,
        language_instruction=language_instruction,
    )

    try:
        result = generate_response(SYSTEM_FIGURE_SUGGEST, user_prompt, max_tokens=3000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("figure suggest failed: %s", e, exc_info=True)
        return jsonify({"error": "图表建议生成失败，请稍后重试"}), 500


# ===== API: Paper Comparison =====

@app.route("/api/compare-papers", methods=["POST"])
@limiter.limit("10 per minute")
def compare_papers():
    data = request.get_json()
    content_a = data.get("content_a", "").strip()
    content_b = data.get("content_b", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content_a or not content_b:
        return jsonify({"error": "请提供两版论文内容"}), 400

    user_prompt = PAPER_COMPARE_PROMPT.format(
        content_a=content_a[:4000],
        content_b=content_b[:4000],
        contest_type=contest_type,
    )

    try:
        result = generate_response(SYSTEM_PAPER_COMPARE, user_prompt, max_tokens=2500, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("paper compare failed: %s", e, exc_info=True)
        return jsonify({"error": "论文对比失败，请稍后重试"}), 500


# ===== API: Key Check =====

@app.route("/api/check-key", methods=["GET"])
def check_key():
    key = _get_api_key()
    if not key:
        return jsonify({"status": "missing"})
    if not key.startswith("sk-"):
        return jsonify({"status": "invalid_format"})
    try:
        resp = generate_response(
            "You are a helpful assistant.", "Reply with just: OK",
            max_tokens=5, api_key=key,
        )
        return jsonify({"status": "ok"}) if resp else jsonify({"status": "no_response"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:200]})


# ===== API: Mock COMAP Review =====

@app.route("/api/mock-review", methods=["POST"])
@limiter.limit("10 per minute")
def mock_review():
    data = request.get_json()
    content = data.get("content", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")

    if not content:
        return jsonify({"error": "请提供论文内容"}), 400

    user_prompt = MOCK_REVIEW_PROMPT.format(content=content[:15000])
    try:
        result = generate_response(SYSTEM_MOCK_REVIEW, user_prompt, max_tokens=3000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("mock review failed: %s", e, exc_info=True)
        return jsonify({"error": "模拟评审失败，请稍后重试"}), 500


# ===== API: Winning Paper Analysis =====

@app.route("/api/analyze-paper", methods=["POST"])
@limiter.limit("10 per minute")
def analyze_paper():
    if "file" not in request.files:
        return jsonify({"error": "请上传 PDF 文件"}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "仅支持 PDF 格式"}), 400

    try:
        from PyPDF2 import PdfReader
        import io
        pdf_bytes = io.BytesIO(file.read())
        reader = PdfReader(pdf_bytes)

        text_parts = []
        for page in reader.pages[:20]:  # limit to 20 pages
            t = page.extract_text()
            if t:
                text_parts.append(t)
        full_text = "\n\n".join(text_parts)

        if len(full_text) < 100:
            return jsonify({"error": "PDF 文本提取失败，请确认文件为标准 PDF（非扫描图片）"}), 400

        # Truncate to reasonable size for LLM
        max_chars = 12000
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n\n... [内容已截断]"

        user_prompt = PAPER_ANALYZE_PROMPT.format(content=full_text)
        result = generate_response(SYSTEM_PAPER_ANALYZE, user_prompt, max_tokens=3000, api_key=_get_api_key())
        return jsonify({"content": result})
    except Exception as e:
        logger.error("paper analyze failed: %s", e, exc_info=True)
        return jsonify({"error": "论文分析失败，请稍后重试"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8080)
