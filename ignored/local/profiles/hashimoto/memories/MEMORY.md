Notifly AWS default region is ap-northeast-2; primary account ID observed in alerts is 702197142747.
§
CloudWatch alarm responses use `[[hermes:processing_status=no_action]]` for false positives or recovered spikes, `[[hermes:processing_status=needs_fix]]` for non-urgent engineering work, and `[[hermes:processing_status=urgent]]` only for active outages requiring immediate @engineers escalation.
§
Terminal subprocesses may intentionally strip messaging secrets such as SLACK_BOT_TOKEN from ambient os.environ; when the profile .env contains the key but os.getenv returns empty, read the target .env file explicitly from collection scripts.
