"""Spark-specific analysis for repo-analyzer.

Provides:
- Spark built-in function recognition (300+ functions from Spark SQL)
- UDF detection from Scala/Java source code
- SQL function call extraction
- Cross-reference between XML configs and Scala/Java loader code
"""

import re
from dataclasses import dataclass, field

# ── Spark Built-in Functions (Spark 3.x) ───────────────────────────────────
# Organized by category for analysis output

SPARK_AGGREGATE_FUNCTIONS = {
    "avg", "count", "count_if", "first", "first_value", "last", "last_value",
    "max", "min", "sum", "sum_distinct", "collect_list", "collect_set",
    "approx_count_distinct", "approx_percentile", "percentile",
    "percentile_approx", "median", "mode", "stddev", "stddev_pop",
    "stddev_samp", "variance", "var_pop", "var_samp", "corr", "covar_pop",
    "covar_samp", "regr_avgx", "regr_avgy", "regr_count", "regr_intercept",
    "regr_r2", "regr_slope", "regr_sxx", "regr_sxy", "regr_syy",
    "grouping", "grouping_id", "kurtosis", "skewness",
}

SPARK_WINDOW_FUNCTIONS = {
    "row_number", "rank", "dense_rank", "percent_rank", "ntile",
    "cume_dist", "lead", "lag", "nth_value", "first_value", "last_value",
}

SPARK_STRING_FUNCTIONS = {
    "ascii", "base64", "bit_length", "char", "char_length", "character_length",
    "concat", "concat_ws", "contains", "decode", "elt", "encode", "endswith",
    "field", "find_in_set", "format_number", "format_string", "initcap",
    "instr", "lcase", "left", "length", "levenshtein", "locate", "lower",
    "lpad", "ltrim", "mask", "octet_length", "overlay", "position",
    "printf", "regexp_count", "regexp_extract", "regexp_extract_all",
    "regexp_instr", "regexp_like", "regexp_replace", "repeat", "replace",
    "reverse", "right", "rpad", "rtrim", "sentences", "soundex", "space",
    "split", "startswith", "substr", "substring", "substring_index",
    "translate", "trim", "ucase", "unbase64", "upper",
}

SPARK_MATH_FUNCTIONS = {
    "abs", "acos", "acosh", "asin", "asinh", "atan", "atan2", "atanh",
    "bround", "cbrt", "ceil", "ceiling", "conv", "cos", "cosh", "cot",
    "csc", "degrees", "e", "exp", "expm1", "factorial", "floor", "greatest",
    "hex", "hypot", "least", "ln", "log", "log10", "log1p", "log2",
    "mod", "negative", "pi", "pmod", "positive", "pow", "power", "radians",
    "rand", "randn", "rint", "round", "sec", "shiftleft", "shiftright",
    "shiftrightunsigned", "sign", "signum", "sin", "sinh", "sqrt",
    "tan", "tanh", "try_add", "try_divide", "try_multiply", "try_subtract",
    "unhex", "width_bucket",
}

SPARK_DATETIME_FUNCTIONS = {
    "add_months", "convert_timezone", "curdate", "current_date",
    "current_timestamp", "current_timezone", "date_add", "date_format",
    "date_from_unix_date", "date_part", "date_sub", "date_trunc",
    "dateadd", "datediff", "datepart", "day", "dayofmonth", "dayofweek",
    "dayofyear", "extract", "from_unixtime", "from_utc_timestamp",
    "hour", "last_day", "localtimestamp", "make_date", "make_dt_interval",
    "make_interval", "make_timestamp", "make_ym_interval", "minute",
    "month", "months_between", "next_day", "now", "quarter", "second",
    "session_window", "timestamp_add", "timestamp_diff", "timestamp_micros",
    "timestamp_millis", "timestamp_seconds", "to_date", "to_timestamp",
    "to_unix_timestamp", "to_utc_timestamp", "trunc", "unix_date",
    "unix_micros", "unix_millis", "unix_seconds", "unix_timestamp",
    "weekday", "weekofyear", "window", "year",
}

SPARK_COLLECTION_FUNCTIONS = {
    "array", "array_append", "array_compact", "array_contains",
    "array_distinct", "array_except", "array_insert", "array_intersect",
    "array_join", "array_max", "array_min", "array_position",
    "array_prepend", "array_remove", "array_repeat", "array_sort",
    "array_union", "arrays_overlap", "arrays_zip", "cardinality",
    "concat", "element_at", "element_at", "exists", "explode",
    "explode_outer", "filter", "flatten", "forall", "from_csv",
    "get", "get_json_object", "inline", "inline_outer",
    "json_array_length", "json_object_keys", "json_tuple",
    "map_concat", "map_entries", "map_filter", "map_from_arrays",
    "map_from_entries", "map_keys", "map_values", "map_zip_with",
    "named_struct", "posexplode", "posexplode_outer", "schema_of_csv",
    "schema_of_json", "sequence", "shuffle", "size", "slice",
    "sort_array", "struct", "to_csv", "to_json", "transform",
    "transform_keys", "transform_values", "try_element_at",
    "typeof", "zip_with",
}

