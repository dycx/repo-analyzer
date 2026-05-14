#!/usr/bin/env python3
"""Assemble final document from Phase 2 module analyses + Phase 3 synthesis."""

from pathlib import Path

analysis_dir = Path("/Users/dycx/code/nginx/.code-analysis")
output_path = Path("/Users/dycx/code/nginx/nginx-analysis.md")

# Load synthesis
synthesis = (analysis_dir / "synthesis.md").read_text(encoding="utf-8")

# Module order (logical dependency order)
module_order = [
    "src_core",
    "src_event",
    "src_event_modules",
    "src_event_quic",
    "src_event_quic_bpf",
    "src_http",
    "src_http_modules",
    "src_http_modules_perl",
    "src_http_v2",
    "src_http_v3",
    "src_mail",
    "src_stream",
    "src_os_unix",
    "src_os_win32",
    "src_misc",
]

modules_dir = analysis_dir / "module_analyses"
module_files = {f.stem: f for f in modules_dir.glob("*.md")}

# Build document
parts = []

# Title
parts.append("# Nginx \u2014 \u9006\u5411\u5de5\u7a0b\u6587\u6863\n")
parts.append(
    '> **\u751f\u6210\u539f\u5219**: \u672c\u6587\u6863\u8fbe\u5230\u201c\u53ef\u91cd\u5efa\u201d\u7ea7\u522b'
    ' \u2014 \u5f00\u53d1\u8005\u4ec5\u51ed\u6b64\u6587\u6863\u53ef\u91cd\u5efa\u529f\u80fd\u7b49\u4ef7\u7684\u9879\u76ee'
    '\uff08\u8bef\u5dee < 5%\uff09\u3002'
)
parts.append(
    '> **\u6e90\u7801\u89c4\u6a21**: 248,757 \u884c C \u4ee3\u7801 | 399 \u6e90\u6587\u4ef6 | 15 \u6a21\u5757 '
    '| 3,277 \u51fd\u6570 | 5,349 \u7b26\u53f7'
)
parts.append("")

# TOC
parts.append("## \u76ee\u5f55\n")
parts.append("1. [\u67b6\u6784\u5168\u666f](#1-\u67b6\u6784\u5168\u666f)")
parts.append("2. [\u6a21\u5757\u8be6\u89e3](#2-\u6a21\u5757\u8be6\u89e3)")
for i, name in enumerate(module_order, 1):
    display = name.replace("src_", "").replace("_", "/")
    parts.append(f"   - [{display}](#2{i}-{name.replace('_', '-')})")
parts.append("3. [\u91cd\u5efa\u6307\u5357](#3-\u91cd\u5efa\u6307\u5357)")
parts.append("")

# Section 1: Architecture
parts.append("---\n")
parts.append("## 1. \u67b6\u6784\u5168\u666f\n")
parts.append(synthesis)

# Section 2: Module details
parts.append("\n---\n")
parts.append("## 2. \u6a21\u5757\u8be6\u89e3\n")
parts.append(
    '> \u4ee5\u4e0b\u6bcf\u4e2a\u6a21\u5757\u7684\u5206\u6790\u5305\u542b: '
    '\u804c\u8d23\u3001\u516c\u5171\u63a5\u53e3\u6e05\u5355\uff08\u542b\u7b7e\u540d\uff09\u3001'
    '\u6838\u5fc3\u7b97\u6cd5\u6d41\u7a0b\u3001\u6570\u636e\u7ed3\u6784\u3001\u5f02\u5e38\u5904\u7406\u3001'
    '\u8fb9\u754c\u6761\u4ef6\u3001\u5916\u90e8\u4f9d\u8d56\u4f7f\u7528\u6a21\u5f0f\u3001\u8bbe\u8ba1\u51b3\u7b56\u3002\n'
)

for i, name in enumerate(module_order, 1):
    display = name.replace("src_", "").replace("_", "/")
    parts.append(f"### 2.{i} `{display}`\n")
    if name in module_files:
        content = module_files[name].read_text(encoding="utf-8")
        parts.append(content)
    else:
        parts.append(f"*Module analysis missing: {name}*")
    parts.append("")

