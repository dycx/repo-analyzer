"""
Report generation utilities for repo-analyzer.

Provides markdown processing (heading normalization, TOC generation) and
HTML report generation with professional styling.
"""

import re
import html
from datetime import datetime

try:
    import markdown as md_lib
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

__all__ = ["normalize_headings", "generate_toc", "generate_html_report"]


def normalize_headings(content: str, base_level: int = 3) -> str:
    """Normalize heading levels so the minimum heading starts at base_level.

    Preserves code blocks (``` ... ```) so headings inside them are untouched.
    Removes empty headings (a heading line with no content before the next heading).
    """
    lines = content.split("\n")
    result = []
    in_code_block = False
    i = 0

    # First pass: find the minimum heading level outside code blocks
    min_level = None
    cb = False
    for line in lines:
        if line.strip().startswith("```"):
            cb = not cb
            continue
        if cb:
            continue
        m = re.match(r"^(#{1,6})\s+\S", line)
        if m:
            level = len(m.group(1))
            if min_level is None or level < min_level:
                min_level = level

    if min_level is None:
        # No headings found; return as-is
        return content

    offset = base_level - min_level  # how much to shift

    # Second pass: rewrite headings and remove empty ones
    in_code_block = False
    pending_heading = None  # (new_level, text) for a heading waiting for content
    i = 0
    while i < len(lines):
        line = lines[i]

        # Track code fences
        if line.strip().startswith("```"):
            in_code_block = not in_code_block

        if in_code_block:
            # Flush pending heading before code block
            if pending_heading is not None:
                lvl, txt = pending_heading
                result.append(f"{'#' * lvl} {txt}")
                pending_heading = None
            result.append(line)
            i += 1
            continue

        # Check if this is a heading line
        hm = re.match(r"^(#{1,6})\s+(.*)", line)
        if hm:
            old_level = len(hm.group(1))
            heading_text = hm.group(2).strip()

            # If there's a pending heading with no content, discard it (empty heading)
            # — we just don't flush it.

            new_level = min(old_level + offset, 6)
            new_level = max(new_level, 1)

            if heading_text == "":
                # Empty heading line like "## \n" — treat as empty, skip
                i += 1
                continue

            pending_heading = (new_level, heading_text)
            i += 1
            continue

        # Non-heading line
        if pending_heading is not None:
            # There was a heading before this line — it's not empty, flush it
            lvl, txt = pending_heading
            result.append(f"{'#' * lvl} {txt}")
            pending_heading = None

        result.append(line)
        i += 1

    # Flush any trailing heading
    if pending_heading is not None:
        lvl, txt = pending_heading
        result.append(f"{'#' * lvl} {txt}")

    return "\n".join(result)


