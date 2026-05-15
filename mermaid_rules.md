# Mermaid Syntax Reference (for LLM code generation)

> Source: https://mermaid.js.org/syntax/flowchart.html, https://mermaid.js.org/syntax/sequenceDiagram.html
> Last updated: 2026-05-15
>
> This document defines the **exact** Mermaid syntax rules that MUST be followed
> when generating diagrams. Violations cause rendering failures.

---

## 1. Flowchart (flowchart TD / LR)

### 1.1 Declaration

```
flowchart TD      (or TB — same direction, top-to-bottom)
flowchart LR
flowchart RL
flowchart BT
```

`flowchart` and `graph` are interchangeable.

### 1.2 Node shapes (classic)

| Shape | Syntax | Example |
|-------|--------|---------|
| Rectangle (default) | `id[text]` | `A[Process]` |
| Round edges | `id(text)` | `A(Round)` |
| Stadium | `id([text])` | `A([Terminal])` |
| Subroutine | `id[[text]]` | `A[[Subroutine]]` |
| Cylinder (DB) | `id[(text)]` | `A[(Database)]` |
| Circle | `id((text))` | `A((Start))` |
| Asymmetric | `id>text]` | `A>Event]` |
| Rhombus (diamond) | `id{text}` | `A{Decision?}` |
| Hexagon | `id{{text}}` | `A{{Prepare}}` |
| Parallelogram | `id[/text/]` | `A[/Input/]` |
| Parallelogram alt | `id[\text\]` | `A[\Output\]` |
| Trapezoid | `id[/text\]` | `A[/Top\]` |
| Trapezoid alt | `id[\text/]` | `A[\Bottom/]` |
| Double circle | `id(((text)))` | `A(((End)))` |

### 1.3 Quoting rules (CRITICAL)

**When to quote labels:**
- Labels containing `(` `)` `[` `]` `{` `}` `<` `>` `/` `\` `#` `&` `=` MUST be quoted
- Unicode text must be quoted
- Syntax: `id["text with (special) chars"]`

**Entity code escaping (inside quotes):**
- `#quot;` → `"`
- `#35;` → `#`
- `#59;` → `;`
- `#amp;` → `&`
- `#lt;` → `<`
- `#gt;` → `>`
- `#9829;` → `♥` (decimal code point)

**Markdown in labels:**
```
A["`text with **bold** and _italic_`"]
```
Must use BOTH double quotes AND backticks.

### 1.4 Assignment / comparison in labels

- ❌ `A{"xxx = "true""}` — nested quotes break parsing
- ❌ `A{xxx = "true"}` — unquoted label with `=` and quotes
- ✅ `A{"xxx is true"}` — rephrase to avoid `=`
- ✅ `A{"xxx == true"}` — use `==` instead of `=`
- ✅ `A["set xxx to true"]` — rephrase assignment as action
- **Rule: NEVER use `=` inside node/diamond labels. Rephrase as natural language.**

### 1.5 Edge types

| Type | Syntax |
|------|--------|
| Directed arrow | `A --> B` |
| Undirected | `A --- B` |
| Dotted arrow | `A -.-> B` |
| Dotted undirected | `A -.- B` |
| Thick arrow | `A ==> B` |
| Thick undirected | `A === B` |
| Invisible | `A ~~~ B` |
| Circle end | `A --o B` |
| Cross end | `A --x B` |

**Edge labels:**
```
A -->|text| B           (pipe syntax)
A -- text -->B          (inline syntax)
A -. text .->B          (dotted with text)
A == text ==>B          (thick with text)
```

**Edge label quoting:**
- ❌ `A -->|callback (read)| B` — unquoted parens break parsing
- ✅ `A -->|"callback (read)"| B` — quote the edge label
- ✅ `A -->|no_special_chars| B` — no quotes needed if clean

**Multi-target chaining:**
```
A --> B & C --> D       (A goes to both B and C, then to D)
A & B --> C & D         (multiple sources and targets)
```

**Edge length (rank spanning):**
```
A -----> B              (more dashes = more rank distance)
```

### 1.6 Subgraph rules

```
subgraph id1 ["Display Title"]
    direction TB
    A --> B
end
```