SPARK_CAST_FUNCTIONS = {
    "cast", "try_cast", "typeof",
}

SPARK_CONDITIONAL_FUNCTIONS = {
    "assert_true", "coalesce", "if", "ifnull", "isnan", "isnotnull",
    "isnull", "nanvl", "nullif", "nvl", "nvl2", "when",
}

SPARK_MISC_FUNCTIONS = {
    "aes_decrypt", "aes_encrypt", "bitmap_bit_position", "bitmap_bucket_number",
    "bitmap_count", "bool_and", "bool_or", "bround", "call_function",
    "catalog", "current_catalog", "current_database", "current_schema",
    "current_user", "input_file_block_length", "input_file_block_start",
    "input_file_name", "java_method", "monotonically_increasing_id",
    "raise_error", "reflect", "schema", "sha1", "sha2", "spark_partition_id",
    "stack", "try_aes_decrypt", "user", "uuid",
    "version", "hash", "xxhash64", "md5", "crc32",
}

# Complete set of all known Spark built-in functions
SPARK_BUILTIN_FUNCTIONS: set[str] = (
    SPARK_AGGREGATE_FUNCTIONS
    | SPARK_WINDOW_FUNCTIONS
    | SPARK_STRING_FUNCTIONS
    | SPARK_MATH_FUNCTIONS
    | SPARK_DATETIME_FUNCTIONS
    | SPARK_COLLECTION_FUNCTIONS
    | SPARK_CAST_FUNCTIONS
    | SPARK_CONDITIONAL_FUNCTIONS
    | SPARK_MISC_FUNCTIONS
)

# Category lookup for reporting
SPARK_FUNCTION_CATEGORIES: dict[str, set[str]] = {
    "aggregate": SPARK_AGGREGATE_FUNCTIONS,
    "window": SPARK_WINDOW_FUNCTIONS,
    "string": SPARK_STRING_FUNCTIONS,
    "math": SPARK_MATH_FUNCTIONS,
    "datetime": SPARK_DATETIME_FUNCTIONS,
    "collection": SPARK_COLLECTION_FUNCTIONS,
    "cast": SPARK_CAST_FUNCTIONS,
    "conditional": SPARK_CONDITIONAL_FUNCTIONS,
    "misc": SPARK_MISC_FUNCTIONS,
}


def categorize_function(func_name: str) -> str:
    """Return the Spark function category, or 'unknown' if not built-in."""
    name_lower = func_name.lower()
    for cat, funcs in SPARK_FUNCTION_CATEGORIES.items():
        if name_lower in funcs:
            return cat
    return "unknown"


# ── SQL Function Call Extraction ───────────────────────────────────────────

# Pattern to match function calls in SQL: func_name(...) or func_name (...)
# Handles qualified names like schema.func_name
_SQL_FUNC_PATTERN = re.compile(
    r'\b([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)?)\s*\(',
)


@dataclass
class SQLFunctionCall:
    """A function call found in a SQL statement."""
    name: str              # function name (possibly qualified)
    file: str              # source file
    line: int              # line number
    is_builtin: bool       # True if Spark built-in
    category: str          # Spark function category or "unknown"
    context: str = ""      # surrounding SQL snippet


def extract_sql_functions(sql_text: str, filepath: str, line_offset: int = 0) -> list[SQLFunctionCall]:
    """Extract function calls from a SQL string.

    Returns a list of SQLFunctionCall with classification.
    """
    calls = []
    seen = set()

    # SQL keywords that look like function calls but aren't
    SQL_KEYWORDS = {
        "select", "from", "where", "group", "by", "order", "having",
        "join", "left", "right", "inner", "outer", "full", "cross",
        "on", "and", "or", "not", "in", "between", "like", "is",
        "null", "true", "false", "case", "when", "then", "else", "end",
        "insert", "into", "values", "update", "set", "delete", "create",
        "alter", "drop", "table", "view", "index", "as", "distinct",
        "all", "union", "intersect", "except", "limit", "offset",
        "asc", "desc", "nulls", "first", "last", "with", "recursive",
        "lateral", "unnest", "window", "over", "partition", "rows",
        "range", "unbounded", "preceding", "following", "current",
        "row", "merge", "using", "matched", "then", "cache", "uncache",
        "explain", "describe", "show", "use", "add", "file", "jar",
        "refresh", "reset", "set", "msck", "repair", "load", "data",
        "overwrite", "local", "inpath", "stored", "format", "location",
        "partitioned", "clustered", "sorted", "buckets", "serde",
        "properties", "temporary", "temp", "function", "macro",
    }

    for m in _SQL_FUNC_PATTERN.finditer(sql_text):
        func_name = m.group(1)
        name_lower = func_name.lower()

        # Skip SQL keywords
        if name_lower in SQL_KEYWORDS:
            continue

        # Skip duplicates in same SQL
        key = name_lower
        if key in seen:
            continue
        seen.add(key)

        # Calculate line number
        line_num = line_offset + sql_text[:m.start()].count('\n')

        # Classify
        is_builtin = name_lower in SPARK_BUILTIN_FUNCTIONS
        category = categorize_function(func_name)

        # Get context (surrounding 100 chars)
        ctx_start = max(0, m.start() - 30)
        ctx_end = min(len(sql_text), m.end() + 70)
        context = sql_text[ctx_start:ctx_end].replace('\n', ' ').strip()

        calls.append(SQLFunctionCall(
            name=func_name,
            file=filepath,
            line=line_num,
            is_builtin=is_builtin,
            category=category,
            context=context,
        ))

    return calls


