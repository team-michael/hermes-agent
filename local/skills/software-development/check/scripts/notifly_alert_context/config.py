import re
from pathlib import Path


DEFAULT_AWS_REGION = 'ap-northeast-2'
DEFAULT_REPO = Path('/home/ubuntu/notifly-event')
PROJECT_TABLE_NAME = 'project'

MAX_LOG_QUERY_GROUPS = 4
MAX_LOG_EVENTS = 300
MAX_LOG_SAMPLES_PER_SIGNATURE = 3
MAX_CODE_CONTEXTS = 2
CODE_CONTEXT_RADIUS = 20
MAX_RDS_PI_INSTANCES = 4
MAX_RDS_PI_SQL = 5
MAX_CONTEXT_ITEMS = 6

KNOWN_PHRASES = [
    'processing took longer than expected',
    'took too long',
    'all keys in the pipeline should belong to the same slots allocation group',
    'crossslot',
    'cpuutilization',
    'freeablememory',
    'approximate number of messages visible',
    'approximateNumberOfMessagesVisible',
]

CODE_GLOBS = [
    '*.ts', '*.tsx', '*.js', '*.jsx', '*.mjs', '*.cjs',
    '*.py', '*.go', '*.java', '*.kt', '*.sql', '*.yml', '*.yaml',
    '*.tf', '*.tfvars', '*.hcl',
]

EXCLUDE_GLOBS = [
    '!AGENTS.md', '!SOUL.md', '!**/node_modules/**', '!**/.git/**',
    '!**/dist/**', '!**/build/**', '!**/coverage/**', '!**/.next/**',
    '!**/logs/**', '!**/sessions/**', '!**/*.md', '!**/*.jsonl',
    '!**/*lock*.yaml', '!**/*lock*.yml', '!**/package-lock.json',
    '!**/yarn.lock', '!**/pnpm-lock.yaml',
]

LOG_NOISE_PATTERNS = [
    re.compile(r'"_aws"\s*:', re.I),
    re.compile(r'^\S+\s+\S+\s+\S+\s+\[[^\]]+\]\s+"(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+', re.I),
    re.compile(r'\bELB-HealthChecker\b', re.I),
    re.compile(r'\bSuccess, message sent\b', re.I),
]

ERROR_DETAIL_PATTERNS = [
    re.compile(r'(?i)\bduplicate key\b'),
    re.compile(r'(?i)\bviolates unique constraint\b'),
    re.compile(r'(?i)\b(sqlstate|constraint|deadlock|timeout|timed out|etimedout)\b'),
    re.compile(r'(?i)^table:\s'),
    re.compile(r'(?i)^routine:\s'),
    re.compile(r'(?i)\b(exception|typeerror|referenceerror|validationerror)\b'),
    re.compile(r'(?i)\b(error from|failed|denied|rejected|throttl)\b'),
    re.compile(r'(?i)\b(statuscode|status code|errorcode|resultcode)\b'),
    re.compile(r'(?i)^query:\s'),
]

ERROR_CONTEXT_PATTERNS = [
    re.compile(r'(?i)\b(received command|command:|operation:|handler|route|path|method)\b'),
    re.compile(r'(?i)\b(project id|project_id|campaign id|campaign_id|user_journey_id)\b'),
    re.compile(r'(?i)\b(request id|trace id|resource:)\b'),
]

BROAD_FILTER_WORDS = {
    'message', 'status', 'level', 'service', 'timestamp', 'environment',
    'projectid', 'project_id', 'method', 'path', 'normalizedpath',
}

CAMPAIGN_CAPABLE_TABLE_PREFIXES = (
    'delivery_result',
    'message_events',
    'scheduled_messages',
    'campaign',
    'campaigns',
    'user_journey',
    'user_journey_nodes',
    'scheduled_nodes',
)
