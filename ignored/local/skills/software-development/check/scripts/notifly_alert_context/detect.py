from .common import *
from .text import normalize_ws

def detect_alarm_name(text: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    patterns = [
        r'CloudWatch Alarm\s*\|\s*(.*?)\s*\|\s*[a-z]{2}-[a-z]+-\d\s*\|\s*Account',
        r'"AlarmName"\s*:\s*"([^"]+)"',
        r'AlarmName\s*[:=]\s*([^\n]+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I | re.S)
        if m:
            return normalize_ws(m.group(1))
    return None

def detect_region(text: str, override: Optional[str]) -> str:
    if override:
        return override
    m = re.search(r'region=([a-z]{2}-[a-z]+-\d)', text)
    if m:
        return m.group(1)
    m = re.search(r'\|\s*([a-z]{2}-[a-z]+-\d)\s*\|\s*Account', text)
    if m:
        return m.group(1)
    m = re.search(r'\b([a-z]{2}-[a-z]+-\d)\b', text)
    if m:
        return m.group(1)
    return os.environ.get('AWS_DEFAULT_REGION', DEFAULT_AWS_REGION)

def detect_log_groups(text: str) -> List[str]:
    return unique(re.findall(r'/aws/[A-Za-z0-9._/\-]+', text))

def detect_project_ids(text: str) -> List[str]:
    """Extract project_ids from explicit key=value / JSON / log-style fields only.

    Sharded table-name suffixes (e.g. delivery_result_<id>) are intentionally
    excluded.  A project_id that appears only inside a
    "relation <table>_<id> does not exist" error message belongs to a
    deleted/absent table and must NOT be promoted to the primary alarm scope.
    Those IDs would produce a false scope attribution — the alarm that fired
    is unrelated to those deleted projects.

    Use detect_sharded_table_refs() separately when table-family attribution
    is explicitly needed.
    """
    patterns = [
        r'\bproject[_\s-]*id\b\s*[:=#-]?\s*[`"\']?([0-9a-f]{32})',
        r'\bprojectId\b\s*[:=#-]?\s*[`"\']?([0-9a-f]{32})',
        r'["\']project[_-]?id["\']\s*:\s*["\']([0-9a-f]{32})["\']',
        r'["\']projectId["\']\s*:\s*["\']([0-9a-f]{32})["\']',
    ]
    out: List[str] = []
    for pattern in patterns:
        out.extend(re.findall(pattern, text or '', flags=re.I))
    # NOTE: detect_sharded_table_refs() is intentionally NOT called here.
    return unique(out)

def detect_sharded_table_refs(text: str) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    for family, project_id in re.findall(r'\b([A-Za-z][A-Za-z0-9_]*?)_([0-9a-f]{32})\b', text or '', flags=re.I):
        refs.append({
            'table_family': family,
            'project_id': project_id,
            'table_pattern': f'{family}_<project_id>',
        })
    seen = set()
    out = []
    for ref in refs:
        key = (ref['table_family'], ref['project_id'])
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out

def detect_sharded_table_names(text: str) -> List[str]:
    return unique(re.findall(r'\b[A-Za-z][A-Za-z0-9_]*_[0-9a-f]{32}(?:_[A-Za-z0-9_]+)?\b', text or '', flags=re.I))

def detect_campaign_ids(text: str) -> List[str]:
    patterns = [
        r'\bcampaign[_\s-]*id\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'\bcampaignId\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'["\']campaign_id["\']\s*:\s*["\']([^"\']{3,64})["\']',
        r'["\']campaignId["\']\s*:\s*["\']([^"\']{3,64})["\']',
    ]
    out: List[str] = []
    for pattern in patterns:
        out.extend(re.findall(pattern, text, flags=re.I))
    noise = {'for', 'from', 'and', 'the', 'with', 'null', 'none', 'undefined', 'unknown'}
    return unique([item for item in out if item.lower() not in noise])

def detect_project_campaign_pairs(text: str) -> List[Dict[str, str]]:
    pairs: List[Dict[str, str]] = []
    patterns = [
        (
            r'\bproject[_\s-]*id\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})[`"\']?'
            r'[^\n\r]{0,1200}?\bcampaign[_\s-]*id\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})'
        ),
        (
            r'\bcampaign[_\s-]*id\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})[`"\']?'
            r'[^\n\r]{0,1200}?\bproject[_\s-]*id\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})'
        ),
        r'\bprojectId\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})[`"\']?[^\n\r]{0,1200}?\bcampaignId\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'\bcampaignId\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})[`"\']?[^\n\r]{0,1200}?\bprojectId\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})',
        r'Project Id:\s*([0-9a-f]{32})[^\n\r]{0,1200}?Campaign Id:\s*([A-Za-z0-9_-]{3,64})',
        r'Campaign Id:\s*([A-Za-z0-9_-]{3,64})[^\n\r]{0,1200}?Project Id:\s*([0-9a-f]{32})',
        r'["\']project[_-]?id["\']\s*:\s*["\']([0-9a-f]{32})["\'][^\n\r]{0,1200}?["\']campaign[_-]?id["\']\s*:\s*["\']([A-Za-z0-9_-]{3,64})["\']',
        r'["\']campaign[_-]?id["\']\s*:\s*["\']([A-Za-z0-9_-]{3,64})["\'][^\n\r]{0,1200}?["\']project[_-]?id["\']\s*:\s*["\']([0-9a-f]{32})["\']',
    ]
    for idx, pattern in enumerate(patterns):
        for first, second in re.findall(pattern, text or '', flags=re.I | re.S):
            if idx in (0, 2, 4, 6):
                project_id, campaign_id = first, second
            else:
                campaign_id, project_id = first, second
            pairs.append({'project_id': project_id, 'campaign_id': campaign_id})
    seen = set()
    out = []
    for pair in pairs:
        key = (pair['project_id'], pair['campaign_id'])
        if key in seen:
            continue
        seen.add(key)
        out.append(pair)
    return out

def detect_user_journey_ids(text: str) -> List[str]:
    patterns = [
        r'\buser[_\s-]*journey[_\s-]*id\b\s*[:=#-]?\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'\buserJourneyId\b\s*[:=#-]?\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'["\']user_journey_id["\']\s*:\s*["\']([^"\']{3,64})["\']',
        r'["\']userJourneyId["\']\s*:\s*["\']([^"\']{3,64})["\']',
    ]
    out: List[str] = []
    for pattern in patterns:
        out.extend(re.findall(pattern, text, flags=re.I))
    return unique(out)

def detect_user_journey_refs(text: str) -> List[str]:
    refs = []
    for match in re.findall(r'\buser[_\s-]*journey[A-Za-z0-9_./-]*\b', text, flags=re.I):
        refs.append(match)
    for match in re.findall(r'\bjourney[_\s-]*(?:session|event|step|node)[A-Za-z0-9_./-]*\b', text, flags=re.I):
        refs.append(match)
    noise = {'user_journey_ids', 'user_journey_refs', 'user_journey_id'}
    return unique([ref for ref in refs if ref.lower() not in noise])

def detect_keywords(text: str) -> List[str]:
    low = text.lower()
    found = []
    for phrase in KNOWN_PHRASES:
        if phrase.lower() in low:
            found.append(phrase)
    return unique(found)

def detect_queue_names(text: str) -> List[str]:
    return unique(re.findall(r'\b[a-z0-9-]+(?:-queue(?:-dlq)?)\b', text))

def detect_service_names(text: str) -> List[str]:
    services = []
    patterns = [
        r'\[([A-Za-z0-9][A-Za-z0-9_.-]{2,80})\]\s+(?:4xx|5xx|error|errors|latency|timeout|slow)\b',
        r'\bservice(?:name)?\b\s*[:=#]\s*[`"\']?([A-Za-z0-9][A-Za-z0-9_.-]{2,80})',
    ]
    for pattern in patterns:
        services.extend(re.findall(pattern, text or '', flags=re.I))
    return unique(services)

def service_names_from_log_groups(log_groups: Sequence[str]) -> List[str]:
    services = []
    for group in log_groups or []:
        parts = [part for part in str(group).split('/') if part]
        if len(parts) >= 4 and parts[:2] == ['aws', 'ecs']:
            services.append(parts[-1])
        elif len(parts) >= 3 and parts[:2] == ['aws', 'lambda']:
            services.append(parts[-1])
    return unique(services)

def detect_lambda_names(text: str, log_groups: Sequence[str], alarm: Optional[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for group in log_groups or []:
        m = re.search(r'^/aws/lambda/([A-Za-z0-9-_]+)', group)
        if m:
            names.append(m.group(1))
    if isinstance(alarm, dict):
        names.extend(alarm_dimension_value(alarm, ['FunctionName']))
    patterns = [
        r'\b([a-z0-9][a-z0-9-]{2,})\s+lambda\s+(?:error|errors|latency|timeout)\b',
        r'\blambda\s+(?:function(?:name)?|name)\b\s*[:=#]\s*[`"\']?([A-Za-z0-9-_]{3,80})',
        r'\bfunction(?:name)?\b\s*[:=#]\s*[`"\']?([A-Za-z0-9-_]{3,80})',
    ]
    for pattern in patterns:
        names.extend(re.findall(pattern, text or '', flags=re.I))
    return unique(names)

def alarm_dimension_value(alarm: Any, names: Sequence[str]) -> List[str]:
    if not isinstance(alarm, dict):
        return []
    dims = alarm.get('Dimensions') or []
    out = []
    wanted = {name.lower() for name in names}
    for dim in dims:
        if not isinstance(dim, dict):
            continue
        name = str(dim.get('Name') or '').lower()
        value = str(dim.get('Value') or '')
        if name in wanted and value:
            out.append(value)
    return unique(out)
