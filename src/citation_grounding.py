"""
NotebookLM-style Autonomous Citation Grounding Agent.

This module implements an agentic workflow that:
  1. Extracts all references and their inline citation contexts from a document.
  2. Verifies each reference against real academic databases (Semantic Scholar +
     Crossref) using function-calling tool use.
  3. When a reference is found to be hallucinated (doesn't exist), the LLM
     autonomously searches for real alternatives that match the citation context.
  4. Auto-replaces hallucinated references with verified real ones — updating
     both the reference list AND inline citation markers (e.g. [1], [2]).

Architecture:
  Paper (Markdown)
      ↓ extract references (regex-based structural parsing)
  List of {ref_id, ref_text, context, inline_markers}
      ↓ verify loop (LLM with search_academic_paper tool)
  Verification results: real / hallucinated / uncertain
      ↓ for each hallucinated: LLM searches → picks replacement
  Replacement map: old_ref_text → new_real_ref (+ updated inline markers)
      ↓ apply replacements
  Corrected Paper (Markdown)
"""

from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.scholar import search_paper_multi, format_reference_apa

logger = logging.getLogger(__name__)


# ── Reference Extraction ──────────────────────────────────────────────

# Patterns for extracting references from Markdown papers
_RE_REF_HEADER = re.compile(
    r'(?:^|\n)(?:#{1,3}\s*)?(?:References?|REFERENCES?|参考文献|Bibliography|Works?\s*Cited|Literature\s*Cited)\s*\n',
    re.IGNORECASE,
)

# [1] Author. Title...
_RE_BRACKET_REF = re.compile(
    r'\[(\d+)\]\s+(.+?)(?=\[\d+\]|\n\n|\Z)',
    re.DOTALL,
)

# 1. Author. Title...
_RE_NUMBERED_REF = re.compile(
    r'^(\d+)\.\s+(.+?)(?=\n\d+\.\s|\n\n|\Z)',
    re.MULTILINE | re.DOTALL,
)

# Inline citation markers: [1], [1,2,3], [1-3]
_RE_INLINE_CITE = re.compile(r'\[([\d,\-\s]+)\]')


@dataclass
class ExtractedReference:
    """A single reference extracted from the document."""
    ref_id: int                                    # [1] → 1
    ref_text: str                                  # full reference text
    inline_markers: list[str] = field(default_factory=list)  # raw marker strings like "[1]"
    context_passages: list[str] = field(default_factory=list)  # text around each inline cite


@dataclass
class VerificationResult:
    """Result of verifying a single reference against academic databases."""
    ref_id: int
    original_text: str
    is_real: bool
    confidence: str           # "high" | "medium" | "low"
    matched_paper: Optional[dict] = None  # real paper match if found
    suggested_replacement: Optional[dict] = None  # {title, authors, year, apa}
    reasoning: str = ""


# ── Tool Definition (OpenAI/DeepSeek function-calling format) ────────

SEARCH_ACADEMIC_PAPER_TOOL = {
    "type": "function",
    "function": {
        "name": "search_academic_paper",
        "description": (
            "Search real academic databases (Semantic Scholar + Crossref) for a paper. "
            "Use this to verify whether a cited reference actually exists, or to find "
            "a real replacement paper that matches the citation context. "
            "Returns a list of matching papers with title, authors, year, DOI, and citation count."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The search query. For title verification, use the paper title. "
                        "For topic-based search, use keywords from the citation context."
                    ),
                },
                "search_purpose": {
                    "type": "string",
                    "enum": ["verify_existence", "find_replacement"],
                    "description": (
                        "'verify_existence' to check if a specific paper exists. "
                        "'find_replacement' to find real papers on the same topic."
                    ),
                },
            },
            "required": ["query", "search_purpose"],
        },
    },
}


def search_academic_paper(query: str, search_purpose: str = "verify_existence") -> str:
    """Execute an academic paper search and return formatted results.

    This is the actual tool executor called by the LLM. It searches
    Semantic Scholar + Crossref, merges results, and returns a
    human-readable summary suitable for LLM consumption.

    Args:
        query: Search query string.
        search_purpose: 'verify_existence' or 'find_replacement'.

    Returns:
        JSON string with search results.
    """
    try:
        papers = search_paper_multi(query, limit=5)

        if not papers:
            return json.dumps({
                "query": query,
                "results": [],
                "summary": "No matching papers found in any database.",
            }, ensure_ascii=False)

        results = []
        for p in papers:
            results.append({
                "title": p.get("title", ""),
                "authors": p.get("authors", [])[:5],
                "year": p.get("year"),
                "citations": p.get("citationCount", 0),
                "doi": p.get("doi", ""),
                "journal": p.get("container_title", ""),
                "source": p.get("_source", "unknown"),
                "apa": format_reference_apa(p),
            })

        return json.dumps({
            "query": query,
            "total_found": len(results),
            "results": results,
            "summary": f"Found {len(results)} matching papers.",
        }, ensure_ascii=False)

    except Exception as e:
        logger.error("search_academic_paper error: %s", e)
        return json.dumps({
            "query": query,
            "error": str(e),
            "results": [],
        }, ensure_ascii=False)


