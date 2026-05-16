"""Spark SQL and UDF analysis.

Provides function catalogs, SQL function extraction, UDF detection,
XML loader detection, and Spark SQL analysis utilities.
"""

from __future__ import annotations


import logging
import re

logger = logging.getLogger("repo_analyzer.analysis.spark")

# ---------------------------------------------------------------------------
# Spark SQL built-in function catalog (300+ functions)
# ---------------------------------------------------------------------------

SPARK_FUNCTIONS: dict[str, list[str]] = {
    "aggregate": [
        "count", "count_if", "count_min_sketch", "first", "first_value",
        "last", "last_value", "min", "max", "sum", "sum_distinct",
        "avg", "average", "mean", "collect_list", "collect_set",
        "approx_count_distinct", "approx_percentile",
        "percentile_approx", "percentile", "var_pop", "var_samp",
        "variance", "stddev_pop", "stddev_samp", "stddev",
        "corr", "covar_pop", "covar_samp", "regr_intercept",
        "regr_slope", "regr_r2", "regr_count", "regr_avgx",
        "regr_avgy", "regr_sxx", "regr_syy", "regr_sxy",
        "skewness", "kurtosis", "grouping", "grouping_id",
        "every", "some", "any", "bool_and", "bool_or",
        "histogram_numeric", "mode", "bitwise_or_agg",
        "bitwise_and_agg", "bitwise_xor_agg",
    ],
    "window": [
        "row_number", "rank", "dense_rank", "percent_rank",
        "ntile", "cume_dist", "lag", "lead", "first_value",
        "last_value", "nth_value", "window", "session_window",
        "input_file_name", "input_file_block_start",
        "input_file_block_length",
    ],
    "string": [
        "ascii", "base64", "bit_length", "char", "character_length",
        "chr", "concat", "concat_ws", "contains", "decode", "elt",
        "encode", "endswith", "field", "find_in_set", "format_number",
        "format_string", "initcap", "instr", "lcase", "left",
        "length", "levenshtein", "locate", "lower", "lpad", "ltrim",
        "luhn_check", "mask", "octet_length", "overlay", "position",
        "printf", "regexp_count", "regexp_extract", "regexp_extract_all",
        "regexp_instr", "regexp_like", "regexp_replace", "regexp_substr",
        "repeat", "replace", "reverse", "right", "rpad", "rtrim",
        "sentences", "soundex", "space", "split", "split_part",
        "startswith", "str_to_map", "substr", "substring",
        "substring_index", "translate", "trim", "ucase", "unbase64",
        "upper", "url_decode", "url_encode",
    ],
    "math": [
        "abs", "acos", "acosh", "asin", "asinh", "atan", "atan2",
        "atanh", "bin", "bround", "cbrt", "ceil", "ceiling",
        "conv", "cos", "cosh", "cot", "csc", "degrees", "e",
        "exp", "expm1", "factorial", "floor", "format_number",
        "hex", "hypot", "isnan", "isnotnull", "isnull",
        "ln", "log", "log10", "log1p", "log2", "mod", "negative",
        "pi", "pmod", "positive", "pow", "power", "radians",
        "rand", "randn", "rint", "round", "sec", "shiftleft",
        "shiftright", "shiftrightunsigned", "sign", "signum",
        "sin", "sinh", "sqrt", "tan", "tanh", "try_add",
        "try_divide", "try_multiply", "try_subtract",
        "unhex", "width_bucket",
    ],
    "datetime": [
        "add_months", "current_date", "current_timestamp",
        "current_timezone", "date_add", "date_diff", "date_format",
        "date_from_unix_date", "date_part", "date_sub",
        "date_trunc", "datediff", "day", "dayofmonth", "dayofweek",
        "dayofyear", "extract", "from_unixtime", "from_utc_timestamp",
        "hour", "last_day", "localtimestamp", "make_date",
        "make_dt_interval", "make_interval", "make_timestamp",
        "make_ym_interval", "minute", "month", "months_between",
        "next_day", "now", "quarter", "second", "session_window",
        "timestamp_micros", "timestamp_millis", "timestamp_seconds",
        "to_date", "to_timestamp", "to_unix_timestamp", "to_utc_timestamp",
        "trunc", "unix_date", "unix_micros", "unix_millis",
        "unix_seconds", "unix_timestamp", "weekofyear", "window",
        "year",
    ],
    "collection": [
        "array", "array_append", "array_compact", "array_contains",
        "array_distinct", "array_except", "array_insert", "array_intersect",
        "array_join", "array_max", "array_min", "array_position",
        "array_prepend", "array_remove", "array_repeat", "array_sort",
        "array_union", "arrays_overlap", "arrays_zip", "cardinality",
        "concat", "element_at", "element_at", "explode", "explode_outer",
        "flatten", "from_json", "get", "get_json_object",
        "inline", "inline_outer", "json_array_length",
        "json_object_keys", "json_tuple", "map_concat",
        "map_contains_key", "map_entries", "map_filter",
        "map_from_arrays", "map_from_entries", "map_keys",
        "map_values", "map_zip_with", "named_struct",
        "posexplode", "posexplode_outer", "schema_of_json",
        "sequence", "shuffle", "size", "slice", "sort_array",
        "struct", "to_json", "transform", "transform_keys",
        "transform_values", "try_element_at", "zip_with",
    ],
    "conditional": [
        "assert_true", "coalesce", "if", "ifnull", "isnan",
        "isnotnull", "isnull", "nullif", "nvl", "nvl2",
        "case", "when", "then", "else", "end",
        "decode", "greatest", "least",
    ],
    "conversion": [
        "cast", "try_cast", "typeof", "bigint", "binary", "boolean",
        "date", "decimal", "double", "float", "int", "integer",
        "long", "short", "smallint", "string", "timestamp",
        "tinyint", "varchar",
    ],
    "misc": [
        "aes_decrypt", "aes_encrypt", "bitmap_bit_position",
        "bitmap_bucket_number", "bitmap_count", "cardinality",
        "crc32", "current_catalog", "current_database",
        "current_schema", "current_user", "equal_null",
        "from_csv", "get", "hash", "hll_sketch_agg",
        "hll_sketch_estimate", "hll_union", "hll_union_agg",
        "java_method", "isnan", "isnotnull", "isnull",
        "kurtosis", "monotonically_increasing_id",
        "md5", "raise_error", "reflect", "require_nonnull",
        "sha", "sha1", "sha2", "spark_partition_id",
        "stack", "to_csv", "try_aes_decrypt",
        "typeof", "user", "uuid", "version",
        "xxhash64",
    ],
}
"""Spark SQL built-in function catalog organized by category."""


