"""
Multi-Step Paper Generation Pipeline.

Orchestrates a 3-step generation process with Chain-of-Thought reasoning
and literature grounding:

  Step 0: Blueprint — analyze problem, output modeling plan (JSON)
  Step 1: Math Core  — generate Sections 4-6 with CoT derivations
  Step 2: Final Assembly — literature search + full paper with verified refs
  Post-Validation — non-blocking check for errors

Each step streams content to the frontend via SSE (Server-Sent Events).
"""

from __future__ import annotations

import json
import logging
from datetime import date

from src.prompts import (
    SYSTEM_BLUEPRINT, USER_BLUEPRINT,
    SYSTEM_MATH_CORE, USER_MATH_CORE,
    SYSTEM_PAPER_FINAL, USER_PAPER_FINAL,
    SYSTEM_POST_VALIDATE, USER_POST_VALIDATE,
)
from src.llm_client import generate_response, generate_stream
from src.scholar import search_papers, format_reference_apa

logger = logging.getLogger(__name__)


def _yield_stage(name: str):
    """Yield an SSE stage marker."""
    return f"data: [STAGE:{name}]\n\n"


def _yield_content(text: str):
    """Yield SSE content lines."""
    parts = []
    for line in text.split('\n'):
        parts.append(f"data: {line}\n")
    parts.append('\n')
    return ''.join(parts)


def run_pipeline(
    problem: str,
    requirements: str,
    contest_type: str,
    problem_type: str,
    problem_category: str,
    api_key: str,
    language_instruction: str,
    language_block: str,
    paper_title_placeholder: str,
) -> str:
    """Run the multi-step paper generation pipeline.

    Args:
        problem: Problem description text.
        requirements: Additional requirements (may be empty).
        contest_type: e.g. "MCM/ICM" or "CUMCM".
        problem_type: e.g. "A", "B", "C".
        problem_category: e.g. "连续型", "离散型".
        api_key: DeepSeek API key.
        language_instruction: Language prompt for the LLM.
        language_block: Additional language constraint block.
        paper_title_placeholder: Default title placeholder.

    Yields:
        SSE-formatted strings (including stage markers and content chunks).
    """
    today_str = (
        date.today().strftime("%Y年%m月%d日")
        if contest_type == "CUMCM"
        else date.today().strftime("%B %d, %Y")
    )
    full_problem = problem
    full_requirements = requirements or "无特殊要求"

    # ── Step 0: Blueprint ─────────────────────────────────────────────
    yield _yield_stage("分析问题结构...")
    yield _yield_stage("生成建模蓝图...")

    blueprint_user = USER_BLUEPRINT.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=full_problem,
        requirements=full_requirements,
        language_block=language_block,
    )

    blueprint_raw = generate_response(
        SYSTEM_BLUEPRINT, blueprint_user,
        max_tokens=1500, api_key=api_key,
    )

    # Parse blueprint JSON from response (may be wrapped in ```json fences)
    blueprint = _parse_blueprint(blueprint_raw)
    yield _yield_content(f"\n\n**Blueprint generated.** Model: {blueprint.get('model_type', 'TBD')}\n\n")
    yield _yield_content("---\n\n")

    # ── Step 1: Math Core ─────────────────────────────────────────────
    yield _yield_stage("推导数学模型...")
    yield _yield_stage("设计求解算法...")
    yield _yield_stage("分析结果与敏感性...")

    math_user = USER_MATH_CORE.format(
        blueprint=blueprint_raw,
        problem=full_problem,
        requirements=full_requirements,
        language_block=language_block,
    )

    math_sections = ""
    for chunk in generate_stream(
        SYSTEM_MATH_CORE, math_user,
        max_tokens=6000, api_key=api_key,
    ):
        math_sections += chunk
        yield _yield_content(chunk)

    yield _yield_content("\n\n")

    # ── Step 2: Literature Search ─────────────────────────────────────
    yield _yield_stage("检索真实文献...")

    verified_refs_text = _search_literature(blueprint, full_problem)
    yield _yield_content(f"\n\n**Literature search complete.** Found references for grounding.\n\n")
    yield _yield_content("---\n\n")

    # ── Step 3: Final Assembly ────────────────────────────────────────
    yield _yield_stage("撰写摘要与引言...")
    yield _yield_stage("撰写假设与论证...")
    yield _yield_stage("整合完整论文...")

    paper_user = USER_PAPER_FINAL.format(
        contest_type=contest_type,
        problem_type=problem_type,
        problem_category=problem_category,
        problem=full_problem,
        requirements=full_requirements,
        language_block=language_block,
        math_sections=math_sections,
        verified_references=verified_refs_text,
        paper_title_or_placeholder=paper_title_placeholder,
        date=today_str,
    )

    full_paper = ""
    for chunk in generate_stream(
        SYSTEM_PAPER_FINAL, paper_user,
        max_tokens=8000, api_key=api_key,
    ):
        full_paper += chunk
        yield _yield_content(chunk)

    # ── Post-Validation (non-blocking, results appended) ──────────────
    yield _yield_stage("验证论文完整性...")
    yield _yield_content("\n\n---\n\n### Validation Report\n\n")

    try:
        validate_user = USER_POST_VALIDATE.format(paper=full_paper[:12000])
        validate_result = generate_response(
            SYSTEM_POST_VALIDATE, validate_user,
            max_tokens=1000, api_key=api_key,
        )
        yield _yield_content(validate_result)
    except Exception as e:
        logger.warning("Post-validation failed (non-blocking): %s", e)
        yield _yield_content("*Validation skipped due to API error.*\n")

    yield "data: [DONE]\n\n"


