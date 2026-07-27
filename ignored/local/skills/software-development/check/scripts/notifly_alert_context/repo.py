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

def shutil_which(cmd: str) -> Optional[str]:
    for p in os.environ.get('PATH', '').split(os.pathsep):
        full = Path(p) / cmd
        if full.exists() and os.access(full, os.X_OK):
            return str(full)
    return None
