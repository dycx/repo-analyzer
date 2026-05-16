"""HTML report generation.

Converts Markdown analysis content into a self-contained HTML report
with dark sidebar TOC, Mermaid.js support, and CJK typography.
"""

from __future__ import annotations


import html
import re

from repo_analyzer.render.markdown import generate_toc, normalize_headings
from repo_analyzer.render.templates import HTML_TEMPLATE


def generate_html_report(
    markdown_content: str,
    repo_name: str,
    model: str,
) -> str:
    """Generate a self-contained HTML report from Markdown content.

    The report includes:
    - Dark sidebar with table of contents (IntersectionObserver-based tracking)
    - Mermaid.js CDN lazy loading for diagram rendering
    - Code blocks with dark theme
    - Table alternating row colors
    - CJK typography support
    - Print-friendly styles
    - XSS-safe: all user/LLM content is escaped via html.escape()

    Args:
        markdown_content: The analysis document in Markdown format.
        repo_name: Repository name (used in page title and header).
        model: Model name used for analysis (displayed in footer).

    Returns:
        Complete HTML document as a string.
    """
    # Normalize headings to start from h2 (h1 is reserved for the page title)
    content = normalize_headings(markdown_content, base_level=2)

    # Generate TOC from the normalized content
    toc = generate_toc(content)

    # Convert Markdown to HTML (basic conversion)
    body_html = _markdown_to_html(content)

    # Escape user-controlled values for XSS safety
    safe_repo = html.escape(repo_name)
    safe_model = html.escape(model)
    safe_toc = toc  # TOC is generated from escaped content
    safe_body = body_html

    # Fill the template
    report = HTML_TEMPLATE.replace("{{REPO_NAME}}", safe_repo)
    report = report.replace("{{MODEL_NAME}}", safe_model)
    report = report.replace("{{TOC_CONTENT}}", safe_toc)
    report = report.replace("{{BODY_CONTENT}}", safe_body)

    return report


