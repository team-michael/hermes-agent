from .common import *
from .text import normalize_ws, truncate

def preview_token(token: str) -> str:
    token = normalize_ws(token)
    if len(token) <= 40:
        return token
    return f"{token[:12]}...{token[-10:]}"

def read_code_context(path: Path, line_no: int, radius: int = CODE_CONTEXT_RADIUS) -> str:
    try:
        lines = path.read_text(errors='replace').splitlines()
    except Exception as e:
        return f'(unable to read context: {e})'
    start = max(1, line_no - radius)
    end = min(len(lines), line_no + radius)
    rendered = []
    for idx in range(start, end + 1):
        line = lines[idx - 1]
        if len(line) > 220:
            line = line[:217] + '...'
        rendered.append(f'{idx}: {line}')
    return '\n'.join(rendered)

def repo_search(repo: Path, tokens: Sequence[str]) -> Optional[List[Dict[str, Any]]]:
    if not repo.exists():
        return None
    rg = shutil_which('rg')
    if not rg:
        return None
    hits: List[Dict[str, Any]] = []
    seen_locations = set()
    for token in unique([t for t in tokens if t and len(t) >= 4])[:6]:
        try:
            cmd = [rg, '-n', '-S', '--no-heading', '--color', 'never', '-m', '4']
            for glob in CODE_GLOBS:
                cmd.extend(['-g', glob])
            for glob in EXCLUDE_GLOBS:
                cmd.extend(['-g', glob])
            cmd.extend([token, str(repo)])
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=False,
            )
            if proc.stdout.strip():
                for raw in proc.stdout.strip().splitlines()[:4]:
                    parts = raw.split(':', 2)
                    if len(parts) != 3:
                        continue
                    file_path, line_s, matched = parts
                    try:
                        line_no = int(line_s)
                    except Exception:
                        continue
                    loc_key = (file_path, line_no)
                    if loc_key in seen_locations:
                        continue
                    seen_locations.add(loc_key)
                    path = Path(file_path)
                    hit: Dict[str, Any] = {
                        'token_preview': preview_token(token),
                        'file': str(path),
                        'line': line_no,
                        'match': truncate(matched, 220),
                    }
                    if len(hits) < MAX_CODE_CONTEXTS:
                        hit['context_excerpt'] = read_code_context(path, line_no)
                    hits.append(hit)
                    if len(hits) >= 8:
                        return hits
        except Exception as e:
            hits.append({'token_preview': preview_token(token), 'error': str(e)})
    return hits[:12]

