"""Enhanced call graph: C function pointer / callback pattern detection.

In C projects like nginx, a huge portion of the control flow goes through
function pointers stored in structs (e.g., ngx_http_module_t, ngx_event_t).
Tree-sitter only captures direct calls — this module fills the gap.

Patterns detected:
1. Struct with function pointer fields → "dispatch table" identification
2. Assignments to function pointer fields → callback registration
3. Calls through function pointer fields → indirect call resolution
4. Java interface/abstract class → virtual dispatch tracking
"""

import re
from dataclasses import dataclass, field


@dataclass
class FuncPointerField:
    """A function pointer field in a C struct."""
    struct_name: str
    field_name: str
    return_type: str
    param_types: list[str]
    file: str
    line: int


@dataclass
class CallbackRegistration:
    """An assignment to a function pointer field."""
    struct_var: str       # variable name or expression
    field_name: str
    assigned_func: str    # the function being assigned
    file: str
    line: int
    # Inferred context: what struct type this likely is
    inferred_type: str = ""


@dataclass
class IndirectCall:
    """A call through a function pointer field."""
    expression: str       # e.g., "c->read->handler"
    field_name: str
    caller: str
    file: str
    line: int


@dataclass
class DispatchTable:
    """A struct type that serves as a dispatch table (vtable-like pattern)."""
    struct_name: str
    fields: list[FuncPointerField] = field(default_factory=list)
    registrations: list[CallbackRegistration] = field(default_factory=list)


# ── C function pointer detection ─────────────────────────────────────────────

# Pattern: type (*field_name)(params);
_C_FP_FIELD_RE = re.compile(
    r'(\w[\w\s\*]*?)\s*\(\s*\*\s*(\w+)\s*\)\s*\(([^)]*)\)\s*;'
)

# Pattern: struct_var->field = func_name;  or  struct_var.field = func_name;
_C_ASSIGN_FP_RE = re.compile(
    r'(\w+(?:->|\.)\w+)\s*=\s*(&?\s*\w+)\s*;'
)

# Pattern: struct_var->field(args)  or  (*struct_var->field)(args)
_C_CALL_FP_RE = re.compile(
    r'(?:\(\s*\*\s*)?(\w+(?:->|\.)+[\w>]+)(?:\s*\)?)\s*\('
)

# Pattern: typedef struct { ... } name;
_C_STRUCT_TYPEDEF_RE = re.compile(
    r'typedef\s+struct\s*(?:\w+)?\s*\{([^}]+)\}\s*(\w+)\s*;'
)

# Pattern: struct name { ... };
_C_STRUCT_RE = re.compile(
    r'struct\s+(\w+)\s*\{([^}]+)\}'
)


def extract_c_func_pointers(source: str, filepath: str) -> list[FuncPointerField]:
    """Extract function pointer fields from C struct definitions."""
    results = []
    
    # Find all struct/typedef struct blocks
    for m in _C_STRUCT_TYPEDEF_RE.finditer(source):
        body = m.group(1)
        struct_name = m.group(2)
        base_line = source[:m.start()].count('\n') + 1
        
        for fm in _C_FP_FIELD_RE.finditer(body):
            ret_type = fm.group(1).strip()
            field_name = fm.group(2).strip()
            params_raw = fm.group(3).strip()
            param_types = [p.strip().split()[-1] for p in params_raw.split(',') if p.strip()]
            line = base_line + body[:fm.start()].count('\n')
            results.append(FuncPointerField(
                struct_name=struct_name,
                field_name=field_name,
                return_type=ret_type,
                param_types=param_types,
                file=filepath,
                line=line,
            ))
    
    for m in _C_STRUCT_RE.finditer(source):
        body = m.group(2)
        struct_name = m.group(1)
        base_line = source[:m.start()].count('\n') + 1
        
        for fm in _C_FP_FIELD_RE.finditer(body):
            ret_type = fm.group(1).strip()
            field_name = fm.group(2).strip()
            params_raw = fm.group(3).strip()
            param_types = [p.strip().split()[-1] for p in params_raw.split(',') if p.strip()]
            line = base_line + body[:fm.start()].count('\n')
            results.append(FuncPointerField(
                struct_name=struct_name,
                field_name=field_name,
                return_type=ret_type,
                param_types=param_types,
                file=filepath,
                line=line,
            ))
    
    return results