def _parse_blueprint(raw: str) -> dict:
    """Extract JSON blueprint from LLM response (may contain markdown fences)."""
    import re

    # Try to extract JSON from ```json ... ``` fences
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    if json_match:
        candidate = json_match.group(1).strip()
    else:
        # Try to find a JSON object directly
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            candidate = json_match.group(0).strip()
        else:
            candidate = raw.strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning("Failed to parse blueprint JSON, using raw text")
        return {"model_type": "unknown", "raw": raw[:500]}


def _search_literature(blueprint: dict, problem: str) -> str:
    """Search Semantic Scholar for relevant literature.

    Uses keywords from the blueprint and problem text to find real papers.
    Returns formatted reference list text for inclusion in the final prompt.
    """
    keywords_list = blueprint.get("literature_keywords", [])
    if not keywords_list:
        # Fallback: extract keywords from model_approach and problem
        approach = blueprint.get("model_approach", "")
        model_type = blueprint.get("model_type", "")
        # Use model type + approach as search terms
        keywords_list = [model_type] if model_type else []
        if approach and len(keywords_list) < 5:
            for word in approach.split()[:10]:
                if len(word) > 3 and word.lower() not in {'using', 'with', 'based', 'that', 'this', 'from'}:
                    keywords_list.append(word)

    if not keywords_list:
        return "*No literature keywords available for search.*"

    all_papers = []
    seen_titles = set()

    for kw in keywords_list[:8]:
        try:
            papers = search_papers(kw, limit=3)
            for p in papers:
                title = (p.get("title") or "").strip().lower()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    all_papers.append(p)
        except Exception as e:
            logger.warning("Literature search failed for '%s': %s", kw, e)

    if not all_papers:
        return "*No matching papers found in Semantic Scholar.*"

    # Sort by citation count
    all_papers.sort(key=lambda p: p.get("citationCount", 0) or 0, reverse=True)

    # Format as reference list
    lines = []
    for i, p in enumerate(all_papers[:15], 1):
        apa = format_reference_apa(p)
        lines.append(f"[{i}] {apa}")

    return "\n".join(lines)