def _make_anchor(heading_text: str) -> str:
    """Convert heading text to a GitHub-compatible anchor id.

    Rules:
    - Lowercase
    - Replace spaces with hyphens
    - Remove backticks
    - Remove special characters except hyphens (keep CJK chars, digits, letters)
    - Strip leading/trailing dots and hyphens from each segment
    - Collapse multiple hyphens
    - Strip leading/trailing hyphens
    """
    # Remove backticks
    text = heading_text.replace("`", "")
    # Remove leading number-dot-space patterns like "1. " → keep the number
    # but the dot and space become a hyphen naturally
    # Lowercase
    text = text.lower()
    # Replace spaces and dots (except in the middle of numbers) with hyphens
    # First, replace spaces with hyphens
    text = text.replace(" ", "-")
    # Replace dots with hyphens
    text = text.replace(".", "-")
    # Remove characters that are not: word chars (letters, digits, underscore), CJK, or hyphens
    # Keep unicode word chars, digits, hyphens
    text = re.sub(r"[^\w\u4e00-\u9fff\u3400-\u4dbf\u2e80-\u2eff\u3000-\u303f\uff00-\uffef\uac00-\ud7af\u3040-\u309f\u30a0-\u30ff-]", "", text)
    # Collapse multiple hyphens
    text = re.sub(r"-{2,}", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")
    return text


def generate_toc(content: str) -> str:
    """Generate a markdown table of contents from headings in the content.

    Only considers headings outside of code fences.
    Indentation: ## = none, ### = 2 spaces, #### = 4 spaces, etc.
    """
    lines = content.split("\n")
    toc_lines = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if not m:
            continue

        level = len(m.group(1))
        text = m.group(2).strip()

        if not text:
            continue

        # Skip h1 (usually the document title) — TOC starts from h2
        if level < 2:
            continue

        anchor = _make_anchor(text)
        indent = "  " * (level - 2)
        toc_lines.append(f"{indent}- [{text}](#{anchor})")

    return "\n".join(toc_lines)


def _basic_md_to_html(content: str) -> str:
    """Minimal markdown-to-HTML converter (fallback if `markdown` lib unavailable)."""
    lines = content.split("\n")
    html_parts = []
    in_code = False
    code_lang = ""
    code_buf = []
    in_table = False
    in_list = False
    list_type = None  # 'ul' or 'ol'
    para_buf = []

    def flush_para():
        nonlocal para_buf
        if para_buf:
            text = " ".join(para_buf)
            text = _inline_format(text)
            html_parts.append(f"<p>{text}</p>")
            para_buf = []

    def flush_list():
        nonlocal in_list, list_type
        if in_list:
            html_parts.append(f"</{list_type}>")
            in_list = False

    def _inline_format(t):
        # bold
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        # italic
        t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
        # inline code
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        # links
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
        return t

    for line in lines:
        # Code fences
        if line.strip().startswith("```"):
            if not in_code:
                flush_para()
                flush_list()
                in_code = True
                code_lang = line.strip()[3:].strip()
                code_buf = []
                lang_attr = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
                html_parts.append(f"<pre><code{lang_attr}>")
            else:
                html_parts.append(html.escape("\n".join(code_buf)))
                html_parts.append("</code></pre>")
                in_code = False
            continue

        if in_code:
            code_buf.append(line)
            continue

        # Empty line
        if not line.strip():
            flush_para()
            flush_list()
            continue

        # Headings
        hm = re.match(r"^(#{1,6})\s+(.*)", line)
        if hm:
            flush_para()
            flush_list()
            level = len(hm.group(1))
            text = _inline_format(hm.group(2).strip())
            anchor = _make_anchor(hm.group(2).strip())
            html_parts.append(f'<h{level} id="{anchor}">{text}</h{level}>')
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", line.strip()):
            flush_para()
            flush_list()
            html_parts.append("<hr>")
            continue

        # Table row
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Check if separator row
            if all(re.match(r"^[-:]+$", c) for c in cells if c):
                continue
            flush_para()
            if not in_table:
                flush_list()
                html_parts.append("<table>")
                tag = "th"
                in_table = True
            else:
                tag = "td"
            row_html = "".join(f"<{tag}>{_inline_format(html.escape(c))}</{tag}>" for c in cells)
            html_parts.append(f"<tr>{row_html}</tr>")
            continue
        else:
            if in_table:
                html_parts.append("</table>")
                in_table = False

        # Unordered list
        lm = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if lm:
            flush_para()
            if not in_list:
                in_list = True
                list_type = "ul"
                html_parts.append("<ul>")
            html_parts.append(f"<li>{_inline_format(lm.group(2))}</li>")
            continue

        # Ordered list
        om = re.match(r"^(\s*)\d+[.)]\s+(.*)", line)
        if om:
            flush_para()
            if not in_list or list_type != "ol":
                flush_list()
                in_list = True
                list_type = "ol"
                html_parts.append("<ol>")
            html_parts.append(f"<li>{_inline_format(om.group(2))}</li>")
            continue

        # flush list if not a list item
        flush_list()
        # Paragraph text
        para_buf.append(line)

    flush_para()
    flush_list()
    if in_table:
        html_parts.append("</table>")
    if in_code:
        html_parts.append(html.escape("\n".join(code_buf)))
        html_parts.append("</code></pre>")

    return "\n".join(html_parts)


def _convert_md_to_html(content: str) -> str:
    """Convert markdown to HTML, using `markdown` library if available."""
    if HAS_MARKDOWN:
        # GFM-compatible extensions (GitHub Flavored Markdown)
        extensions = [
            "tables",          # GFM tables
            "fenced_code",     # GFM fenced code blocks
            "codehilite",      # Syntax highlighting
            "toc",             # Auto-generated heading anchors
            "attr_list",       # Attribute lists
            "sane_lists",      # Better list handling (CommonMark-compatible)
            "smarty",          # Smart quotes/dashes
            "md_in_html",      # Markdown inside HTML blocks
        ]
        ext_configs = {
            "codehilite": {"css_class": "highlight", "guess_lang": True},
            "toc": {"permalink": False, "title": ""},
        }
        try:
            return md_lib.markdown(
                content, extensions=extensions, extension_configs=ext_configs,
                output_format="html5",
            )
        except Exception:
            pass
    return _basic_md_to_html(content)


def _extract_mermaid_blocks(content: str):
    """Extract mermaid blocks from content, return (modified_content, list_of_blocks)."""
    blocks = []
    pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

    def replacer(m):
        blocks.append(m.group(1).strip())
        return f"__MERMAID_PLACEHOLDER_{len(blocks) - 1}__"

    modified = pattern.sub(replacer, content)
    return modified, blocks


def _extract_toc_for_html(content: str) -> list:
    """Extract headings for sidebar TOC generation. Returns list of (level, text, anchor)."""
    lines = content.split("\n")
    entries = []
    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level < 2 or not text:
                continue
            anchor = _make_anchor(text)
            # Strip markdown formatting for display
            clean = re.sub(r"`([^`]*)`", r"\1", text)
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
            clean = re.sub(r"\*(.+?)\*", r"\1", clean)
            entries.append((level, clean, anchor))
    return entries


def generate_html_report(md_content: str, repo_name: str, model: str) -> str:
    """Convert markdown content to a styled HTML report.

    Professional styling with dark sidebar TOC, clean typography,
    mermaid.js support, and print-friendly layout.
    """
    # Extract mermaid blocks before converting
    processed_md, mermaid_blocks = _extract_mermaid_blocks(md_content)

    # Convert to HTML
    body_html = _convert_md_to_html(processed_md)

    # Restore mermaid blocks with proper div wrappers
    for idx, block in enumerate(mermaid_blocks):
        placeholder = f"__MERMAID_PLACEHOLDER_{idx}__"
        escaped = html.escape(block)
        mermaid_div = f'<div class="mermaid">{escaped}</div>'
        body_html = body_html.replace(
            f"<p>{placeholder}</p>", mermaid_div
        )
        body_html = body_html.replace(placeholder, mermaid_div)

    # Build sidebar TOC
    toc_entries = _extract_toc_for_html(md_content)
    sidebar_items = []
    for level, text, anchor in toc_entries:
        indent_px = (level - 2) * 16
        safe_text = html.escape(text)
        if len(safe_text) > 48:
            safe_text = safe_text[:46] + "…"
        sidebar_items.append(
            f'<a href="#{anchor}" class="toc-item toc-l{level}" '
            f'style="padding-left:{indent_px + 16}px">{safe_text}</a>'
        )
    sidebar_toc = "\n".join(sidebar_items)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_repo = html.escape(repo_name)
    safe_model = html.escape(model)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="Reverse engineering analysis report for {safe_repo}">
<meta name="generator" content="repo-analyzer">
<title>{safe_repo} — Analysis Report</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  color-scheme: light dark;
  --sidebar-bg: #1a1a2e;
  --sidebar-text: #a0a0b8;
  --sidebar-active: #ffffff;
  --accent: #0066cc;
  --accent-light: #e8f0fe;
  --bg: #ffffff;
  --bg-secondary: #f7f7fa;
  --text: #1a1a2e;
  --text-secondary: #555;
  --border: #e5e5ea;
  --code-bg: #f5f5f7;
  --sidebar-w: 280px;
}}