- ❌ `subgraph "Title"` — missing ID
- ✅ `subgraph myid ["Title"]` — has ID and quoted title
- Every `subgraph` MUST have a matching `end`
- Direction inside subgraph: `direction TB` (or LR/RL/BT)
- **LIMITATION**: If ANY nodes in the subgraph are linked to nodes outside,
  the subgraph direction is IGNORED — it inherits the parent direction.

### 1.7 RESERVED WORDS (CRITICAL)

**`end` is a reserved keyword:**
- ❌ `A["end"]` or `A(end)` — BREAKS the flowchart completely
- ✅ `A["End"]` or `A["END"]` — capitalize at least one letter
- ✅ `A["eNd"]` — any capitalization other than all-lowercase "end"

**Node IDs starting with `o` or `x` after `---`:**
- ❌ `A---ops` — parsed as circle edge `A` to `ps` via `o`
- ✅ `A--- ops` (space after) or `A---Ops` (capitalize)

### 1.8 Comments

```
%% this is a comment (must be on its own line)
```

### 1.9 Styling

```
style nodeId fill:#f9f,stroke:#333,stroke-width:4px
classDef className fill:#f9f,stroke:#333,stroke-width:4px;
class nodeId1,nodeId2 className;
A:::className --> B
linkStyle 3 stroke:#ff3,stroke-width:4px;
```

---

## 2. Sequence Diagram (sequenceDiagram)

### 2.1 Declaration

```
sequenceDiagram
```

Must be the first line.

### 2.2 Participants

```
participant Alice                    (implicit)
participant A as "Friendly Name"     (with alias)
actor Bob                            (stick figure)
```

**Typed participants (v11+):**
```
participant A@{ "type": "boundary" }    (or control, entity, database, collections, queue)
```

- Participant order in source = rendered order
- IDs are case-sensitive
- Aliases with `as` take precedence

### 2.3 Messages

**Syntax:** `[Sender][Arrow][Receiver]: Message text`

| Arrow | Meaning |
|-------|---------|
| `->>` | Solid line with arrowhead (sync call) — **most common** |
| `-->>` | Dotted line with arrowhead (return) — **most common** |
| `->` | Solid line without arrowhead |
| `-->` | Dotted line without arrowhead |
| `-x` | Solid line with cross (failed) |
| `--x` | Dotted line with cross (failed) |
| `-)` | Solid line with open arrow (async) |
| `--)` | Dotted line with open arrow (async) |
| `<<->>` | Solid bidirectional (v11+) |
| `<<-->>` | Dotted bidirectional (v11+) |

**Message text rules:**
- ❌ `A->>B: func(a="value")` — inner quotes break parsing
- ✅ `A->>B: func(a=value)` — remove inner quotes
- ✅ `A->>B: func with value` — rephrase
- **Rule: NEVER use double quotes inside message labels. Use entity code `#quot;` if absolutely needed.**
- **Semicolons in messages**: `;` can act as line break. Escape with `#59;`
- **Line breaks**: use `<br/>` in messages and notes

### 2.4 Activations

```
activate John                       (explicit activate)
deactivate John                     (explicit deactivate)
Alice->>+John: Hello               (shortcut: activate on receive)
John-->>-Alice: Thanks             (shortcut: deactivate on send)
```

Activations can be stacked on the same actor.

### 2.5 Notes

```
Note right of John: text
Note left of Alice: text
Note over Alice,John: text spanning two participants
```

### 2.6 Block structures (ALL must have matching `end`)

**alt / else / end** (if/else):
```
alt success condition
    A->>B: request
else error condition
    A->>B: error handling
end
```

**opt / end** (if without else):
```
opt optional condition
    A->>B: do something
end
```

**loop / end** (repetition):
```
loop every 5 seconds
    A->>B: heartbeat
end
```

**break / end** (break out of enclosing block):
```
break error occurred
    A->>B: abort
end
```
⚠️ `break` MUST have a matching `end` and MUST contain at least one message.

**par / and / end** (parallel):
```
par action 1
    A->>B: do X
and action 2
    A->>C: do Y
end
```