def _all_spark_functions() -> set[str]:
    """Flatten all Spark functions into a single set."""
    result: set[str] = set()
    for funcs in SPARK_FUNCTIONS.values():
        result.update(funcs)
    return result


_ALL_SPARK_FUNCS = _all_spark_functions()


# ---------------------------------------------------------------------------
# SQL function extraction
# ---------------------------------------------------------------------------

# Matches function calls in SQL: word followed by optional parenthesis
_SQL_FUNC_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(", re.IGNORECASE)

# SQL keywords that look like function calls but aren't
_SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "in", "is", "as",
    "on", "join", "left", "right", "inner", "outer", "cross", "full",
    "group", "by", "order", "having", "limit", "offset", "union",
    "except", "intersect", "insert", "into", "values", "update",
    "set", "delete", "create", "table", "view", "index", "drop",
    "alter", "add", "column", "primary", "key", "foreign",
    "references", "constraint", "check", "default", "null",
    "not", "between", "like", "exists", "all", "any", "some",
    "distinct", "all", "fetch", "next", "row", "rows", "only",
    "with", "recursive", "lateral", "natural", "using", "pivot",
    "unpivot", "tablesample", "partition", "over", "rows",
    "range", "groups", "unbounded", "preceding", "following",
    "current", "row", "no", "action", "cascade", "restrict",
    "temporary", "temp", "if", "replace", "describe", "explain",
    "show", "use", "grant", "revoke", "trigger", "before",
    "after", "for", "each", "statement", "execute", "function",
    "returns", "language", "sql", "contains", "reads",
    "modifies", "data", "comment", "cache", "uncache",
    "clear", "refresh", "add", "files", "jar", "jars",
    "property", "properties", "extended", "formatted",
    "serde", "stored", "location", "partitioned", "clustered",
    "sorted", "buckets", "skewed", "terminated", "escaped",
    "lines", "delimited", "fields", "collection", "items",
    "keys", "map", "struct", "array", "interval", "year",
    "month", "day", "hour", "minute", "second", "try",
    "then", "else", "end", "case", "when", "begin",
}


