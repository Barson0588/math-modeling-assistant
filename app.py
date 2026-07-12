from flask import Flask, render_template, request, jsonify
from src.prompts import ROLES_INFO, SYSTEM_PROMPT, PAPER_GENERATION_PROMPT
from src.llm_client import generate_response

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/roles")
def get_roles():
    return jsonify({"content": ROLES_INFO})


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    problem = data.get("problem", "").strip()
    requirements = data.get("requirements", "").strip()

    if not problem:
        return jsonify({"error": "请输入题目描述"}), 400

    user_prompt = PAPER_GENERATION_PROMPT.format(
        problem=problem, requirements=requirements or "无特殊要求"
    )

    try:
        result = generate_response(SYSTEM_PROMPT, user_prompt)
        return jsonify({"content": result})
    except Exception as e:
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8080)
