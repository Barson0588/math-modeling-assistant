"""
AST-based, Layout-Preserving Deduplication Engine.

Parses Markdown into a token tree via markdown-it-py, isolates
non-text nodes (code fences, images, tables, LaTeX math, horizontal rules),
extracts only natural-language text paragraphs for LLM rewriting,
then maps rewritten text back into the original token positions
and reassembles the document — without touching protected nodes.

Architecture:
  Markdown text
      ↓ markdown-it parse
  Token list (flat, with open/close pairs)
      ↓ classify blocks + segment inline content
  Text segments + placeholder-protected segments
      ↓ DeepSeek API (only text segments)
  Rewritten text segments
      ↓ merge placeholders back
  Modified token list
      ↓ token→markdown serializer
  Rewritten Markdown text
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from typing import Optional

from markdown_it import MarkdownIt
from markdown_it.token import Token


# ── Inline Math / Protected Pattern Detection ──────────────────────────
# Because we don't use the texmath plugin, LaTeX math appears as raw text
# inside inline tokens. We detect these patterns to protect them.

_MATH_DISPLAY = re.compile(r'\$\$[\s\S]+?\$\$')       # $$ ... $$ (multi-line aware)
_MATH_INLINE = re.compile(r'(?<!\$)\$[^$\n]+?\$(?!\$)')  # $ ... $ (single-line, not double)
_LATEX_ENV = re.compile(r'\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}')  # \begin{..}..\end{..}
_LATEX_PAREN_INLINE = re.compile(r'\\\([\s\S]*?\\\)')   # \( ... \)
_LATEX_BRACKET_DISPLAY = re.compile(r'\\\[[\s\S]*?\\\]')  # \[ ... \]
_IMAGE_MD = re.compile(r'!\[.*?\]\(.*?\)')              # ![alt](url)
_INLINE_CODE = re.compile(r'`[^`]+`')                    # `code`
_PIPE_TABLE = re.compile(r'\|[^|]+\|.*\n\|[-: |]+\|')   # pipe tables (multi-line pattern)

# Combined pattern — order: LaTeX env first (longest match), then display math,
# then inline math (shortest), then images, then code
_PROTECTED_INLINE = re.compile(
    r'(\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\})'  # 1. LaTeX environments \begin..\end
    r'|(\\\[[\s\S]*?\\\])'                          # 2. Display math \[...\]
    r'|(\\\([\s\S]*?\\\))'                          # 3. Inline math \(...\)
    r'|(\$\$[\s\S]+?\$\$)'                          # 4. Display math $$...$$
    r'|(?<!\$)\$[^$\n]+?\$(?!\$)'                  # 5. Inline math $...$ (single-line)
    r'|(!\[.*?\]\(.*?\))'                           # 6. Images ![alt](url)
    r'|(`[^`]+`)',                                  # 7. Inline code `...`
)


# ── Token type constants ───────────────────────────────────────────────

# In markdown-it-py, the inline content lives in 'inline' tokens.
# Block tokens wrap inline tokens with *_open / *_close pairs.
_TEXT_BLOCK_OPENERS = {'paragraph_open', 'heading_open', 'list_item_open'}
_PROTECTED_BLOCK_TYPES = {'fence', 'code_block', 'hr', 'math_block', 'table_open', 'blockquote_open'}


# ── Data structures ────────────────────────────────────────────────────

@dataclass
class TextSegment:
    """A contiguous piece of natural-language text that needs rewriting."""
    id: int
    text: str
    token_idx: int          # index of the parent inline token in self.tokens
    child_indices: list[int] = field(default_factory=list)  # child text indices


@dataclass
class ProtectedSpan:
    """A protected inline span (math, image, code) within an inline token."""
    raw: str                # the original raw text e.g. "$x^2$"
    placeholder: str        # unique placeholder e.g. "⟨⟨PROTECTED_0⟩⟩"


@dataclass
class InlineBlueprint:
    """Deconstructed inline token: text segments + protected placeholders."""
    token_idx: int
    parts: list[str]        # alternating: text, placeholder, text, placeholder, ...
    protected_map: dict[str, str]  # placeholder → raw protected text


# ── Main Engine ────────────────────────────────────────────────────────

class LayoutPreservingDeduper:
    """Parse, classify, extract, rewrite, and reassemble a Markdown document.

    Usage:
        deduper = LayoutPreservingDeduper()
        deduper.parse(markdown_text)
        segments = deduper.extract_text_segments()
        # Send segments to LLM, get back rewritten_texts dict
        result = deduper.apply_and_render(rewritten_texts)
    """

    def __init__(self):
        self.md = MarkdownIt()
        self.tokens: list[Token] = []
        self._original_text: str = ""
        self._seg_to_inline: dict[int, int] = {}  # segment id → inline token index

    # ── Phase 1: Parse ─────────────────────────────────────────────

    def parse(self, text: str) -> LayoutPreservingDeduper:
        """Parse markdown text into a token tree."""
        self._original_text = text
        self.tokens = self.md.parse(text)
        return self

    # ── Phase 2: Classify & Extract ────────────────────────────────

    def extract_text_segments(self) -> list[dict]:
        """Extract only natural-language text segments that need rewriting.

        Returns a list of dicts:
          {id, text, token_idx, context_header}
        where context_header is the nearest heading text (for LLM context).
        """
        segments: list[dict] = []
        seg_id = 0
        current_heading = ""
        i = 0

        while i < len(self.tokens):
            t = self.tokens[i]

            # Track nearest heading for context
            if t.type == 'heading_open':
                heading_inline = self._find_inline_in_block(i)
                if heading_inline:
                    current_heading = heading_inline.content
                i = self._skip_block(i)
                continue

            # Skip protected blocks entirely (fence, hr, etc.)
            if t.type in _PROTECTED_BLOCK_TYPES:
                i = self._skip_block(i)
                continue

            # Text blocks: paragraph_open, list_item_open → find the inline token
            if t.type in _TEXT_BLOCK_OPENERS:
                inline_t = self._find_inline_in_block(i)
                inline_idx = self._find_inline_index_in_block(i)
                if inline_t and inline_t.content.strip():
                    raw_content = inline_t.content

                    # Skip pure pipe-table paragraphs (contain |---| delimiter)
                    if _PIPE_TABLE.search(raw_content):
                        i = self._skip_block(i)
                        continue

                    # Deconstruct inline content: separate text from protected spans
                    clean_text, placeholder_map = self._strip_protected_spans(raw_content)

                    # Skip segments that have no meaningful text after stripping
                    text_only = _PROTECTED_INLINE.sub('', raw_content).strip()
                    if not text_only:
                        i = self._skip_block(i)
                        continue

                    segments.append({
                        'id': seg_id,
                        'text': clean_text.strip(),
                        'token_idx': inline_idx,
                        'context_header': current_heading,
                    })
                    self._seg_to_inline[seg_id] = inline_idx
                    seg_id += 1

                i = self._skip_block(i)
                continue

            i += 1

        return segments

    # ── Phase 3: Apply rewrites & Reassemble ────────────────────────

    def apply_and_render(self, rewritten_map: dict[int, str]) -> str:
        """Apply rewritten text back to the token tree and serialize to Markdown.

        Args:
            rewritten_map: dict mapping segment.id → rewritten text

        Returns:
            Complete rewritten Markdown document.
        """
        # Phase 3a: For each rewritten segment, merge protected spans back in
        merged_map: dict[int, str] = {}

        for seg_id, new_text in rewritten_map.items():
            # Find the inline token and reconstruct with protected spans
            inline_idx = self._seg_id_to_inline_idx(seg_id)
            if inline_idx is None:
                merged_map[seg_id] = new_text
                continue

            token = self.tokens[inline_idx]
            original_content = token.content

            # Strip protected spans from original to get the text→placeholder mapping
            _, placeholder_map = self._strip_protected_spans(original_content)

            # Reconstruct: insert protected spans back into rewritten text
            merged = self._merge_protected_spans(new_text, placeholder_map)
            merged_map[seg_id] = merged

        # Phase 3b: Apply merged content to tokens
        self._apply_to_tokens(merged_map)

        # Phase 3c: Serialize tokens back to Markdown
        return TokenMarkdownRenderer().render(self.tokens)

    # ── Internal helpers ───────────────────────────────────────────

    def _strip_protected_spans(self, text: str) -> tuple[str, dict[str, str]]:
        """Replace protected inline spans (math, images, code) with placeholders.

        Returns:
            (clean_text, placeholder_map) where placeholder_map maps
            placeholder → original protected text.
        """
        placeholder_map: dict[str, str] = {}
        counter = 0

        def _replace(m: re.Match) -> str:
            nonlocal counter
            placeholder = f"⟨⟨PROTECTED_{counter}⟩⟩"
            placeholder_map[placeholder] = m.group(0)
            counter += 1
            return placeholder

        clean = _PROTECTED_INLINE.sub(_replace, text)
        return clean, placeholder_map

    def _merge_protected_spans(self, rewritten_text: str, placeholder_map: dict[str, str]) -> str:
        """Restore protected spans into rewritten text.

        Strategy:
        1. If placeholders appear in the rewritten text (LLM preserved them),
           replace them directly with the original protected content.
        2. If placeholders are missing (LLM removed them), try to find
           a reasonable insertion point by looking for sentence boundaries
           near the end of the rewritten text, and append the lost content.
        """
        result = rewritten_text
        lost: list[str] = []

        for placeholder, original in placeholder_map.items():
            if placeholder in result:
                result = result.replace(placeholder, original)
            else:
                lost.append(original)

        if lost:
            # Append lost protected content at a clean break point
            result = result.rstrip()
            if result and not result.endswith(('.', '!', '?', ':', '\n')):
                result += '.'
            result += ' ' + ' '.join(lost)

        return result

    def _apply_to_tokens(self, merged_map: dict[int, str]) -> None:
        """Apply merged content to inline tokens."""
        for seg_id, merged_text in merged_map.items():
            inline_idx = self._seg_id_to_inline_idx(seg_id)
            if inline_idx is not None:
                token = self.tokens[inline_idx]
                token.content = merged_text
                # Clear children so the renderer uses content directly
                token.children = None

    def _seg_id_to_inline_idx(self, seg_id: int) -> Optional[int]:
        """Map a segment ID back to its inline token index using the stored
        mapping built during extract_text_segments."""
        return self._seg_to_inline.get(seg_id)

    def _find_inline_in_block(self, open_idx: int) -> Optional[Token]:
        """Find the inline token inside a block starting at open_idx."""
        depth = 1  # we start after the opening token
        for j in range(open_idx + 1, len(self.tokens)):
            t = self.tokens[j]
            if t.type.endswith('_open'):
                depth += 1
            elif t.type.endswith('_close'):
                depth -= 1
                if depth == 0:
                    return None  # block closed, no inline found
            elif t.type == 'inline' and depth == 1:
                return t
        return None

    def _find_inline_index_in_block(self, open_idx: int) -> Optional[int]:
        """Find the index of the inline token inside a block."""
        depth = 1
        for j in range(open_idx + 1, len(self.tokens)):
            t = self.tokens[j]
            if t.type.endswith('_open'):
                depth += 1
            elif t.type.endswith('_close'):
                depth -= 1
                if depth == 0:
                    return None
            elif t.type == 'inline' and depth == 1:
                return j
        return None

    def _skip_block(self, start_idx: int) -> int:
        """Skip past a block (past its closing token). Returns index after close."""
        t = self.tokens[start_idx]
        # For self-closing tokens (fence, hr)
        if t.type in ('fence', 'hr', 'code_block', 'math_block'):
            return start_idx + 1

        # For paired tokens (paragraph_open→paragraph_close, table_open→table_close, etc.)
        if t.type.endswith('_open'):
            depth = 1
            close_suffix = '_close'
            for j in range(start_idx + 1, len(self.tokens)):
                tt = self.tokens[j]
                if tt.type.endswith('_open'):
                    depth += 1
                elif tt.type.endswith('_close'):
                    depth -= 1
                    if depth == 0:
                        return j + 1
            return start_idx + 1  # fallback

        return start_idx + 1


# ── Token → Markdown Serializer ────────────────────────────────────────

class TokenMarkdownRenderer:
    """Serialize a markdown-it token list back to Markdown text.

    This is the inverse of markdown-it's parser. It walks the flat token
    list and reconstructs valid Markdown, preserving the original formatting
    as much as possible.
    """

    def render(self, tokens: list[Token]) -> str:
        self._out: list[str] = []
        self._tokens = tokens
        i = 0
        n = len(tokens)
        while i < n:
            i = self._render_token(i)
        return ''.join(self._out)

    def _render_token(self, i: int) -> int:
        t = self._tokens[i]
        tt = t.type

        # ── Headings ──
        if tt == 'heading_open':
            level = int(t.tag[1])  # h1 → 1, h2 → 2
            self._out.append('#' * level + ' ')
            i += 1
            while i < len(self._tokens) and self._tokens[i].type != 'heading_close':
                i = self._render_token(i)
            self._out.append('\n\n')
            return i + 1  # skip heading_close

        # ── Paragraphs ──
        if tt == 'paragraph_open':
            i += 1
            while i < len(self._tokens) and self._tokens[i].type != 'paragraph_close':
                i = self._render_token(i)
            self._out.append('\n\n')
            return i + 1

        # ── Inline content ──
        if tt == 'inline':
            self._out.append(t.content)
            return i + 1

        # ── Fenced code blocks ──
        if tt == 'fence':
            info = t.info or ''
            self._out.append(f'```{info}\n{t.content}\n```\n\n')
            return i + 1

        # ── Horizontal rules ──
        if tt == 'hr':
            self._out.append('---\n\n')
            return i + 1

        # ── Tables ──
        if tt == 'table_open':
            j = i + 1
            while j < len(self._tokens) and self._tokens[j].type != 'table_close':
                j = self._render_token(j)
            self._out.append('\n')
            return j + 1

        if tt == 'thead_open':
            self._out.append('')
            return i + 1

        if tt == 'thead_close':
            return i + 1

        if tt == 'tbody_open':
            self._out.append('')
            return i + 1

        if tt == 'tbody_close':
            return i + 1

        if tt == 'tr_open':
            self._out.append('| ')
            i += 1
            while i < len(self._tokens) and self._tokens[i].type != 'tr_close':
                if self._tokens[i].type == 'th_open' or self._tokens[i].type == 'td_open':
                    i += 1
                    while i < len(self._tokens) and self._tokens[i].type not in ('th_close', 'td_close'):
                        i = self._render_token(i)
                    self._out.append(' | ')
                    i += 1
                else:
                    i += 1
            self._out.append('\n')
            return i + 1

        # ── Bullet lists ──
        if tt == 'bullet_list_open':
            self._out.append('\n')
            i += 1
            while i < len(self._tokens) and self._tokens[i].type != 'bullet_list_close':
                i = self._render_token(i)
            self._out.append('\n')
            return i + 1

        if tt == 'list_item_open':
            self._out.append('- ')
            i += 1
            while i < len(self._tokens) and self._tokens[i].type != 'list_item_close':
                i = self._render_token(i)
            return i + 1

        # ── Ordered lists ──
        if tt == 'ordered_list_open':
            self._out.append('\n')
            self._ol_counter = 1
            i += 1
            while i < len(self._tokens) and self._tokens[i].type != 'ordered_list_close':
                i = self._render_token(i)
            self._out.append('\n')
            return i + 1

        # ── Blockquotes ──
        if tt == 'blockquote_open':
            self._out.append('> ')
            i += 1
            while i < len(self._tokens) and self._tokens[i].type != 'blockquote_close':
                i = self._render_token(i)
            self._out.append('\n\n')
            return i + 1

        # ── Fallback: skip unknown tokens ──
        return i + 1


# ── Convenience: Full pipeline ─────────────────────────────────────────

def deduplicate_paper(
    markdown_text: str,
    llm_rewrite_fn,
    batch_size: int = 5,
) -> str:
    """Run the full AST-based deduplication pipeline.

    Args:
        markdown_text: The original paper in Markdown.
        llm_rewrite_fn: A callable (segments: list[dict]) → dict[int, str]
            that sends text segments to an LLM and returns rewritten versions
            keyed by segment ID.
        batch_size: How many text segments to send per LLM call.

    Returns:
        The rewritten Markdown document with all protected nodes intact.
    """
    deduper = LayoutPreservingDeduper()
    deduper.parse(markdown_text)
    segments = deduper.extract_text_segments()

    if not segments:
        return markdown_text  # nothing to rewrite

    # Batch segments and send to LLM
    rewritten_map: dict[int, str] = {}

    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]
        batch_result = llm_rewrite_fn(batch)
        rewritten_map.update(batch_result)

    return deduper.apply_and_render(rewritten_map)
