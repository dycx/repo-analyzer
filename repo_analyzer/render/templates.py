"""HTML/CSS/JS template strings for the analysis report.

Contains the full HTML5 template with:
- Dark sidebar (280px, fixed)
- Main content area (960px centered)
- Mermaid.js CDN with lazy loading
- Code block dark theme
- Table alternating row colors
- Details/summary styling
- CJK font stack
- color-scheme: light dark
- IntersectionObserver for TOC tracking
- scroll-margin-top for anchor links
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{REPO_NAME}} — 代码分析报告</title>
<style>
  :root {
    --sidebar-width: 280px;
    --content-width: 960px;
    --bg-primary: #1a1a2e;
    --bg-secondary: #16213e;
    --bg-content: #ffffff;
    --bg-code: #1e1e2e;
    --bg-code-inline: #f0f0f5;
    --text-primary: #e0e0e0;
    --text-secondary: #a0a0b8;
    --text-content: #1a1a2e;
    --text-code: #cdd6f4;
    --accent: #7c3aed;
    --accent-light: #a78bfa;
    --border: #2a2a4a;
    --table-alt-row: #f8f9fa;
    --blockquote-border: #7c3aed;
    --blockquote-bg: #f8f7ff;
    --scroll-margin: 80px;
    color-scheme: light dark;
  }

  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  html {
    scroll-behavior: smooth;
  }

  body {
    font-family:
      -apple-system, BlinkMacSystemFont,
      "Segoe UI", "Noto Sans SC", "PingFang SC", "Hiragino Sans GB",
      "Microsoft YaHei", "WenQuanYi Micro Hei",
      Roboto, "Helvetica Neue", Arial,
      sans-serif;
    line-height: 1.7;
    color: var(--text-content);
    background: var(--bg-content);
  }

  /* --- Sidebar --- */
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    width: var(--sidebar-width);
    height: 100vh;
    background: var(--bg-primary);
    color: var(--text-primary);
    overflow-y: auto;
    padding: 24px 16px;
    z-index: 100;
    border-right: 1px solid var(--border);
  }

  .sidebar-header {
    font-size: 14px;
    font-weight: 700;
    color: var(--accent-light);
    margin-bottom: 8px;
    letter-spacing: 0.5px;
  }

  .sidebar-meta {
    font-size: 11px;
    color: var(--text-secondary);
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }

  .sidebar a {
    color: var(--text-primary);
    text-decoration: none;
    display: block;
    padding: 4px 0;
    font-size: 13px;
    line-height: 1.5;
    border-left: 2px solid transparent;
    padding-left: 8px;
    transition: all 0.15s ease;
  }

  .sidebar a:hover {
    color: var(--accent-light);
    border-left-color: var(--accent);
  }

  .sidebar a.active {
    color: var(--accent-light);
    border-left-color: var(--accent-light);
    font-weight: 600;
  }

  .toc-h2 { padding-left: 8px; font-weight: 600; }
  .toc-h3 { padding-left: 20px; }
  .toc-h4 { padding-left: 32px; font-size: 12px; }
  .toc-h5 { padding-left: 44px; font-size: 11px; }
  .toc-h6 { padding-left: 56px; font-size: 11px; color: var(--text-secondary); }

  /* --- Main Content --- */
  .main {
    margin-left: var(--sidebar-width);
    padding: 40px 48px;
    max-width: calc(var(--content-width) + 96px);
  }

  .main h1 {
    font-size: 28px;
    font-weight: 800;
    margin-bottom: 8px;
    color: var(--text-content);
    border-bottom: 2px solid var(--accent);
    padding-bottom: 8px;
  }

  .main h2 {
    font-size: 22px;
    font-weight: 700;
    margin-top: 40px;
    margin-bottom: 16px;
    color: var(--text-content);
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 6px;
  }

  .main h3 {
    font-size: 18px;
    font-weight: 600;
    margin-top: 32px;
    margin-bottom: 12px;
    color: var(--text-content);
  }

  .main h4 {
    font-size: 15px;
    font-weight: 600;
    margin-top: 24px;
    margin-bottom: 8px;
  }

  .main h5, .main h6 {
    font-size: 14px;
    font-weight: 600;
    margin-top: 20px;
    margin-bottom: 8px;
    color: #555;
  }

  /* Anchor scroll offset */
  .main h1[id], .main h2[id], .main h3[id],
  .main h4[id], .main h5[id], .main h6[id] {
    scroll-margin-top: var(--scroll-margin);
  }

  .main p {
    margin-bottom: 12px;
  }

  .main a {
    color: var(--accent);
    text-decoration: none;
  }

  .main a:hover {
    text-decoration: underline;
  }

  /* --- Code Blocks --- */
  .main pre {
    background: var(--bg-code);
    color: var(--text-code);
    border-radius: 8px;
    padding: 16px 20px;
    overflow-x: auto;
    margin: 16px 0;
    font-size: 13px;
    line-height: 1.6;
    font-family: "JetBrains Mono", "Fira Code", "SF Mono", "Cascadia Code",
                 Consolas, "Liberation Mono", Menlo, monospace;
  }

  .main pre code {
    background: transparent;
    padding: 0;
    border-radius: 0;
    font-size: inherit;
  }

  .main code {
    background: var(--bg-code-inline);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.9em;
    font-family: "JetBrains Mono", "Fira Code", "SF Mono", Consolas,
                 "Liberation Mono", Menlo, monospace;
  }

  /* --- Tables --- */
  .main table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 14px;
  }

  .main thead th {
    background: var(--bg-primary);
    color: var(--text-primary);
    padding: 10px 14px;
    text-align: left;
    font-weight: 600;
    border: 1px solid var(--border);
  }

  .main tbody td {
    padding: 8px 14px;
    border: 1px solid #e5e7eb;
  }

  .main tbody tr:nth-child(even) {
    background: var(--table-alt-row);
  }

  .main tbody tr:hover {
    background: #eef2ff;
  }

  /* --- Details / Summary --- */
  .main details {
    margin: 16px 0;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    overflow: hidden;
  }

  .main summary {
    padding: 12px 16px;
    background: #f9fafb;
    cursor: pointer;
    font-weight: 600;
    font-size: 14px;
    user-select: none;
    border-bottom: 1px solid #e5e7eb;
  }

  .main summary:hover {
    background: #f3f4f6;
  }

  .main details[open] summary {
    border-bottom: 1px solid #e5e7eb;
  }

  .main details > *:not(summary) {
    padding: 0 16px;
  }

  .main details > pre {
    margin: 12px 0;
    border-radius: 0;
  }

  /* --- Blockquote --- */
  .main blockquote {
    border-left: 4px solid var(--blockquote-border);
    background: var(--blockquote-bg);
    padding: 12px 16px;
    margin: 16px 0;
    border-radius: 0 8px 8px 0;
  }

  /* --- Lists --- */
  .main ul, .main ol {
    margin: 8px 0 16px 24px;
  }

  .main li {
    margin-bottom: 4px;
  }

  /* --- Horizontal Rule --- */
  .main hr {
    border: none;
    border-top: 1px solid #e5e7eb;
    margin: 32px 0;
  }

  /* --- Images --- */
  .main img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    margin: 8px 0;
  }

  /* --- Footer --- */
  .footer {
    margin-top: 48px;
    padding-top: 24px;
    border-top: 1px solid #e5e7eb;
    font-size: 12px;
    color: #999;
    text-align: center;
  }

  /* --- Responsive --- */
  @media (max-width: 1024px) {
    .sidebar {
      display: none;
    }
    .main {
      margin-left: 0;
      padding: 24px 20px;
    }
  }

  /* --- Print --- */
  @media print {
    .sidebar {
      display: none;
    }
    .main {
      margin-left: 0;
      padding: 0;
      max-width: 100%;
    }
    .main pre {
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .main details {
      border: 1px solid #ccc;
    }
    .main details[open] {
      break-inside: avoid;
    }
    .footer {
      display: none;
    }
  }

  /* --- Scrollbar (sidebar) --- */
  .sidebar::-webkit-scrollbar {
    width: 6px;
  }
  .sidebar::-webkit-scrollbar-track {
    background: transparent;
  }
  .sidebar::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 3px;
  }
  .sidebar::-webkit-scrollbar-thumb:hover {
    background: #3a3a5a;
  }
</style>
</head>
<body>

<!-- Sidebar TOC -->
<nav class="sidebar" id="sidebar">
  <div class="sidebar-header">{{REPO_NAME}}</div>
  <div class="sidebar-meta">Generated by repo-analyzer v2.0 &middot; Model: {{MODEL_NAME}}</div>
  <div id="toc">
    {{TOC_CONTENT}}
  </div>
</nav>

<!-- Main Content -->
<main class="main" id="content">
  <h1>{{REPO_NAME}} — 代码分析报告</h1>
  {{BODY_CONTENT}}
  <div class="footer">
    <p>Generated by <strong>repo-analyzer v2.0</strong> &middot; Model: {{MODEL_NAME}}</p>
  </div>
</main>

<!-- Mermaid.js (lazy loaded) -->
<script>
(function() {
  // Lazy load Mermaid.js only when mermaid blocks exist
  function loadMermaid() {
    if (document.querySelector('.mermaid, pre code[class*="language-mermaid"], code.language-mermaid')) {
      var script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
      script.onload = function() {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: 'dark',
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
        });
        // Find all mermaid code blocks and render them
        document.querySelectorAll('pre code.language-mermaid').forEach(function(el) {
          var pre = el.parentElement;
          var container = document.createElement('div');
          container.className = 'mermaid';
          container.textContent = el.textContent;
          pre.parentNode.replaceChild(container, pre);
        });
        mermaid.run({ querySelector: '.mermaid' });
      };
      document.head.appendChild(script);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadMermaid);
  } else {
    loadMermaid();
  }
})();
</script>

<!-- TOC IntersectionObserver for current position tracking -->
<script>
(function() {
  var tocLinks = document.querySelectorAll('#toc a');
  if (!tocLinks.length) return;

  // Build map of id -> link element
  var linkMap = {};
  tocLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    if (href && href.startsWith('#')) {
      linkMap[href.slice(1)] = link;
    }
  });

  var headingIds = Object.keys(linkMap);
  if (!headingIds.length) return;

  var observer = new IntersectionObserver(
    function(entries) {
      entries.forEach(function(entry) {
        var id = entry.target.getAttribute('id');
        if (!id || !linkMap[id]) return;
        if (entry.isIntersecting) {
          // Remove active from all
          tocLinks.forEach(function(l) { l.classList.remove('active'); });
          linkMap[id].classList.add('active');
          // Scroll sidebar to keep the active link visible
          linkMap[id].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      });
    },
    {
      rootMargin: '-80px 0px -70% 0px',
      threshold: 0
    }
  );

  headingIds.forEach(function(id) {
    var el = document.getElementById(id);
    if (el) observer.observe(el);
  });
})();
</script>

</body>
</html>"""
