# execute_code / terminal .env Credential Loading

## Problem

Both `execute_code` and `terminal` tools do not auto-load Hermes `.env` files. AWS credentials in `~/.hermes/profiles/hashimoto/.env` (or `~/.hermes/.env`) are not sourced into the tool sandbox environment. boto3 then falls back to ambient EC2 instance metadata credentials (`EC2CloudWatchAgentRole`), which typically lacks `cloudwatch:DescribeAlarms`, `logs:FilterLogEvents`, `dynamodb:Query`, and other read APIs — causing `AccessDenied` errors.

## Fix — explicit .env loading

Always load `.env` explicitly before constructing any boto3 client in `execute_code`:

```python
env_path = '/home/ubuntu/.hermes/profiles/hashimoto/.env'
aws_vars = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line.startswith('AWS_') and '=' in line:
            key, val = line.split('=', 1)
            aws_vars[key] = val

cw = boto3.client('cloudwatch',
    region_name=aws_vars.get('AWS_DEFAULT_REGION', 'ap-northeast-2'),
    aws_access_key_id=aws_vars['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=aws_vars['AWS_SECRET_ACCESS_KEY'],
)
```

This pattern is required for ALL AWS service clients (cloudwatch, logs, sqs, dynamodb, rds, pi, etc.) when called via `execute_code` or `terminal` Python scripts.

## Helper script absence fallback

When `scripts/collect_notifly_alert_context.py` is not present in the profile-local skill copy (`~/.hermes/profiles/hashimoto/skills/software-development/check/scripts/`), use direct boto3 calls with the explicit credential loading pattern above.

For bracket-prefix alarm names (e.g., `[api-service] 4xx error response is greater than 300 in 5m`):

- `--alarm-names` and `--alarm-name` fail because the leading `[` is parsed as JSON array syntax
- `AlarmNamePrefix` also fails because prefix matching is literal and the bracket is the first character
- Use `paginator` + client-side substring filter instead:

```python
paginator = cw.get_paginator('describe_alarms')
all_alarms = []
for page in paginator.paginate(AlarmTypes=['MetricAlarm']):
    all_alarms.extend(page.get('MetricAlarms', []))
matching = [a for a in all_alarms if 'api-service' in a['AlarmName'] and '4xx' in a['AlarmName'].lower()]
```

## Verification

To confirm which credentials boto3 is actually using:

```python
import boto3.session
session = boto3.session.Session()
creds = session.get_credentials()
print(f"Credential type: {type(creds).__name__}")
print(f"Method: {creds.method}" if hasattr(creds, 'method') else "No method attr")
# 'iam-role' or 'RefreshableCredentials' = EC2 instance metadata fallback (wrong)
# 'env' or explicit keys = .env loaded correctly
```

## `HOME` override pitfall — `~` expansion breaks in profile-isolated sessions

In Hermes profile-isolated sessions, the `HOME` environment variable is set to a profile-specific subdirectory (e.g., `HOME=/home/ubuntu/.hermes/profiles/hashimoto/home`), not the real user home (`/home/ubuntu`). This causes `os.path.expanduser("~/.hermes/...")` to resolve to a nonsensical path like `/home/ubuntu/.hermes/profiles/hashimoto/home/.hermes/profiles/hashimoto/.env`, resulting in `FileNotFoundError`.

**Never use `~` or `os.path.expanduser` for Hermes `.env` paths in inline Python scripts.** Always use the absolute path directly:

```python
# WRONG — HOME override breaks tilde expansion
env_path = os.path.expanduser("~/.hermes/profiles/hashimoto/.env")

# RIGHT — absolute path is immune to HOME override
env_path = "/home/ubuntu/.hermes/profiles/hashimoto/.env"
```

The `HERMES_HOME` environment variable (`/home/ubuntu/.hermes/profiles/hashimoto`) can also be used as a base, but the absolute path is the most reliable form for inline scripts.

## Session history

- 2026-06-22: `execute_code` boto3 calls failed with `AccessDenied` on `cloudwatch:DescribeAlarms` because `.env` was not loaded. boto3 used `EC2CloudWatchAgentRole` from EC2 instance metadata. Fix: explicit `.env` parsing + credential passing. After fix, all CloudWatch/Logs Insights calls succeeded.
- 2026-06-23: Inline Python script in `terminal` used `os.path.expanduser("~/.hermes/...")` which resolved to `/home/ubuntu/.hermes/profiles/hashimoto/home/.hermes/...` due to `HOME=/home/ubuntu/.hermes/profiles/hashimoto/home`. Fix: use absolute path `/home/ubuntu/.hermes/profiles/hashimoto/.env` directly.