def extract_sql_functions(
    sql_text: str,
    filepath: str = "",
    line_offset: int = 0,
) -> list[dict]:
    """Extract function calls from a SQL text block.

    Parameters
    ----------
    sql_text : str
        Raw SQL source text.
    filepath : str
        Source file path for provenance.
    line_offset : int
        Starting line number offset within the file.

    Returns
    -------
    list[dict]
        Each entry: ``{"name": str, "line": int, "filepath": str,
        "is_spark_builtin": bool}``
    """
    results: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for i, line in enumerate(sql_text.splitlines(), start=line_offset + 1):
        for m in _SQL_FUNC_RE.finditer(line):
            name = m.group(1).lower()
            if name in _SQL_KEYWORDS:
                continue
            key = (name, i)
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "name": name,
                "line": i,
                "filepath": filepath,
                "is_spark_builtin": name in _ALL_SPARK_FUNCS,
            })

    return results


# ---------------------------------------------------------------------------
# UDF detection
# ---------------------------------------------------------------------------

_UDF_PATTERNS: list[re.Pattern] = [
    # Scala/Java: spark.udf.register("name", ...)
    re.compile(
        r"""(?:spark|sqlContext|sc)\.udf\.register\s*\(\s*["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    # Python: spark.udf.registerJavaFunction("name", ...)
    re.compile(
        r"""(?:spark|sqlContext)\.udf\.registerJavaFunction\s*\(\s*["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    # Python: @udf / @pandas_udf decorator with name
    re.compile(
        r"""@(?:pandas_)?udf\s*\(\s*.*?["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    # SQL: CREATE FUNCTION name
    re.compile(
        r"""\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY\s+)?FUNCTION\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"']?(\w+)[`"']?""",
        re.IGNORECASE,
    ),
    # Hive: ADD JAR + CREATE TEMPORARY FUNCTION
    re.compile(
        r"""\bCREATE\s+TEMPORARY\s+FUNCTION\s+[`"']?(\w+)[`"']?\s+AS\s+["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    # Scala: val udfName = udf(...)
    re.compile(
        r"""(?:val|var|def)\s+(\w+)\s*=\s*(?:udf|pandas_udf)\s*\(""",
        re.IGNORECASE,
    ),
    # registerFunction in older APIs
    re.compile(
        r"""\.registerFunction\s*\(\s*["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    # SQL: CREATE TEMP FUNCTION
    re.compile(
        r"""\bCREATE\s+TEMP\s+FUNCTION\s+[`"']?(\w+)[`"']?\s+AS\s+["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    # spark.sessionState.functionRegistry.registerFunction
    re.compile(
        r"""functionRegistry\.registerFunction\s*\(\s*["']([^"']+)["']""",
        re.IGNORECASE,
    ),
]
"""Regex patterns for detecting UDF registrations (9 patterns)."""


def detect_udfs_in_source(
    filepath: str,
    source_text: str,
) -> list[dict]:
    """Detect UDF registrations in source code.

    Parameters
    ----------
    filepath : str
        Path to the source file.
    source_text : str
        Full source text to scan.

    Returns
    -------
    list[dict]
        Each entry: ``{"name": str, "line": int, "filepath": str,
        "pattern": str}``
    """
    results: list[dict] = []
    seen: set[str] = set()

    for i, line in enumerate(source_text.splitlines(), start=1):
        for pat_idx, pat in enumerate(_UDF_PATTERNS):
            for m in pat.finditer(line):
                name = m.group(1)
                if name in seen:
                    continue
                seen.add(name)
                results.append({
                    "name": name,
                    "line": i,
                    "filepath": filepath,
                    "pattern": f"udf_pattern_{pat_idx}",
                })

    return results


# ---------------------------------------------------------------------------
# XML loader detection
# ---------------------------------------------------------------------------

_XML_LOADER_PATTERNS: list[re.Pattern] = [
    # SparkContext.textFile / wholeTextFiles
    re.compile(
        r"""(?:sc|sparkContext|spark)\.(?:textFile|wholeTextFiles|newAPIHadoopFile)\s*\(\s*["']([^"']*\.xml)["']""",
        re.IGNORECASE,
    ),
    # spark.read.format("xml") / .format("com.databricks.spark.xml")
    re.compile(
        r"""\.format\s*\(\s*["'](?:xml|com\.databricks\.spark\.xml|org\.apache\.spark\.sql\.xml)["']""",
        re.IGNORECASE,
    ),
    # .option("rowTag", ...) indicating XML processing
    re.compile(
        r"""\.option\s*\(\s*["'](?:rowTag|rootTag|attributePrefix|valueTag)["']""",
        re.IGNORECASE,
    ),
    # XMLInputFormat references
    re.compile(
        r"""(?:XmlInputFormat|XMLInputFormat|StreamInputFormat)""",
        re.IGNORECASE,
    ),
    # loadXML / parseXML function calls
    re.compile(
        r"""(?:loadXML|parseXML|readXML|xmlToDataFrame)\s*\(""",
        re.IGNORECASE,
    ),
    # Hadoop XML config: mapreduce.input.xmlinputformat
    re.compile(
        r"""(?:mapreduce\.input\.xmlinputformat|xmlinput\.starttag|xmlinput\.endtag)""",
        re.IGNORECASE,
    ),
    # Databricks spark-xml package import
    re.compile(
        r"""(?:com\.databricks\.spark\.xml|spark\.xml)""",
        re.IGNORECASE,
    ),
    # XML schema / XSD file references
    re.compile(
        r"""["'][^"']*\.xsd["']""",
        re.IGNORECASE,
    ),
]
"""Regex patterns for detecting XML loader references (8 patterns)."""


def detect_xml_loaders(
    filepath: str,
    source_text: str,
) -> list[dict]:
    """Detect XML loader references in source code.

    Parameters
    ----------
    filepath : str
        Path to the source file.
    source_text : str
        Full source text to scan.

    Returns
    -------
    list[dict]
        Each entry: ``{"name": str, "line": int, "filepath": str,
        "pattern": str}``
    """
    results: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for i, line in enumerate(source_text.splitlines(), start=1):
        for pat_idx, pat in enumerate(_XML_LOADER_PATTERNS):
            for m in pat.finditer(line):
                # Use the matched text as the name
                name = m.group(0) if m.lastindex is None or m.lastindex == 0 else m.group(1)
                key = (name, i)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "name": name,
                    "line": i,
                    "filepath": filepath,
                    "pattern": f"xml_loader_{pat_idx}",
                })

    return results


# ---------------------------------------------------------------------------
# Spark SQL analysis
# ---------------------------------------------------------------------------

# CTE detection
_CTE_RE = re.compile(
    r"""\bWITH\s+(?:RECURSIVE\s+)?[`"']?(\w+)[`"']?\s+AS\s*\(""",
    re.IGNORECASE,
)

# Table references (FROM / JOIN)
_TABLE_REF_RE = re.compile(
    r"""(?:FROM|JOIN)\s+(?:LATERAL\s+)?(?:VIEW\s+)?[`"']?(\w+(?:\.\w+)?)[`"']?(?:\s+(?:AS\s+)?[`"']?(\w+)[`"']?)?""",
    re.IGNORECASE,
)

# Subquery alias
_SUBQUERY_ALIAS_RE = re.compile(
    r"""\)\s+(?:AS\s+)?[`"']?(\w+)[`"']?""",
    re.IGNORECASE,
)


def analyze_spark_sql(sql_text: str) -> dict:
    """Analyze a Spark SQL block for function references, table refs, and CTEs.

    Parameters
    ----------
    sql_text : str
        Raw SQL source.

    Returns
    -------
    dict
        Keys: ``functions`` (list[dict]), ``table_refs`` (list[str]),
        ``ctes`` (list[str]), ``is_spark_sql`` (bool).
    """
    functions = extract_sql_functions(sql_text)

    # Extract table references
    table_refs: list[str] = []
    seen_tables: set[str] = set()
    for m in _TABLE_REF_RE.finditer(sql_text):
        tbl = m.group(1)
        if tbl and tbl.lower() not in _SQL_KEYWORDS and tbl not in seen_tables:
            seen_tables.add(tbl)
            table_refs.append(tbl)

    # Extract CTEs
    ctes: list[str] = []
    for m in _CTE_RE.finditer(sql_text):
        cte_name = m.group(1)
        if cte_name and cte_name.lower() not in _SQL_KEYWORDS:
            ctes.append(cte_name)

    # Heuristic: is this Spark SQL?
    spark_indicators = {
        "lateral view", "explode", "posexplode", "from_json",
        "to_json", "get_json_object", "schema_of_json",
        "from_csv", "to_csv", "schema_of_csv",
        "window", "session_window", "map_keys", "map_values",
        "array_", "struct", "named_struct", "transform",
        "aggregate", "reduce", "zip_with", "filter",
    }
    sql_lower = sql_text.lower()
    is_spark = any(ind in sql_lower for ind in spark_indicators)
    # Also flag if Spark built-in functions are found
    if not is_spark:
        spark_builtin_found = any(f["is_spark_builtin"] for f in functions)
        is_spark = spark_builtin_found

    result = {
        "functions": functions,
        "table_refs": table_refs,
        "ctes": ctes,
        "is_spark_sql": is_spark,
    }

    logger.debug(
        "Spark SQL analysis: %d functions, %d table refs, %d CTEs, spark=%s",
        len(functions), len(table_refs), len(ctes), is_spark,
    )

    return result
