from .common import *

def normalize_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()

def truncate(text: str, limit: int = 240) -> str:
    text = normalize_ws(text)
    if len(text) <= limit:
        return text
    return f'{text[:limit - 3]}...'

def looks_like_low_signal_log(message: str) -> bool:
    if not message:
        return True
    return any(pattern.search(message) for pattern in LOG_NOISE_PATTERNS)

def sanitize_log_line(message: str, limit: int = 260) -> str:
    """Return a short, non-raw sample line suitable for LLM context."""
    text = normalize_ws(message)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '<email>', text)
    text = re.sub(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', '<aws_key>', text)
    text = re.sub(r'\bv1:[A-Za-z0-9+/=]{16,}', 'v1:<encrypted>', text)
    text = re.sub(r'\b[A-Za-z0-9+/]{48,}={0,2}\b', '<token>', text)
    text = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '<uuid>', text, flags=re.I)
    text = re.sub(r'\b[0-9a-f]{32}\b', '<project_id>', text, flags=re.I)
    text = re.sub(r'https?://\S+', '<url>', text)
    text = re.sub(r'\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-Z]+\b', '<timestamp>', text)
    return truncate(text, limit)

def sanitize_error(message: Any, limit: int = 260) -> str:
    text = normalize_ws(str(message or ''))
    text = re.sub(r'Request ID: [A-Za-z0-9-]+', 'Request ID: <id>', text)
    text = re.sub(r"account ID '?[0-9]{12}'?", 'account ID <account>', text)
    return truncate(text, limit)

def sanitize_sql_statement(statement: Any, limit: int = 260) -> str:
    text = normalize_ws(str(statement or ''))
    if not text:
        return ''
    text = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '<uuid>', text, flags=re.I)
    text = re.sub(r'(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])', '<project_id>', text, flags=re.I)
    text = re.sub(r"'(?:''|[^'])*'", "'?'", text)
    text = re.sub(r'\b\d+(?:\.\d+)?\b', '?', text)
    return truncate(text, limit)

def log_signature(message: str) -> Optional[str]:
    if looks_like_low_signal_log(message):
        return None
    text = sanitize_log_line(message, limit=420)
    if not text:
        return None
    # Keep error class and stable prose, collapse volatile values.
    text = re.sub(r'\b\d+\b', '<n>', text)
    text = re.sub(r'\b0x[0-9a-f]+\b', '<hex>', text, flags=re.I)
    text = re.sub(r'(["\'])(?:<project_id>|<uuid>|[A-Za-z0-9_-]{20,})\1', r'\1<id>\1', text)
    return truncate(text, 220)

def logs_insights_regex(value: str) -> Optional[str]:
    value = normalize_ws(value)
    if len(value) < 4:
        return None
    if len(value) > 120:
        value = value[:120]
    return re.escape(value).replace('/', r'\/')

def logs_insights_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

def metric_filter_terms(pattern: str) -> List[str]:
    pattern = normalize_ws(pattern)
    if not pattern:
        return []
    # Simple CloudWatch metric filter terms such as ERROR should be preserved
    # exactly; they define what triggered the alarm.
    if re.fullmatch(r'[A-Za-z0-9_.:-]{3,80}', pattern):
        return [pattern]

    terms: List[str] = []
    terms.extend(re.findall(r'"([^"]{3,120})"', pattern))
    for word in re.findall(r'\b[A-Za-z][A-Za-z0-9_.:-]{3,80}\b', pattern):
        if word.lower() in BROAD_FILTER_WORDS:
            continue
        if word not in terms and (
            word.isupper()
            or any(token in word.lower() for token in ['error', 'exception', 'timeout', 'fail', 'denied'])
        ):
            terms.append(word)
    return unique(terms)[:6]

def logs_result_dict(row: Sequence[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for cell in row:
        field = cell.get('field')
        value = cell.get('value')
        if field is not None and value is not None:
            out[field] = value
    return out