html {{
  scroll-behavior: smooth;
  scroll-padding-top: 24px;
}}

/* Anchor offset for fixed header */
h1[id], h2[id], h3[id], h4[id], h5[id], h6[id] {{
  scroll-margin-top: 24px;
}}

body {{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
    Roboto, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 15px;
  line-height: 1.6;
  color: var(--text);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
  word-break: break-word;
  overflow-wrap: break-word;
}}

/* CJK support */
:lang(zh), :lang(ja), :lang(ko) {{
  word-break: break-all;
  line-break: anywhere;
  text-autospace: ideograph-alpha ideograph-numeric;
}}

/* Sidebar */
.sidebar {{
  position: fixed;
  top: 0; left: 0;
  width: var(--sidebar-w);
  height: 100vh;
  background: var(--sidebar-bg);
  color: var(--sidebar-text);
  overflow-y: auto;
  z-index: 100;
  display: flex;
  flex-direction: column;
  transition: transform 0.3s ease;
}}

.sidebar.collapsed {{ transform: translateX(calc(-1 * var(--sidebar-w))); }}

.sidebar-header {{
  padding: 24px 20px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  flex-shrink: 0;
}}

.sidebar-header h2 {{
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}

.sidebar-header .meta {{
  font-size: 12px;
  color: var(--sidebar-text);
  opacity: 0.7;
}}

.toc-item {{
  display: block;
  padding: 6px 16px;
  color: var(--sidebar-text);
  text-decoration: none;
  font-size: 13px;
  line-height: 1.5;
  transition: color 0.15s, background 0.15s;
  border-left: 3px solid transparent;
}}

.toc-item:hover {{
  color: var(--sidebar-active);
  background: rgba(255,255,255,0.04);
}}

.toc-item.active {{
  color: var(--sidebar-active);
  border-left-color: var(--accent);
  background: rgba(255,255,255,0.06);
}}

.toc-l2 {{ font-weight: 600; color: #ccc; }}
.toc-l3 {{ font-weight: 400; }}
.toc-l4, .toc-l5, .toc-l6 {{ font-weight: 300; font-size: 12px; }}

/* Toggle button */
.sidebar-toggle {{
  position: fixed;
  top: 12px;
  left: 12px;
  z-index: 200;
  width: 36px; height: 36px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  font-size: 18px;
  color: var(--text);
  transition: left 0.3s ease;
}}

.sidebar-toggle.shifted {{ left: calc(var(--sidebar-w) + 12px); }}

/* Main content */
.content {{
  margin-left: var(--sidebar-w);
  padding: 40px 48px 80px;
  max-width: 960px;
  transition: margin-left 0.3s ease;
}}

.content.expanded {{ margin-left: 0; }}

/* Typography */
h1 {{ font-size: 2em; font-weight: 700; margin: 0.8em 0 0.4em; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }}
h2 {{ font-size: 1.5em; font-weight: 700; margin: 1.6em 0 0.5em; border-bottom: 1px solid var(--border); padding-bottom: 0.2em; }}
h3 {{ font-size: 1.2em; font-weight: 600; margin: 1.4em 0 0.4em; }}
h4 {{ font-size: 1em; font-weight: 600; margin: 1.2em 0 0.3em; }}
h5, h6 {{ font-size: 0.9em; font-weight: 600; margin: 1em 0 0.3em; color: var(--text-secondary); }}

p {{ margin: 0.6em 0; }}

a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* Code */
code {{
  font-family: "SF Mono", "Fira Code", "JetBrains Mono", Menlo, monospace;
  font-size: 0.88em;
  background: var(--code-bg);
  padding: 0.15em 0.4em;
  border-radius: 4px;
}}

pre {{
  background: #1e1e2e;
  color: #cdd6f4;
  border-radius: 8px;
  padding: 16px 20px;
  overflow-x: auto;
  margin: 1em 0;
  line-height: 1.5;
}}

pre code {{
  background: none;
  padding: 0;
  font-size: 13px;
  color: inherit;
}}

/* Tables */
table {{
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: 14px;
}}

th, td {{
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}}

th {{
  font-weight: 600;
  background: var(--bg-secondary);
  border-bottom: 2px solid var(--border);
}}

tr:nth-child(even) {{ background: var(--bg-secondary); }}
tr:hover {{ background: var(--accent-light); }}

/* Lists */
ul, ol {{ margin: 0.5em 0; padding-left: 1.8em; }}
li {{ margin: 0.25em 0; }}

/* Blockquote */
blockquote {{
  border-left: 4px solid var(--accent);
  margin: 1em 0;
  padding: 0.5em 1em;
  background: var(--accent-light);
  border-radius: 0 6px 6px 0;
  color: var(--text-secondary);
}}

/* Horizontal rule */
hr {{
  border: none;
  border-top: 1px solid var(--border);
  margin: 2em 0;
}}

/* Details / Collapsible */
details {{
  margin: 1em 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}}

details summary {{
  padding: 12px 16px;
  background: var(--bg-secondary);
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  user-select: none;
  list-style: none;
  display: flex;
  align-items: center;
}}

details summary::before {{
  content: "▸";
  margin-right: 8px;
  font-size: 12px;
  transition: transform 0.2s;
}}

details[open] summary::before {{ transform: rotate(90deg); }}
details summary::-webkit-details-marker {{ display: none; }}

details > div, details > p, details > ul, details > ol {{
  padding: 12px 16px;
}}

/* Mermaid */
.mermaid {{
  text-align: center;
  margin: 1.5em 0;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  overflow-x: auto;
}}

/* Images */
img {{ max-width: 100%; border-radius: 6px; margin: 0.5em 0; }}

/* Footer */
.report-footer {{
  margin-left: var(--sidebar-w);
  padding: 1.5em 48px 2em;
  border-top: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-secondary);
  transition: margin-left 0.3s ease;
}}

.content.expanded ~ .report-footer {{
  margin-left: 0;
}}

/* Scrollbar */
.sidebar {{
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.15) transparent;
}}
.sidebar::-webkit-scrollbar {{ width: 4px; }}
.sidebar::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.15); border-radius: 2px; }}