# Map tool name → executor function
CITATION_TOOL_EXECUTORS = {
    "search_academic_paper": search_academic_paper,
}


# ── System Prompt for the Citation Agent ────────────────────────────

SYSTEM_CITATION_AGENT = """You are an academic citation verification agent. Your job is to verify that every reference cited in a mathematical modeling paper actually exists in the real world, and to fix any that don't.

## Your Workflow

For each reference provided to you, follow this process:

### Step 1: Analyze the reference text
Parse the reference to extract: title, authors, year, journal/publisher, DOI (if present).

### Step 2: Search to verify existence
Call `search_academic_paper` with purpose="verify_existence" using the paper's title as the query.

### Step 3: Evaluate search results
- **If a close match is found** (similar title, matching authors, same year ±1): mark as REAL, confidence="high". Record the matched paper details.
- **If a partial match is found** (similar topic but different authors/title): mark as NEEDS CORRECTION. Note what doesn't match.
- **If no match is found**: the reference is likely HALLUCINATED.

### Step 4: For hallucinated references — find a real replacement
Call `search_academic_paper` with purpose="find_replacement" using keywords from the reference's topic area and the citation context.

From the search results, pick the best replacement paper that:
- Covers the same topic/method as the original citation
- Is from a credible source (peer-reviewed journal or conference)
- Has citations (preferred) or at least a verifiable DOI
- Was published before or during the paper's apparent timeframe

### Step 5: Output your verdict

For EACH reference, output a JSON object with these fields:
```json
{
  "ref_id": <number>,
  "original_text": "<the original reference text>",
  "verdict": "verified" | "hallucinated" | "uncertain",
  "confidence": "high" | "medium" | "low",
  "matched_paper": {
    "title": "<real title>",
    "authors": ["<author1>", "<author2>"],
    "year": <year>,
    "doi": "<doi if available>",
    "journal": "<journal name>"
  },
  "replacement_apa": "<APA-formatted replacement reference, or null if verified>",
  "replacement_inline_markers": "<how inline citations should look after fix, or null>",
  "reasoning": "<brief explanation of the verdict>"
}
```

## Critical Rules

1. **Preserve citation numbering**: When replacing a hallucinated reference, keep the SAME reference number [N]. The replacement must be a real paper that matches the citation context.
2. **Verify ALL references**: Don't assume any reference is real without checking.
3. **Be thorough**: If uncertain, search multiple times with different query formulations.
4. **Reference format**: Replacement references should follow APA 7th edition format.
5. **Mathematical formulas in titles**: Preserve LaTeX notation in titles.
6. **Be honest**: If you cannot find a suitable replacement, mark as "uncertain" with confidence "low" and explain why.
"""


# ── Main Agent ───────────────────────────────────────────────────────