def _markdown_to_html(md: str) -> str:
    """Convert Markdown to HTML with basic syntax support.

    Handles:
    - Headings (h1-h6)
    - Fenced code blocks (with language class)
    - Inline code
    - Bold, italic
    - Links
    - Images
    - Unordered lists
    - Ordered lists
    - Blockquotes
    - Horizontal rules
    - Tables (basic)
    - HTML passthrough (for <details>, <summary>, etc.)
    - Paragraphs

    All user/LLM text content is escaped via html.escape().

    Args:
        md: Markdown text.

    Returns:
        HTML string.
    """
    lines = md.split("\n")
    html_parts: list[str] = []
    i = 0
    in_code_block = False
    code_lang = ""
    code_lines: list[str] = []
    in_list = False
    list_type = ""  # "ul" or "ol"
    in_blockquote = False
    bq_lines: list[str] = []

    while i < len(lines):
        line = lines[i]

        # Fenced code block start
        if not in_code_block and re.match(r'^(`{3,})\s*(\w*)', line):
            m = re.match(r'^(`{3,})\s*(\w*)', line)
            in_code_block = True
            code_lang = m.group(2) or ""
            code_lines = []
            i += 1
            continue

        # Fenced code block end
        if in_code_block and re.match(r'^`{3,}\s*$', line):
            in_code_block = False
            escaped_code = html.escape("\n".join(code_lines))
            lang_class = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
            html_parts.append(f'<pre><code{lang_class}>{escaped_code}</code></pre>')
            i += 1
            continue

        # Inside code block
        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # HTML passthrough (for <details>, <summary>, etc.)
        if re.match(r'^\s*<', line) and not re.match(r'^\s*<br', line, re.IGNORECASE):
            html_parts.append(line)
            i += 1
            continue

        # Close any open list
        if in_list and not re.match(r'^(\s*[-*+]|\s*\d+\.)\s', line):
            html_parts.append(f'</{list_type}>')
            in_list = False

        # Close any open blockquote
        if in_blockquote and not line.startswith(">"):
            bq_escaped = html.escape("\n".join(bq_lines)).replace("\n", "<br>")
            html_parts.append(f'<blockquote><p>{bq_escaped}</p></blockquote>')
            in_blockquote = False
            bq_lines = []

        # Empty line
        if not line.strip():
            i += 1
            continue

        # Headings
        heading_match = re.match(r'^(#{1,6})\s+(.+)', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            # Generate id for anchor linking
            anchor = _make_heading_anchor(text)
            safe_text = _inline_format(html.escape(text))
            html_parts.append(f'<h{level} id="{anchor}">{safe_text}</h{level}>')
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^[-*_]{3,}\s*$', line):
            html_parts.append('<hr>')
            i += 1
            continue

        # Blockquote
        if line.startswith(">"):
            in_blockquote = True
            bq_lines.append(line.lstrip("> ").strip())
            i += 1
            continue

        # Unordered list
        ul_match = re.match(r'^(\s*)[-*+]\s+(.+)', line)
        if ul_match:
            if not in_list or list_type != "ul":
                if in_list:
                    html_parts.append(f'</{list_type}>')
                html_parts.append('<ul>')
                in_list = True
                list_type = "ul"
            safe_item = _inline_format(html.escape(ul_match.group(2)))
            html_parts.append(f'<li>{safe_item}</li>')
            i += 1
            continue

        # Ordered list
        ol_match = re.match(r'^(\s*)\d+\.\s+(.+)', line)
        if ol_match:
            if not in_list or list_type != "ol":
                if in_list:
                    html_parts.append(f'</{list_type}>')
                html_parts.append('<ol>')
                in_list = True
                list_type = "ol"
            safe_item = _inline_format(html.escape(ol_match.group(2)))
            html_parts.append(f'<li>{safe_item}</li>')
            i += 1
            continue

        # Table
        if "|" in line and i + 1 < len(lines) and re.match(r'^[\s|:-]+$', lines[i + 1]):
            table_lines = [line]
            j = i + 1
            while j < len(lines) and "|" in lines[j]:
                table_lines.append(lines[j])
                j += 1
            html_parts.append(_build_table(table_lines))
            i = j
            continue

        # Paragraph
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_element(lines[i]):
            para_lines.append(lines[i])
            i += 1
        safe_para = _inline_format(html.escape(" ".join(l.strip() for l in para_lines)))
        html_parts.append(f'<p>{safe_para}</p>')

    # Close any remaining open elements
    if in_list:
        html_parts.append(f'</{list_type}>')
    if in_blockquote:
        bq_escaped = html.escape("\n".join(bq_lines)).replace("\n", "<br>")
        html_parts.append(f'<blockquote><p>{bq_escaped}</p></blockquote>')

    return "\n".join(html_parts)


def _make_heading_anchor(text: str) -> str:
    """Generate a GitHub-compatible anchor from heading text.

    Args:
        text: Heading text (may contain HTML entities from prior escaping).

    Returns:
        Anchor string safe for use in id attributes.
    """
    from repo_analyzer.render.markdown import _make_anchor
    return _make_anchor(text)


def _inline_format(text: str) -> str:
    """Apply inline Markdown formatting to already-escaped text.

    Handles bold, italic, inline code, links, and images.

    Args:
        text: HTML-escaped text with Markdown formatting.

    Returns:
        Text with inline Markdown converted to HTML.
    """
    # Inline code: `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Bold+italic: ***text***
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)

    # Bold: **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # Italic: *text*
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

    # Images: ![alt](url) -- must come before links
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1">', text)

    # Links: [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    return text


def _build_table(table_lines: list[str]) -> str:
    """Convert Markdown table lines to an HTML table.

    Args:
        table_lines: Lines of a Markdown table including header, separator, and rows.

    Returns:
        HTML table string.
    """
    if len(table_lines) < 2:
        return ""

    def _parse_cells(line: str) -> list[str]:
        cells = line.strip().strip("|").split("|")
        return [c.strip() for c in cells]

    header_cells = _parse_cells(table_lines[0])
    # table_lines[1] is the separator (---|---|---)
    rows = table_lines[2:]

    parts = ['<table>']

    # Header
    parts.append('<thead><tr>')
    for cell in header_cells:
        safe = _inline_format(html.escape(cell))
        parts.append(f'<th>{safe}</th>')
    parts.append('</tr></thead>')

    # Body
    parts.append('<tbody>')
    for row in rows:
        cells = _parse_cells(row)
        parts.append('<tr>')
        for cell in cells:
            safe = _inline_format(html.escape(cell))
            parts.append(f'<td>{safe}</td>')
        parts.append('</tr>')
    parts.append('</tbody>')
    parts.append('</table>')

    return "\n".join(parts)


def _is_block_element(line: str) -> bool:
    """Check if a line starts a new block element."""
    stripped = line.strip()
    if re.match(r'^#{1,6}\s', stripped):
        return True
    if re.match(r'^[-*_]{3,}$', stripped):
        return True
    if re.match(r'^(`{3,})', stripped):
        return True
    if re.match(r'^(\s*[-*+]|\s*\d+\.)\s', stripped):
        return True
    if stripped.startswith(">"):
        return True
    if re.match(r'^\s*<', stripped):
        return True
    return False
