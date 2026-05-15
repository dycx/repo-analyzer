# Mermaid Syntax Reference (for LLM code generation)

> This document defines the **exact** Mermaid syntax rules that must be followed
> when generating diagrams. Violations cause rendering failures.

---

## 1. Flowchart (flowchart TD / LR)

### 1.1 Node shapes

| Syntax | Shape | Use case |
|--------|-------|----------|
| `A["text"]` | Rectangle | Default action/process node |
| `A{"text"}` | Diamond (rhombus) | Decision/condition — **exactly 2 outgoing edges** |
| `A(("text"))` | Circle | Start/End terminal |
| `A[["text"]]` | Subroutine | Function call |
| `A>"text"]` | Flag/asymmetric | Event/trigger |
| `A("text (info)")` | Stadium (rounded) | ⚠️ Only when parentheses are inside quotes |

### 1.2 Quoting rules (CRITICAL)

- **Any label containing `(`, `)`, `{`, `}`, `[`, `]`, `|`, `#`, `>`, `<`, `=` MUST be quoted**
- Quoted labels use double quotes: `A["label with (parens)"]`
- Inside quotes, parentheses are literal and safe
- ❌ `A[label (info)]` → broken (unquoted parens create stadium shape)
- ✅ `A["label info"]` — remove parens, or `A["label (info)"]` — quote the whole thing

### 1.3 Assignment / comparison in labels

- ❌ `A{"xxx = \"true\""}` — nested escaped quotes break parsing
- ❌ `A{xxx = "true"}` — unquoted label with `=` and quotes
- ✅ `A{"xxx is true"}` — rephrase to avoid `=` in labels
- ✅ `A{"xxx == true"}` — use `==` instead of `=` (safer in most renderers)
- ✅ `A["set xxx to true"]` — rephrase assignment as action
- **Rule: Avoid `=` inside diamond/node labels. Rephrase as natural language.**

### 1.4 Edge labels

- `A -->|label| B` — basic edge with label
- ❌ `A -->|label (info)| B` — unquoted parens in edge label break parsing
- ✅ `A -->|"label info"| B` — quote the edge label
- ✅ `A -->|label| B` — if no special chars, no quotes needed
- **Rule: If edge label contains any special character, wrap in quotes: `-->|"label"|`**

### 1.5 Subgraph

```
subgraph id ["Display Title"]
    A --> B
end
```

- ❌ `subgraph "Title"` — missing ID
- ✅ `subgraph myid ["Title"]` — has ID and quoted title
- Every `subgraph` MUST have a matching `end`

### 1.6 Links / URLs in nodes

- ❌ `A["visit https://example.com"]` — URL with `//` breaks
- ✅ `A["visit example.com"]` — remove protocol
- Or use click: `A["label"]` then `click A href "https://example.com"`

---

## 2. Sequence Diagram (sequenceDiagram)

### 2.1 Participants

```
sequenceDiagram
    participant A as "ModuleA"
    participant B as "ModuleB"
```

- Use `as "Friendly Name"` for all participants
- Keep participant count ≤ 6 (more = unreadable)
- **Group related modules** — don't list every single function as a participant

### 2.2 Messages

```
A->>B: function_name(args)
B-->>A: return_value
```

- `->>` = solid arrow (sync call)
- `-->>` = dashed arrow (return/response)
- `-x` = solid arrow, cross at end (failed)
- `--x` = dashed arrow, cross at end

**Message label rules:**
- ❌ `A->>B: func(param="value")` — quotes inside message break parsing
- ✅ `A->>B: func(param=value)` — remove inner quotes
- ✅ `A->>B: func with param value` — rephrase
- **Rule: No double quotes inside message labels. Remove or rephrase.**

### 2.3 Blocks (CRITICAL — every opening needs closing)

```
alt success path
    A->>B: request
    B-->>A: response
else error path
    A->>B: request
    B-->>A: error
end
```

**Block types:**
- `alt` / `else` / `end` — conditional
- `opt` / `end` — optional
- `loop` / `end` — loop
- `break` / `end` — break (⚠️ **MUST have matching `end`**)
- `par` / `and` / `end` — parallel

**Rule: Every `alt`, `opt`, `loop`, `break`, `par` MUST have a matching `end`.**
**Rule: `break` block MUST contain at least one message before `end`.**

### 2.4 Notes

```
Note right of B: does something
Note left of A: caller info
Note over A,B: shared context
```

- Use notes sparingly — they add clutter
- Prefer concise message labels over notes

### 2.5 Simplification rules for code analysis

**Problem:** Sequence diagrams with 20+ messages are unreadable.
**Solution:**

1. **Max 15 messages per diagram** — if more, split into sub-diagrams
2. **Max 6 participants** — merge related functions into module-level participants
3. **Show the "what", not every "how"**:
   - ❌ 8 separate messages for: parse header → validate → check cache → ...
   - ✅ 1 message: `Client->>HTTP: process_request(req)`
4. **Group internal steps into notes** instead of separate messages:
   ```
   Client->>HTTP: process_request(req)
   Note right of HTTP: parse headers, validate, check cache
   HTTP->>Upstream: forward(backend_req)
   ```
5. **Only show cross-module boundaries** — intra-module calls are for flowcharts, not sequence diagrams
6. **Collapse callback chains**: instead of showing every callback registration step, show the dispatch:
   ```
   Event->>Handler: via ngx_event_actions_t.process_event
   ```
7. **Use `loop`/`opt`/`alt` blocks for control flow**, not linear expansion

---

## 3. Common Mistakes (LLM output patterns that break rendering)

| Bad pattern | Fix |
|-------------|-----|
| `A[step (detail)]` | `A["step detail"]` or `A["step (detail)"]` |
| `A{value = "x"}` | `A{"value is x"}` |
| `break` without `end` | Add matching `end` |
| `subgraph "Title"` | `subgraph id ["Title"]` |
| `A->>B: func(a="b")` | `A->>B: func(a=b)` |
| 25+ messages in sequence diagram | Limit to 15, group into modules |
| 8 participants in sequence diagram | Limit to 6, merge related |
| Every internal function call as message | Show only cross-module calls |
| Nested quotes: `A["say \"hello\""]` | `A["say hello"]` — remove inner quotes |
| `=` in diamond label | Rephrase: `{"status is active"}` not `{"status = active"}` |