# Section 3: Rebuild guide
parts.append("\n---\n")
parts.append("## 3. \u91cd\u5efa\u6307\u5357\n")
parts.append("""\u5982\u679c\u8981\u4ece\u96f6\u91cd\u5efa Nginx\uff0c\u4ee5\u4e0b\u662f\u5173\u952e\u6307\u5bfc:

### 3.1 \u63a8\u8350\u5b9e\u73b0\u987a\u5e8f

```
\u9636\u6bb5 1: \u57fa\u7840\u5c42 (src/core)
  \u251c\u2500\u2500 \u5185\u5b58\u6c60 (ngx_palloc) \u2014 \u6240\u6709\u5206\u914d\u7684\u57fa\u77f3
  \u251c\u2500\u2500 \u65e5\u5fd7\u7cfb\u7edf (ngx_log) \u2014 \u8c03\u8bd5\u548c\u76d1\u63a7\u7684\u57fa\u7840
  \u251c\u2500\u2500 \u914d\u7f6e\u89e3\u6790 (ngx_conf_file) \u2014 \u9a71\u52a8\u6240\u6709\u6a21\u5757\u884c\u4e3a
  \u251c\u2500\u2500 \u57fa\u7840\u6570\u636e\u7ed3\u6784 (array, list, rbtree, hash)
  \u2514\u2500\u2500 \u5b57\u7b26\u4e32\u4e0e\u7f13\u51b2\u533a\u7ba1\u7406 (ngx_string, ngx_buf)

\u9636\u6bb5 2: \u4e8b\u4ef6\u5c42 (src/event)
  \u251c\u2500\u2500 \u4e8b\u4ef6\u62bd\u8c61 (ngx_event_t, ngx_connection_t)
  \u251c\u2500\u2500 \u5e73\u53f0\u9002\u914d: epoll (Linux) / kqueue (BSD) / IOCP (Windows)
  \u251c\u2500\u2500 \u5b9a\u65f6\u5668 (\u7ea2\u9ed1\u6811)
  \u251c\u2500\u2500 \u4fe1\u53f7\u5904\u7406
  \u2514\u2500\u2500 SSL/TLS \u96c6\u6210

\u9636\u6bb5 3: HTTP \u6838\u5fc3 (src/http)
  \u251c\u2500\u2500 \u8bf7\u6c42\u89e3\u6790 (\u72b6\u6001\u673a)
  \u251c\u2500\u2500 \u9636\u6bb5\u5904\u7406\u5668\u94fe (rewrite \u2192 access \u2192 content)
  \u251c\u2500\u2500 \u8fc7\u6ee4\u5668\u94fe (header filter \u2192 body filter)
  \u251c\u2500\u2500 Upstream \u4ee3\u7406
  \u2514\u2500\u2500 \u53d8\u91cf\u7cfb\u7edf

\u9636\u6bb5 4: HTTP \u6269\u5c55\u6a21\u5757 (src/http/modules)
  \u251c\u2500\u2500 \u9759\u6001\u6587\u4ef6\u670d\u52a1
  \u251c\u2500\u2500 \u53cd\u5411\u4ee3\u7406
  \u251c\u2500\u2500 FastCGI/uWSGI/SCGI
  \u251c\u2500\u2500 Gzip \u538b\u7f29
  \u251c\u2500\u2500 \u91cd\u5199\u4e0e\u91cd\u5b9a\u5411
  \u2514\u2500\u2500 \u8bbf\u95ee\u63a7\u5236

\u9636\u6bb5 5: \u9ad8\u7ea7\u534f\u8bae
  \u251c\u2500\u2500 HTTP/2 (src/http/v2) \u2014 HPACK, \u5e27, \u6d41\u63a7
  \u251c\u2500\u2500 HTTP/3 + QUIC (src/http/v3, src/event/quic)
  \u251c\u2500\u2500 Mail \u4ee3\u7406 (src/mail)
  \u2514\u2500\u2500 Stream TCP/UDP \u4ee3\u7406 (src/stream)

\u9636\u6bb5 6: \u5e73\u53f0\u5c42 (src/os)
  \u251c\u2500\u2500 Unix: \u8fdb\u7a0b\u7ba1\u7406, \u5171\u4eab\u5185\u5b58, \u4fe1\u53f7
  \u2514\u2500\u2500 Windows: IOCP, \u670d\u52a1\u7ba1\u7406
```

### 3.2 \u5173\u952e\u6280\u672f\u51b3\u7b56

| \u51b3\u7b56\u70b9 | \u9009\u62e9 | \u539f\u56e0 |
|--------|------|------|
| \u5e76\u53d1\u6a21\u578b | \u591a\u8fdb\u7a0b + \u5355\u7ebf\u7a0b\u4e8b\u4ef6\u5faa\u73af | \u907f\u514d\u9501\u7ade\u4e89\uff0c\u5229\u7528\u591a\u6838 |
| \u5185\u5b58\u7ba1\u7406 | \u5bf9\u8c61\u6c60 (ngx_pool_t) | O(1) \u5206\u914d\uff0c\u8bf7\u6c42\u7ed3\u675f\u6574\u4f53\u91ca\u653e |
| I/O \u6a21\u578b | \u5168\u975e\u963b\u585e + \u72b6\u6001\u673a | \u9ad8\u5e76\u53d1\u4e0b\u4e0d\u963b\u585e |
| \u6a21\u5757\u63a5\u53e3 | \u56de\u8c03\u51fd\u6570\u6307\u9488 + \u914d\u7f6e\u4e0a\u4e0b\u6587 | \u7f16\u8bd1\u65f6/\u8fd0\u884c\u65f6\u53ef\u6269\u5c55 |
| \u9519\u8bef\u4f20\u9012 | \u72b6\u6001\u7801 (NGX_OK/ERROR/AGAIN) | \u7edf\u4e00\u5f02\u6b65\u64cd\u4f5c\u7ed3\u679c |

### 3.3 \u5fc5\u987b\u6ce8\u610f\u7684\u5751

1. **\u4fe1\u53f7\u5b89\u5168**: \u4fe1\u53f7\u5904\u7406\u51fd\u6570\u4e2d\u4e0d\u80fd\u8c03\u7528 malloc/free\uff0c\u5fc5\u987b\u7528\u539f\u5b50\u64cd\u4f5c\u6216\u4e13\u7528\u961f\u5217
2. **\u5185\u5b58\u6cc4\u6f0f**: \u4e8b\u4ef6\u5faa\u73af\u4e2d\u7684\u4e34\u65f6\u5bf9\u8c61\u5fc5\u987b\u6ce8\u518c pool_cleanup_t \u6e05\u7406\u51fd\u6570
3. **\u534f\u8bae\u8fb9\u754c**: QUIC/HTTP2 \u89e3\u6790\u65f6\u52a1\u5fc5\u68c0\u67e5\u7f13\u51b2\u533a\u957f\u5ea6\uff0c\u9632\u6b62\u8d8a\u754c\u8bfb
4. **\u5171\u4eab\u5185\u5b58**: Worker \u95f4\u901a\u4fe1\u9700\u8981 ngx_slab_pool \u7ba1\u7406\uff0c\u907f\u514d\u788e\u7247\u5316
5. **\u914d\u7f6e\u91cd\u8f7d**: ngx_init_cycle \u5fc5\u987b\u539f\u5b50\u5207\u6362\uff0c\u65e7 cycle \u5ef6\u8fdf\u5230\u6240\u6709\u8bf7\u6c42\u5b8c\u6210\u540e\u9500\u6bc1

### 3.4 \u8bbe\u8ba1\u6a21\u5f0f\u53c2\u8003

- **\u8d23\u4efb\u94fe (Chain of Responsibility)**: HTTP \u9636\u6bb5\u5904\u7406 (preaccess \u2192 access \u2192 content)
- **\u8fc7\u6ee4\u5668\u94fe (Filter Chain)**: \u54cd\u5e94\u6d41\u5904\u7406 (header filter \u2192 body filter)
- **\u72b6\u6001\u673a (State Machine)**: \u534f\u8bae\u89e3\u6790\u3001\u8fde\u63a5\u751f\u547d\u5468\u671f
- **\u7b56\u7565\u6a21\u5f0f (Strategy)**: \u4e8b\u4ef6\u9a71\u52a8\u62bd\u8c61 (epoll vs kqueue vs IOCP)
- **\u5bf9\u8c61\u6c60 (Object Pool)**: \u5185\u5b58\u5206\u914d (ngx_pool_t)
- **\u89c2\u5bdf\u8005\u6a21\u5f0f (Observer)**: \u5171\u4eab\u5185\u5b58 zone \u7684 init/reinit \u56de\u8c03

---
""")

parts.append(
    "*Generated by repo-analyzer | LLM: qwen/qwen3.5-35b-a3b | Date: 2026-05-14*\n"
)

# Write
final = "\n".join(parts)
output_path.write_text(final, encoding="utf-8")

print(f"Final document: {output_path}")
print(f"Size: {len(final):,} chars ({len(final)/1024:.1f} KB)")
print(f"Lines: {final.count(chr(10)):,}")