# ── UDF Detection from Scala/Java ──────────────────────────────────────────

@dataclass
class UDFDefinition:
    """A UDF definition found in Scala/Java code."""
    name: str              # UDF name (as registered)
    class_name: str        # implementing class
    file: str              # source file
    line: int              # line number
    registration_type: str  # "spark.udf.register", "udf.register", "UDFRegistration", etc.
    return_type: str = ""  # return type if specified


# Patterns for UDF registration in Scala/Java
_UDF_PATTERNS = [
    # spark.udf.register("name", func)
    re.compile(r'spark\.udf\.register\s*\(\s*["\'](\w+)["\']'),
    # spark.udf.register("name", func, returnType)
    re.compile(r'spark\.udf\.register\s*\(\s*["\'](\w+)["\']\s*,\s*(\w+)'),
    # udf.register("name", func)
    re.compile(r'\.udf\.register\s*\(\s*["\'](\w+)["\']'),
    # UDF("name", func, returnType)
    re.compile(r'UDF\s*\(\s*["\'](\w+)["\']'),
    # registerFunction("name", func)
    re.compile(r'registerFunction\s*\(\s*["\'](\w+)["\']'),
    # spark.udf.registerJavaFunction("name", "class")
    re.compile(r'registerJavaFunction\s*\(\s*["\'](\w+)["\']\s*,\s*["\']([^"\']+)["\']'),
    # @udf or @UDF annotation (class-level)
    re.compile(r'@(?:udf|UDF)\s*(?:\([^)]*\))?\s*(?:class|object)\s+(\w+)'),
    # UDFRegistration
    re.compile(r'UDFRegistration\s*\(\s*["\'](\w+)["\']'),
    # .udf.register("name")
    re.compile(r'\.register\s*\(\s*["\'](\w+)["\']\s*,'),
]


def detect_udfs_in_source(filepath: str, source_text: str) -> list[UDFDefinition]:
    """Detect UDF registrations in Scala/Java source code."""
    udfs = []
    seen = set()

    for pattern in _UDF_PATTERNS:
        for m in pattern.finditer(source_text):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)

            line_num = source_text[:m.start()].count('\n') + 1

            # Try to find the enclosing class
            class_name = _find_enclosing_class(source_text, m.start())

            # Determine registration type
            match_text = m.group(0)
            if "spark.udf.register" in match_text:
                reg_type = "spark.udf.register"
            elif "registerJavaFunction" in match_text:
                reg_type = "registerJavaFunction"
            elif "registerFunction" in match_text:
                reg_type = "registerFunction"
            elif "@udf" in match_text.lower():
                reg_type = "@UDF annotation"
            else:
                reg_type = "udf.register"

            udfs.append(UDFDefinition(
                name=name,
                class_name=class_name,
                file=filepath,
                line=line_num,
                registration_type=reg_type,
            ))

    return udfs


def _find_enclosing_class(source_text: str, position: int) -> str:
    """Find the enclosing class/object name before the given position."""
    # Look backwards for 'class XXX' or 'object XXX'
    text_before = source_text[:position]
    m = re.search(r'(?:class|object)\s+(\w+)', text_before[-2000:])
    return m.group(1) if m else ""


# ── XML Config Cross-Reference ─────────────────────────────────────────────

@dataclass
class XMLLoaderRef:
    """Reference from Scala/Java code to an XML config file."""
    xml_file: str          # XML file being loaded
    loader_file: str       # Scala/Java file doing the loading
    loader_line: int       # line number
    loader_method: str     # how it's loaded (e.g., "spark.read.xml", "XMLLoader.load")
    context: str = ""      # surrounding code