/* Keyboard navigation */
:focus-visible {{
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 4px;
}}

.toc-item:focus-visible {{
  outline-color: var(--sidebar-active);
}}

/* Print */
@media print {{
  .sidebar, .sidebar-toggle {{ display: none !important; }}
  .content {{ margin-left: 0 !important; padding: 20px !important; max-width: 100% !important; }}
  .report-footer {{ margin-left: 0 !important; padding: 1em 20px !important; }}
  pre {{ white-space: pre-wrap; word-wrap: break-word; }}
  table {{ font-size: 12px; }}
  h1, h2, h3 {{ page-break-after: avoid; }}
  details {{ break-inside: avoid; }}
  details[open] {{ break-inside: auto; }}
}}

/* Responsive */
@media (max-width: 900px) {{
  .sidebar {{ transform: translateX(calc(-1 * var(--sidebar-w))); }}
  .sidebar.open {{ transform: translateX(0); }}
  .content {{ margin-left: 0; padding: 24px 20px 60px; }}
  .report-footer {{ margin-left: 0; padding: 1.5em 20px 2em; }}
  .sidebar-toggle {{ display: flex; }}
}}
</style>
</head>
<body>

<button class="sidebar-toggle" id="sidebarToggle" title="Toggle TOC">☰</button>

<nav class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <h2>{safe_repo}</h2>
    <div class="meta">Model: {safe_model}<br>Generated: {generated_at}</div>
  </div>
  <div style="padding: 8px 0;">
{sidebar_toc}
  </div>