class CitationGroundingAgent:
    """Autonomous citation verification and correction agent.

    Usage:
        agent = CitationGroundingAgent()
        result = agent.run(paper_markdown, llm_api_fn)
        # result.corrected_paper: str
        # result.verification_results: list[VerificationResult]
    """

    def __init__(self):
        self.extracted_refs: list[ExtractedReference] = []
        self.verification_results: list[VerificationResult] = []

    def extract_references(self, markdown_text: str) -> list[ExtractedReference]:
        """Extract all references and their inline citation contexts from a paper.

        Args:
            markdown_text: The full paper in Markdown format.

        Returns:
            List of ExtractedReference objects.
        """
        # 1. Find the reference section
        ref_header = _RE_REF_HEADER.search(markdown_text)
        if not ref_header:
            return []

        ref_section = markdown_text[ref_header.end():]

        # 2. Parse individual references using both patterns
        refs_raw = []

        # Try bracket-style references first: [1], [2], ...
        bracket_matches = _RE_BRACKET_REF.findall(ref_section)
        seen_ids = set()
        for ref_num, ref_text in bracket_matches:
            if len(ref_text.strip()) > 20 and int(ref_num) not in seen_ids:
                seen_ids.add(int(ref_num))
                refs_raw.append((int(ref_num), ref_text.strip()))

        # If no bracket refs, try numbered refs: 1., 2., ...
        if not refs_raw:
            numbered_matches = _RE_NUMBERED_REF.findall(ref_section)
            for ref_num, ref_text in numbered_matches:
                if len(ref_text.strip()) > 20 and int(ref_num) not in seen_ids:
                    seen_ids.add(int(ref_num))
                    refs_raw.append((int(ref_num), ref_text.strip()))

        # 3. Find inline citation markers for each reference
        # We search in the text BEFORE the reference section
        main_text = markdown_text[:ref_header.start()] if ref_header else markdown_text

        extracted = []
        for ref_num, ref_text in refs_raw:
            inline_markers = []
            context_passages = []

            # Find all occurrences of [ref_num] in the main text
            marker_pattern = rf'\[{ref_num}\]'
            for m in re.finditer(marker_pattern, main_text):
                marker = m.group(0)
                # Extract surrounding context (100 chars before and after)
                start = max(0, m.start() - 100)
                end = min(len(main_text), m.end() + 100)
                context = main_text[start:end].replace('\n', ' ').strip()
                inline_markers.append(marker)
                context_passages.append(context)

            # Also check for multi-citation mentions like [1,2,3] or [1-3]
            for m in _RE_INLINE_CITE.finditer(main_text):
                ids_in_marker = re.findall(r'\d+', m.group(0))
                if str(ref_num) in ids_in_marker:
                    marker = m.group(0)
                    if marker not in inline_markers:
                        inline_markers.append(marker)
                        start = max(0, m.start() - 100)
                        end = min(len(main_text), m.end() + 100)
                        context = main_text[start:end].replace('\n', ' ').strip()
                        context_passages.append(context)

            extracted.append(ExtractedReference(
                ref_id=ref_num,
                ref_text=ref_text,
                inline_markers=inline_markers if inline_markers else [f"[{ref_num}]"],
                context_passages=context_passages if context_passages else [""],
            ))

        self.extracted_refs = sorted(extracted, key=lambda r: r.ref_id)
        return self.extracted_refs

    def build_verification_prompt(self) -> str:
        """Build the user prompt for the citation verification agent."""
        if not self.extracted_refs:
            return "No references found in the document."

        lines = [
            "Please verify the following references from a mathematical modeling paper.",
            "",
            "For each reference, use the `search_academic_paper` tool to check",
            "whether it exists. If a reference is hallucinated, find a real",
            "replacement that matches the citation context.",
            "",
            "---",
            "",
        ]

        for ref in self.extracted_refs:
            lines.append(f"## Reference [{ref.ref_id}]")
            lines.append(f"")
            lines.append(f"**Reference text:** {ref.ref_text}")
            lines.append(f"")
            if ref.context_passages and ref.context_passages[0]:
                lines.append(f"**Citation context:** ...{ref.context_passages[0]}...")
                lines.append(f"")
            lines.append(f"**Inline markers found:** {', '.join(ref.inline_markers)}")
            lines.append(f"")
            lines.append("---")
            lines.append("")

        lines.append("Verify each reference above. For every hallucinated reference,")
        lines.append("use search_academic_paper to find a real alternative and provide")
        lines.append("the replacement in APA format. Output the complete verification")
        lines.append("results as a JSON array containing one object per reference.")
        lines.append("")
        lines.append("Begin verification now. Start by searching for each reference.")

        return "\n".join(lines)

    def parse_verification_response(self, response_text: str) -> list[VerificationResult]:
        """Parse the LLM's JSON response into VerificationResult objects."""
        results = []

        try:
            # Try to extract JSON array from response
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if json_match:
                data = json.loads(json_match.group(0))
                if isinstance(data, list):
                    for item in data:
                        results.append(VerificationResult(
                            ref_id=item.get("ref_id", 0),
                            original_text=item.get("original_text", ""),
                            is_real=item.get("verdict") == "verified",
                            confidence=item.get("confidence", "low"),
                            matched_paper=item.get("matched_paper"),
                            suggested_replacement=item.get("replacement_apa"),
                            reasoning=item.get("reasoning", ""),
                        ))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to parse verification response: %s", e)
            logger.debug("Raw response: %s", response_text[:500])

        return results

    def apply_corrections(self, markdown_text: str) -> tuple[str, list[dict]]:
        """Apply verified reference corrections to the document.

        Replaces hallucinated references with real ones, updating both the
        reference list and inline citation markers.

        Args:
            markdown_text: Original paper in Markdown.

        Returns:
            (corrected_markdown, corrections_log) where corrections_log is
            a list of {ref_id, old_text, new_text, is_corrected} dicts.
        """
        corrected = markdown_text
        corrections_log = []

        # Sort by ref_id descending so replacements don't shift positions
        sorted_results = sorted(
            self.verification_results,
            key=lambda r: r.ref_id,
            reverse=True,
        )

        for vr in sorted_results:
            if vr.is_real:
                corrections_log.append({
                    "ref_id": vr.ref_id,
                    "old_text": vr.original_text[:120],
                    "new_text": vr.original_text[:120],
                    "is_corrected": False,
                    "note": "Already real — no correction needed",
                })
                continue

            # For hallucinated/uncertain refs with a replacement
            replacement = vr.suggested_replacement
            if not replacement:
                corrections_log.append({
                    "ref_id": vr.ref_id,
                    "old_text": vr.original_text[:120],
                    "new_text": None,
                    "is_corrected": False,
                    "note": f"No replacement found ({vr.confidence} confidence)",
                })
                continue

            # Replace the reference text in the reference section
            # Strategy: find the reference block for this ref_id and replace it
            old_ref_pattern = rf'\[{vr.ref_id}\]\s*{re.escape(vr.original_text[:80])}'
            ref_match = re.search(old_ref_pattern, corrected)
            if ref_match:
                # Replace just this reference entry
                old_entry = ref_match.group(0)
                new_entry = f"[{vr.ref_id}] {replacement}"
                corrected = corrected.replace(old_entry, new_entry, 1)
                corrections_log.append({
                    "ref_id": vr.ref_id,
                    "old_text": vr.original_text[:120],
                    "new_text": replacement[:200],
                    "is_corrected": True,
                    "note": "Replaced hallucinated reference with real one",
                })
            else:
                # Try simpler pattern: just find [N] and replace the line
                simple_pattern = rf'\[{vr.ref_id}\]\s*[^\n]+'
                simple_match = re.search(simple_pattern, corrected)
                if simple_match:
                    corrected = corrected.replace(
                        simple_match.group(0),
                        f"[{vr.ref_id}] {replacement}",
                        1,
                    )
                    corrections_log.append({
                        "ref_id": vr.ref_id,
                        "old_text": vr.original_text[:120],
                        "new_text": replacement[:200],
                        "is_corrected": True,
                        "note": "Replaced (simple pattern match)",
                    })

        return corrected, corrections_log

    def generate_correction_summary(self, corrections_log: list[dict]) -> str:
        """Generate a human-readable summary of corrections made."""
        total = len(corrections_log)
        corrected = sum(1 for c in corrections_log if c.get("is_corrected"))
        unchanged = sum(1 for c in corrections_log if not c.get("is_corrected") and c.get("note") and "Already real" in c.get("note", ""))
        failed = total - corrected - unchanged

        lines = [
            f"## Citation Verification Summary",
            f"",
            f"- **Total references:** {total}",
            f"- **Verified real:** {unchanged}",
            f"- **Corrected (replaced):** {corrected}",
            f"- **Could not fix:** {failed}",
            f"",
        ]

        if corrected > 0:
            lines.append("### Corrections Made")
            lines.append("")
            for c in corrections_log:
                if c.get("is_corrected"):
                    lines.append(f"- **[{c['ref_id']}]** Replaced:")
                    lines.append(f"  - Old: *{c['old_text'][:100]}...*")
                    lines.append(f"  - New: {c['new_text'][:150]}")
                    lines.append("")

        return "\n".join(lines)