# Patterns for XML file loading in Scala/Java
_XML_LOAD_PATTERNS = [
    # spark.read.xml("path/to/file.xml")
    re.compile(r'\.read\.xml\s*\(\s*["\']([^"\']+\.xml)["\']'),
    # spark.read.format("xml").load("path")
    re.compile(r'\.format\s*\(\s*["\']xml["\']\s*\)\s*(?:\.option\([^)]*\)\s*)*\.load\s*\(\s*["\']([^"\']+)["\']'),
    # XMLLoader.load("path")
    re.compile(r'XMLLoader\.load\s*\(\s*["\']([^"\']+\.xml)["\']'),
    # XmlReader("path")
    re.compile(r'XmlReader\s*\(\s*["\']([^"\']+\.xml)["\']'),
    # Generic: .load("something.xml")
    re.compile(r'\.load\s*\(\s*["\']([^"\']+\.xml)["\']'),
    # Source("path.xml")
    re.compile(r'Source\s*\.\s*fromFile\s*\(\s*["\']([^"\']+\.xml)["\']'),
    # XML.parse / XML.load
    re.compile(r'XML\.(?:parse|load)\s*\(\s*["\']([^"\']+\.xml)["\']'),
    # configFile = "xxx.xml"
    re.compile(r'(?:configFile|configPath|xmlFile|xmlPath)\s*=\s*["\']([^"\']+\.xml)["\']'),
]


def detect_xml_loaders(filepath: str, source_text: str) -> list[XMLLoaderRef]:
    """Detect XML config file loading in Scala/Java source code."""
    refs = []
    seen = set()

    for pattern in _XML_LOAD_PATTERNS:
        for m in pattern.finditer(source_text):
            xml_path = m.group(1)
            if xml_path in seen:
                continue
            seen.add(xml_path)

            line_num = source_text[:m.start()].count('\n') + 1

            # Determine loader method
            match_text = m.group(0)
            if ".read.xml" in match_text:
                method = "spark.read.xml"
            elif ".format" in match_text:
                method = "spark.read.format(xml)"
            elif "XMLLoader" in match_text:
                method = "XMLLoader.load"
            elif "XmlReader" in match_text:
                method = "XmlReader"
            elif "XML.parse" in match_text or "XML.load" in match_text:
                method = "scala.xml.XML"
            elif "Source.fromFile" in match_text:
                method = "scala.io.Source"
            else:
                method = ".load(xml)"

            # Get context
            ctx_start = max(0, m.start() - 50)
            ctx_end = min(len(source_text), m.end() + 50)
            context = source_text[ctx_start:ctx_end].replace('\n', ' ').strip()

            refs.append(XMLLoaderRef(
                xml_file=xml_path,
                loader_file=filepath,
                loader_line=line_num,
                loader_method=method,
                context=context,
            ))

    return refs


# ── Spark SQL Analysis (from XML content) ──────────────────────────────────

@dataclass
class SparkSQLAnalysis:
    """Analysis of a SQL statement found in XML."""
    sql_text: str
    xml_file: str
    xml_element: str     # XML element path (e.g., "root/step[@name='calc1']")
    line: int
    function_calls: list[SQLFunctionCall] = field(default_factory=list)
    tables_referenced: list[str] = field(default_factory=list)
    ctes: list[str] = field(default_factory=list)  # WITH clause names


# Pattern to extract table references from SQL
_TABLE_PATTERN = re.compile(
    r'\b(?:FROM|JOIN|INTO|OVERWRITE\s+TABLE|TABLE)\s+([`"\']?\w+(?:\.\w+)*[`"\']?)',
    re.IGNORECASE,
)

_CTE_PATTERN = re.compile(
    r'\bWITH\s+(?:RECURSIVE\s+)?(\w+)\s+AS\s*\(',
    re.IGNORECASE,
)


def analyze_spark_sql(sql_text: str, xml_file: str, xml_element: str, line: int) -> SparkSQLAnalysis:
    """Analyze a SQL statement for Spark-specific patterns."""
    analysis = SparkSQLAnalysis(
        sql_text=sql_text[:1000],
        xml_file=xml_file,
        xml_element=xml_element,
        line=line,
    )

    # Extract function calls
    analysis.function_calls = extract_sql_functions(sql_text, xml_file, line)

    # Extract table references
    seen_tables = set()
    for m in _TABLE_PATTERN.finditer(sql_text):
        table = m.group(1).strip('`"\'')
        if table.lower() not in ("set", "select", "where", "and", "or", "null"):
            if table not in seen_tables:
                seen_tables.add(table)
                analysis.tables_referenced.append(table)

    # Extract CTE names
    for m in _CTE_PATTERN.finditer(sql_text):
        analysis.ctes.append(m.group(1))

    return analysis