def extract_callback_registrations(source: str, filepath: str) -> list[CallbackRegistration]:
    """Find assignments like: module->postconfiguration = ngx_http_module_postconfiguration;"""
    results = []
    
    for m in _C_ASSIGN_FP_RE.finditer(source):
        expr = m.group(1)
        func = m.group(2).strip().lstrip('&').strip()
        line = source[:m.start()].count('\n') + 1
        
        # Split into var->field or var.field
        if '->' in expr:
            parts = expr.split('->', 1)
            sep = '->'
        elif '.' in expr:
            parts = expr.split('.', 1)
            sep = '.'
        else:
            continue
        
        var_name = parts[0]
        field_name = parts[1]
        
        # Only track if assigned value looks like a function name (not a literal)
        if func and not func.startswith('"') and not func.isdigit() and func != 'NULL':
            results.append(CallbackRegistration(
                struct_var=var_name,
                field_name=field_name,
                assigned_func=func,
                file=filepath,
                line=line,
            ))
    
    return results


def extract_indirect_calls(source: str, filepath: str) -> list[IndirectCall]:
    """Find calls like: c->read->handler(ev) or (*module->init)(cf)."""
    results = []
    
    for m in _C_CALL_FP_RE.finditer(source):
        expr = m.group(1)
        line = source[:m.start()].count('\n') + 1
        
        # Check if this looks like a function pointer call
        # (contains -> or . and the last part is likely a field name)
        if '->' in expr or '.' in expr:
            # Extract the field name
            parts = expr.replace('->', '.').split('.')
            field_name = parts[-1]
            
            # Heuristic: common function pointer field names
            fp_indicators = {
                'handler', 'callback', 'init', 'exit', 'create', 'destroy',
                'read', 'write', 'connect', 'accept', 'close', 'process',
                'preconfiguration', 'postconfiguration', 'init_main_conf',
                'init_server_conf', 'init_location_conf', 'merge',
                'content_handler', 'filter', 'checker', 'resolver',
                'alloc', 'free', 'copy', 'compare', 'hash',
                'send', 'recv', 'input_filter', 'output_filter',
            }
            
            if field_name in fp_indicators or field_name.endswith('_handler') \
                    or field_name.endswith('_cb') or field_name.endswith('_func'):
                # Determine caller context (approximate)
                caller = "<unknown>"
                # Try to find enclosing function by looking backward for a function def
                
                results.append(IndirectCall(
                    expression=expr,
                    field_name=field_name,
                    caller=caller,
                    file=filepath,
                    line=line,
                ))
    
    return results


def build_dispatch_tables(
    func_ptrs: list[FuncPointerField],
    registrations: list[CallbackRegistration],
) -> list[DispatchTable]:
    """Group function pointer fields into dispatch tables (vtable-like structs)."""
    tables: dict[str, DispatchTable] = {}
    
    for fp in func_ptrs:
        if fp.struct_name not in tables:
            tables[fp.struct_name] = DispatchTable(struct_name=fp.struct_name)
        tables[fp.struct_name].fields.append(fp)
    
    # Match registrations to tables by field name
    for reg in registrations:
        for tname, table in tables.items():
            for fp in table.fields:
                if fp.field_name == reg.field_name:
                    reg.inferred_type = tname
                    table.registrations.append(reg)
                    break
    
    return list(tables.values())


# ── Java virtual dispatch ────────────────────────────────────────────────────

def extract_java_virtual_dispatch(
    symbols: list[dict],
) -> list[dict]:
    """For Java: identify interface/abstract class → implementation relationships."""
    # Group symbols by kind
    interfaces = [s for s in symbols if s.get('kind') == 'interface']
    classes = [s for s in symbols if s.get('kind') == 'class']
    
    dispatches = []
    
    # Find classes that implement interfaces (from signature)
    for cls in classes:
        sig = cls.get('signature', '')
        if 'implements' in sig:
            parts = sig.split('implements')
            if len(parts) > 1:
                iface_names = [n.strip() for n in parts[1].split(',')]
                for iface in iface_names:
                    dispatches.append({
                        'type': 'implements',
                        'class': cls['name'],
                        'interface': iface,
                        'file': cls['file'],
                        'line': cls['line'],
                    })
        if 'extends' in sig:
            parts = sig.split('extends')
            if len(parts) > 1:
                parent = parts[1].split('implements')[0].strip().split(',')[0].strip()
                if parent:
                    dispatches.append({
                        'type': 'extends',
                        'class': cls['name'],
                        'parent': parent,
                        'file': cls['file'],
                        'line': cls['line'],
                    })
    
    return dispatches


