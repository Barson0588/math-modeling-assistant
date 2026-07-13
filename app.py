from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from src.prompts import (
    ROLES_INFO, SYSTEM_MCM_EN, SYSTEM_MCM_CN, SYSTEM_AI_REPORT,
    PAPER_PROMPT, AI_REPORT_PROMPT, LATEX_TEMPLATE,
)
from src.llm_client import generate_response, generate_stream
from src.models_data import MODELS
from src.problems_data import PROBLEMS
from src.guide_data import GUIDE

app = Flask(__name__)


# ===== Page Routes =====

@app.route("/")
def index():
    return render_template("index.html")


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
def generate():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    requirements = data.get("requirements", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    problem_type = data.get("problem_type", "A")
    problem_category = data.get("problem_category", "连续型")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    # Select system prompt based on contest type
    if contest_type == "CUMCM":
        system_prompt = SYSTEM_MCM_CN.format(
            contest_type="国赛 CUMCM",
            problem_type=problem_type,
            language_instruction="使用中文撰写论文框架，按国赛格式。",
        )
        language_block = ""
        abstract_note = "中文摘要 300 字左右，单独成页"
        ref_note = "建议引用 10-15 篇中文核心文献"
    else:
        system_prompt = SYSTEM_MCM_EN
        language_block = "**IMPORTANT: Generate the paper framework in ENGLISH. Follow MCM/ICM standards strictly.**"
        abstract_note = "English summary, 200-250 words, standalone page, NO formulas or citations"
        ref_note = "Suggest 15-20 authoritative English references in APA 7th edition"

    user_prompt = PAPER_PROMPT.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=problem,
        requirements=requirements or "无特殊要求",
        language_block=language_block,
        abstract_note=abstract_note,
        ref_note=ref_note,
    )

    try:
        result = generate_response(system_prompt, user_prompt)
        return jsonify({"content": result})
    except Exception as e:
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


@app.route("/api/generate/stream", methods=["POST"])
def generate_stream_endpoint():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    requirements = data.get("requirements", "").strip()
    contest_type = data.get("contest_type", "MCM/ICM")
    problem_type = data.get("problem_type", "A")
    problem_category = data.get("problem_category", "连续型")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    if contest_type == "CUMCM":
        system_prompt = SYSTEM_MCM_CN.format(
            contest_type="国赛 CUMCM",
            problem_type=problem_type,
            language_instruction="使用中文撰写论文框架，按国赛格式。",
        )
        language_block = ""
        abstract_note = "中文摘要 300 字左右，单独成页"
        ref_note = "建议引用 10-15 篇中文核心文献"
    else:
        system_prompt = SYSTEM_MCM_EN
        language_block = "**IMPORTANT: Generate the paper framework in ENGLISH. Follow MCM/ICM standards strictly.**"
        abstract_note = "English summary, 200-250 words, standalone page, NO formulas or citations"
        ref_note = "Suggest 15-20 authoritative English references in APA 7th edition"

    user_prompt = PAPER_PROMPT.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=problem,
        requirements=requirements or "无特殊要求",
        language_block=language_block,
        abstract_note=abstract_note,
        ref_note=ref_note,
    )

    def generate():
        try:
            for chunk in generate_stream(system_prompt, user_prompt):
                # Proper SSE framing: each line of the chunk gets its own "data:" prefix.
                # Empty line (\n\n) marks end of one SSE message.
                for line in chunk.split('\n'):
                    yield f"data: {line}\n"
                yield '\n'
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"

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
def ai_report():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    tools_used = data.get("tools_used", "DeepSeek Chat for brainstorming and code generation")

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    user_prompt = AI_REPORT_PROMPT.format(problem=problem, tools_used=tools_used)

    try:
        result = generate_response(SYSTEM_AI_REPORT, user_prompt)
        return jsonify({"content": result})
    except Exception as e:
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


# ===== API: LaTeX Template =====

@app.route("/api/latex")
def get_latex():
    return jsonify({"content": LATEX_TEMPLATE})


if __name__ == "__main__":
    app.run(debug=True, port=8080)
