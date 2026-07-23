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
    default_limits=["30 per minute", "300 per hour"],
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
    system_prompt = SYSTEM_PAPER.format(
        contest_type=contest_type,
        language_instruction=lc["language_instruction"],
    )

    user_prompt = PAPER_FULL_PROMPT.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=problem,
        requirements=requirements or "无特殊要求",
        language_block=lc["language_block"],
        paper_title_or_placeholder=lc["paper_title_placeholder"],
        date=date.today().strftime("%B %d, %Y") if contest_type != "CUMCM" else date.today().strftime("%Y年%m月%d日"),
    )

    def generate():
        try:
            stages = [
                "撰写摘要", "引言与问题重述", "模型建立",
                "模型求解", "结果分析", "敏感性分析", "结论与参考文献",
            ]
            for s in stages:
                yield f"data: [STAGE:{s}]\n\n"

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

        # Search all references, but be responsive
        results = []
        fake_count = 0
        for ref_num, ref_text in refs_found:
            # Smart title extraction for better Semantic Scholar matching
            search_query = _extract_title_for_search(ref_text)

            papers = search_by_keywords([search_query], limit=5)
            if papers:
                best = papers[0]
                # Consider verified if title similarity or citation count is substantial
                verified = best.get("citationCount", 0) > 0 or len(best.get("title", "")) > 20
                result = {
                    "ref_num": ref_num,
                    "original": ref_text[:200],
                    "status": "verified",
                    "match_title": best.get("title", ""),
                    "match_authors": best.get("authors", []),
                    "match_year": best.get("year"),
                    "match_citations": best.get("citationCount", 0),
                    "match_doi": best.get("doi", ""),
                    "match_url": best.get("url", ""),
                    "match_apa": format_reference_apa(best),
                    "alternatives": [
                        format_reference_apa(p) for p in papers[1:3]
                    ] if papers[1:] else [],
                }
                results.append(result)
            else:
                fake_count += 1
                # Try broader search for alternative real references
                fallback_query = search_query[:80]
                alt_papers = search_papers(fallback_query, limit=3) if len(fallback_query) > 20 else []
                results.append({
                    "ref_num": ref_num,
                    "original": ref_text[:200],
                    "status": "not_found",
                    "match_title": "",
                    "match_authors": [],
                    "match_year": None,
                    "match_citations": 0,
                    "match_doi": "",
                    "match_url": "",
                    "match_apa": "",
                    "suggested_replacements": [
                        {
                            "apa": format_reference_apa(p),
                            "title": p.get("title", ""),
                            "citationCount": p.get("citationCount", 0),
                            "year": p.get("year"),
                        }
                        for p in alt_papers
                    ] if alt_papers else [],
                })

        verified = sum(1 for r in results if r["status"] == "verified")
        return jsonify({
            "total": len(results),
            "verified": verified,
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
                max_turns=5,
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