# ── Main entry point ─────────────────────────────────────────────────────────

def enhance_call_graph(
    files_analysis: list[dict],
    repo_root: str,
) -> dict:
    """Enhance the call graph with indirect call information.

    Returns a dict with:
    - func_pointer_fields: list of function pointer struct fields
    - callback_registrations: list of assignments to function pointers
    - indirect_calls: list of calls through function pointers
    - dispatch_tables: grouped function pointer structs
    - java_dispatch: Java virtual dispatch relationships
    - enhanced_call_edges: additional call edges (source -> target)
    """
    import os
    
    all_func_ptrs = []
    all_registrations = []
    all_indirect_calls = []
    all_java_dispatch = []
    
    for fa in files_analysis:
        fpath = os.path.join(repo_root, fa['path'])
        lang = fa.get('language', '')
        
        if lang == 'C':
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    source = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            
            fps = extract_c_func_pointers(source, fa['path'])
            regs = extract_callback_registrations(source, fa['path'])
            ics = extract_indirect_calls(source, fa['path'])
            
            all_func_ptrs.extend([{
                'struct': fp.struct_name,
                'field': fp.field_name,
                'return_type': fp.return_type,
                'file': fp.file,
                'line': fp.line,
            } for fp in fps])
            
            all_registrations.extend([{
                'var': r.struct_var,
                'field': r.field_name,
                'func': r.assigned_func,
                'file': r.file,
                'line': r.line,
                'inferred_type': r.inferred_type,
            } for r in regs])
            
            all_indirect_calls.extend([{
                'expression': ic.expression,
                'field': ic.field_name,
                'file': ic.file,
                'line': ic.line,
            } for ic in ics])
        
        elif lang == 'Java':
            symbols = fa.get('symbols', [])
            dispatches = extract_java_virtual_dispatch(symbols)
            all_java_dispatch.extend(dispatches)
    
    # Build dispatch tables
    from dataclasses import asdict
    fp_objs = []
    for fp in all_func_ptrs:
        fp_objs.append(FuncPointerField(
            struct_name=fp.get('struct', fp.get('struct_name', '')),
            field_name=fp.get('field', fp.get('field_name', '')),
            return_type=fp.get('return_type', ''),
            param_types=[],
            file=fp.get('file', ''),
            line=fp.get('line', 0),
        ))
    reg_objs = []
    for r in all_registrations:
        reg_objs.append(CallbackRegistration(
            struct_var=r.get('var', r.get('struct_var', '')),
            field_name=r.get('field', r.get('field_name', '')),
            assigned_func=r.get('func', r.get('assigned_func', '')),
            file=r.get('file', ''),
            line=r.get('line', 0),
            inferred_type=r.get('inferred_type', ''),
        ))
    tables = build_dispatch_tables(fp_objs, reg_objs)
    
    # Build enhanced call edges: for each indirect call, find matching registrations
    enhanced_edges = []
    for ic in all_indirect_calls:
        field = ic['field']
        matching_regs = [r for r in all_registrations if r['field'] == field]
        for reg in matching_regs:
            enhanced_edges.append({
                'caller': ic['expression'],
                'callee': reg['func'],
                'type': 'indirect',
                'field': field,
                'file': ic['file'],
                'line': ic['line'],
            })
    
    return {
        'func_pointer_fields': all_func_ptrs,
        'callback_registrations': all_registrations,
        'indirect_calls': all_indirect_calls,
        'dispatch_tables': [{
            'struct': t.struct_name,
            'fields': [{'name': f.field_name, 'type': f.return_type} for f in t.fields],
            'registered_callbacks': [{'field': r.field_name, 'func': r.assigned_func} 
                                     for r in t.registrations],
        } for t in tables if len(t.fields) >= 2],  # Only tables with 2+ function pointers
        'java_dispatch': all_java_dispatch,
        'enhanced_call_edges': enhanced_edges,
        'summary': {
            'func_pointer_fields': len(all_func_ptrs),
            'callback_registrations': len(all_registrations),
            'indirect_calls': len(all_indirect_calls),
            'dispatch_tables': len([t for t in tables if len(t.fields) >= 2]),
            'enhanced_edges': len(enhanced_edges),
        },
    }