</nav>

<main class="content" id="mainContent">
{body_html}
</main>

<footer class="report-footer">
  <p>Report generated on {generated_at} using <strong>{safe_model}</strong></p>
</footer>

<script>
// Sidebar toggle
const sidebar = document.getElementById('sidebar');
const toggle = document.getElementById('sidebarToggle');
const mainContent = document.getElementById('mainContent');
let sidebarOpen = window.innerWidth > 900;

function updateSidebar() {{
  if (window.innerWidth <= 900) {{
    sidebar.classList.toggle('open', sidebarOpen);
  }} else {{
    sidebar.classList.toggle('collapsed', !sidebarOpen);
    mainContent.classList.toggle('expanded', !sidebarOpen);
    toggle.classList.toggle('shifted', sidebarOpen);
  }}
}}

toggle.addEventListener('click', () => {{ sidebarOpen = !sidebarOpen; updateSidebar(); }});
updateSidebar();
window.addEventListener('resize', updateSidebar);

// Active TOC tracking
const tocItems = document.querySelectorAll('.toc-item');
const headings = [];
tocItems.forEach(item => {{
  const id = item.getAttribute('href').slice(1);
  const el = document.getElementById(id);
  if (el) headings.push({{ el, item }});
}});

if (headings.length) {{
  const observer = new IntersectionObserver(entries => {{
    entries.forEach(entry => {{
      if (entry.isIntersecting) {{
        tocItems.forEach(i => i.classList.remove('active'));
        const match = headings.find(h => h.el === entry.target);
        if (match) match.item.classList.add('active');
      }}
    }});
  }}, {{ rootMargin: '-10% 0px -80% 0px' }});
  headings.forEach(h => observer.observe(h.el));
}}

// Smooth scroll for sidebar links
tocItems.forEach(item => {{
  item.addEventListener('click', e => {{
    if (window.innerWidth <= 900) {{ sidebarOpen = false; updateSidebar(); }}
  }});
}});
</script>

<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js" async></script>
<script>
document.addEventListener('DOMContentLoaded', () => {{
  if (typeof mermaid !== 'undefined') {{
    mermaid.initialize({{
      startOnLoad: true,
      theme: 'default',
      securityLevel: 'loose',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }});
  }}
}});
</script>

</body>
</html>"""