# ── Convenience: Full Pipeline ───────────────────────────────────────

def run_citation_grounding(
    markdown_text: str,
    run_tool_loop_fn,
) -> tuple[str, str]:
    """Run the complete citation grounding pipeline.

    Args:
        markdown_text: The paper in Markdown format.
        run_tool_loop_fn: A function (system_prompt, user_prompt, tools,
            tool_executors) → str that runs the LLM tool-use loop.
            (Use llm_client.run_tool_loop or equivalent.)

    Returns:
        (corrected_paper, summary_report) tuple.
    """
    agent = CitationGroundingAgent()

    # Phase 1: Extract references
    refs = agent.extract_references(markdown_text)
    if not refs:
        return markdown_text, "No references found in the document."

    # Phase 2: Build verification prompt
    user_prompt = agent.build_verification_prompt()

    # Phase 3: Run the LLM tool-use loop
    response = run_tool_loop_fn(
        system_prompt=SYSTEM_CITATION_AGENT,
        user_prompt=user_prompt,
        tools=[SEARCH_ACADEMIC_PAPER_TOOL],
        tool_executors=CITATION_TOOL_EXECUTORS,
    )

    # Phase 4: Parse results
    agent.verification_results = agent.parse_verification_response(response)

    # Phase 5: Apply corrections
    corrected_paper, corrections_log = agent.apply_corrections(markdown_text)

    # Phase 6: Generate summary
    summary = agent.generate_correction_summary(corrections_log)

    return corrected_paper, summary