**critical / option / end** (must-succeed with alternatives):
```
critical must succeed
    A->>B: critical operation
option alternative A
    A->>B: fallback 1
option alternative B
    A->>B: fallback 2
end
```
Can have zero `option` blocks.

**rect / end** (background highlighting):
```
rect rgb(200, 255, 200)
    A->>B: highlighted section
end
```

**NESTING**: All block types CAN be nested inside each other:
```
alt outer condition
    loop every second
        A->>B: poll
        opt has result
            B-->>A: data
        end
    end
else error
    break fatal
        A->>B: abort
    end
end
```

### 2.7 Grouping / Box (v11+)

```
box Purple Alice & John
    participant A
    participant J
end
box transparent Aqua
```

### 2.8 Autonumbering

```
autonumber                     (enable, starts at 1)
autonumber 10 5                (start at 10, increment by 5)
```

### 2.9 Comments

```
%% this is a comment (own line only)
```

### 2.10 Common failure patterns

| Bad pattern | Fix |
|-------------|-----|
| `break` without `end` | Add matching `end` |
| `alt` without `end` | Add matching `end` |
| `loop` without `end` | Add matching `end` |
| `opt` without `end` | Add matching `end` |
| `par` without `end` | Add matching `end` |
| `critical` without `end` | Add matching `end` |
| `rect` without `end` | Add matching `end` |
| `option` outside `critical...end` | Move inside critical block |
| `and` outside `par...end` | Move inside par block |
| `else` without `alt...end` | Move inside alt block |
| `A->>B: func(a="b")` | Remove inner quotes |
| `;` in message text | Escape: `#59;` |
| "end" as node label | Capitalize: "End" |

---

## 3. Diagram Size Optimization

Large diagrams are unreadable. Apply these rules to keep diagrams compact.

### 3.1 Flowchart size control

- **Node count**: ≤ 12 per diagram
- **If > 12 nodes**: split into 2-3 sub-diagrams, each covering one sub-phase
- **Direction**: use `flowchart LR` (left-right) to save vertical space
- **Label length**: ≤ 15 characters per node label
- **Merge linear chains**: if A→B→C with no branches, merge to A["B then C"]
- **Omit trivial paths**: don't show every simple straight-through path

### 3.2 Sequence diagram size control

- **Participants**: ≤ 5 (module-level, not function-level)
- **Messages**: ≤ 10 (merge aggressively)
- **Label length**: ≤ 20 characters, remove parameter details
- **Show only cross-module calls**: intra-module calls belong in flowcharts

### 3.3 Collapsible diagrams

Wrap every mermaid block in HTML `<details>` tags:

```
<details>
<summary>Flowchart: HTTP Request Handling (8 edges)</summary>

```mermaid
flowchart LR
    ...
```

</details>
```

This lets readers expand only the diagrams they need.

---

## 4. Rules for LLM Code Generation (consolidated)

### 4.1 Flowchart generation rules

1. **Labels with special chars MUST be quoted**: `A["text (info)"]`
2. **NEVER use `=` in labels**: rephrase as natural language
3. **Diamond nodes**: exactly 2 outgoing edges, label as question
4. **subgraph**: must have ID, quoted title, and matching `end`
5. **Edge labels with special chars**: wrap in `|"label"|`
6. **NEVER use "end" as a label** (reserved keyword)
7. **NEVER use nested quotes**: remove inner quotes
8. **No URLs with protocol**: remove `https://`
9. **Entity codes for special chars**: `#quot;` `#amp;` `#lt;` `#gt;` `#59;`

### 4.2 Sequence diagram generation rules

1. **participants ≤ 6** — use module-level names, merge related functions
2. **messages ≤ 15** — merge internal steps into Notes
3. **Only cross-module calls** — intra-module calls belong in flowcharts
4. **NEVER use quotes inside messages**: `func(a=value)` not `func(a="value")`
5. **Every block opening MUST have matching `end`**
6. **break block MUST contain ≥ 1 message**
7. **Callback chains simplified**: `Event->>Handler: via dispatch_table`
8. **Use `as` alias for all participants**: `participant A as "Module Name"`
9. **Use `<br/>` for line breaks** in messages/notes
10. **Escape semicolons**: `#59;`