def _relative_repo_path(repo: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def _next_page_file(repo: Path, transaction: str) -> Optional[Path]:
    route = (transaction or '').split('?', 1)[0].strip()
    route = re.sub(r'^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+', '', route, flags=re.I)
    route = route.strip('/')
    if not route:
        return None
    page_roots = [
        repo / 'services/server/web-console/src/pages',
        repo / 'src/pages',
    ]
    for root in page_roots:
        for suffix in ('.tsx', '.ts', '.jsx', '.js'):
            for candidate in (root / f'{route}{suffix}', root / route / f'index{suffix}'):
                if candidate.is_file():
                    return candidate
    return None


def _named_function_line(source: str, name: str) -> Optional[int]:
    pattern = re.compile(
        rf'\b(?:export\s+)?(?:default\s+)?(?:async\s+)?'
        rf'(?:function|class)\s+{re.escape(name)}\b|'
        rf'\b(?:export\s+)?(?:const|let|var)\s+{re.escape(name)}\b'
    )
    for line_no, line in enumerate(source.splitlines(), 1):
        if pattern.search(line):
            return line_no
    return None


def _default_page_function(source: str) -> tuple[Optional[str], Optional[int]]:
    match = re.search(
        r'\bexport\s+default\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)',
        source,
    )
    if not match:
        return None, None
    name = match.group(1)
    return name, _named_function_line(source, name)


def _rendered_local_symbols(source: str) -> List[str]:
    local_imports: set[str] = set()
    for match in re.finditer(
        r'import\s+\{([^}]+)\}\s+from\s+["\'](?:@/|\./|\.\./)[^"\']+["\']',
        source,
    ):
        for item in match.group(1).split(','):
            name = item.strip().split(' as ')[-1].strip()
            if re.fullmatch(r'[A-Z][A-Za-z0-9_$]*', name):
                local_imports.add(name)
    rendered = re.findall(r'<([A-Z][A-Za-z0-9_$]*)\b', source)
    ignored = {'Head', 'Fragment', 'AsyncBoundary'}
    return unique(
        symbol for symbol in rendered
        if symbol in local_imports and symbol not in ignored
    )[:4]


def _symbol_definition(repo: Path, symbol: str) -> Optional[Dict[str, Any]]:
    roots = [
        repo / 'services/server/web-console/src',
        repo / 'src',
    ]
    pattern = (
        rf'\b(?:export\s+)?(?:default\s+)?(?:async\s+)?'
        rf'(?:function|class)\s+{re.escape(symbol)}\b|'
        rf'\b(?:export\s+)?(?:const|let|var)\s+{re.escape(symbol)}\b'
    )
    rg = shutil_which('rg')
    for root in roots:
        if not root.is_dir():
            continue
        if rg:
            proc = subprocess.run(
                [
                    rg, '-n', '--no-heading', '--color', 'never', '-m', '1',
                    '-g', '*.ts', '-g', '*.tsx', '-g', '*.js', '-g', '*.jsx',
                    pattern, str(root),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            for raw in proc.stdout.splitlines():
                parts = raw.split(':', 2)
                if len(parts) != 3:
                    continue
                path, line, _ = parts
                return {
                    'file': _relative_repo_path(repo, Path(path)),
                    'function': symbol,
                    'line': int(line),
                    'evidence': 'rendered_component',
                }
        else:
            for path in root.rglob('*'):
                if path.suffix not in {'.ts', '.tsx', '.js', '.jsx'}:
                    continue
                try:
                    source = path.read_text(errors='replace')
                except OSError:
                    continue
                line = _named_function_line(source, symbol)
                if line:
                    return {
                        'file': _relative_repo_path(repo, path),
                        'function': symbol,
                        'line': line,
                        'evidence': 'rendered_component',
                    }
    return None


def trace_sentry_code_locations(
    repo: Path,
    facts: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Resolve Sentry routes to Next.js pages and preserve exact stack frames."""
    locations: List[Dict[str, Any]] = []
    for fact in facts[:3]:
        if not isinstance(fact, dict):
            continue
        transaction = str(fact.get('transaction') or '')
        page_file = _next_page_file(repo, transaction)
        page = None
        function_candidates: List[Dict[str, Any]] = []
        if page_file:
            try:
                source = page_file.read_text(errors='replace')
            except OSError:
                source = ''
            page_function, page_line = _default_page_function(source)
            page = {
                'file': _relative_repo_path(repo, page_file),
                'function': page_function,
                'line': page_line,
                'evidence': 'next_route_match',
            }
            for symbol in _rendered_local_symbols(source):
                definition = _symbol_definition(repo, symbol)
                if definition:
                    function_candidates.append(definition)
        stack_location = fact.get('stack_location')
        if isinstance(stack_location, dict):
            trace_status = 'exact_stack_frame'
        elif page:
            trace_status = 'route_and_component_only_stack_unavailable'
        else:
            trace_status = 'unresolved_stack_and_route_unavailable'
        locations.append({
            'issue_id': fact.get('issue_id'),
            'transaction': fact.get('transaction'),
            'page': page,
            'error_location': stack_location if isinstance(stack_location, dict) else None,
            'function_candidates': function_candidates[:4],
            'trace_status': trace_status,
        })
    return locations


def shutil_which(cmd: str) -> Optional[str]:
    for p in os.environ.get('PATH', '').split(os.pathsep):
        full = Path(p) / cmd
        if full.exists() and os.access(full, os.X_OK):
            return str(full)
    return None
