For the andrej Hermes profile, Slack credentials are stored in /home/ubuntu/.hermes/profiles/andrej/.env; terminal subprocesses intentionally strip messaging secrets such as SLACK_BOT_TOKEN from ambient os.environ unless explicitly loaded or allowlisted.
§
Notifly project lookup convention: when a `project_id` is found, map it through the DynamoDB `project` table and include the corresponding product_id/name; PostgreSQL per-project tables follow the `table_name_${project_id}` naming pattern.
§
Notifly analytics Athena defaults: region `ap-northeast-2`, workgroup `primary`, database `notifly_analytics`, result output `s3://raw-events-query-logs/athena-query-results/`; key tables include `notifly_event_logs` and `notifly_message_events`, commonly filtered by `dt`, `h`, `project_id`, and `pre_conversion`.
§
For `team-michael/notifly-event` web-console work, new or changed user-facing messages should follow the existing i18n/locale pattern instead of hardcoded strings.
§
For Slack image/attachment questions, do not infer from text-only thread context that media is inaccessible; when channel_id/thread_ts are available, retrieve the Slack thread/root via Web API, inspect `messages[0].files[]`/attachments, download authorized images, and use vision analysis.
§
Hermes local patches for this profile historically used branch `local/hermes-patches` with `update.local_patch_branch`; after `hermes update`, local patch changes may need to be checked out, rebased, or reapplied on top of updated main.
§
Git commit identity used in prior Notifly agent work: `Andrej Karpathy <team@greyboxhq.com>`.
§
For `team-michael/cloudflare-containers` Access-protected endpoints, Cloudflare Access service-token headers `cf-access-client-id` and `cf-access-client-secret` can be used when available; their values are secrets and should not be stored or printed.