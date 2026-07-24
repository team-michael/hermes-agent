# Sentry delivery-result query timeout pattern

Session note for the `web-console/sentry alert` family.

## Trigger shape

A Sentry email alert may report a `Query read timeout` from a `web-console` issue whose SQL mentions a sharded table such as:

- `delivery_result_<project_id>`
- `message_events_<project_id>`
- `users_<project_id>`

The alert is still routed through the Sentry email proxy (`/aws/ecs/notifly-services-prod/web-console/sentry`) and therefore trips the broad `%ERROR%` metric filter intentionally.

## What mattered in this session

- The **current alarm-window** trigger was the source of truth, not the broader 7d/30d Sentry mix.
- `current_error_details` carried the concrete SQL fingerprint, including the `Query read timeout` text.
- `table_refs` from the same current trigger were enough to recover project scope even when top-level `project_ids` were empty.
- For this family, report the exact sharded table suffix in the root-cause line and map the suffix’s `project_id` through DynamoDB `project` before deciding whether scope is known.

## Practical reminder

When the issue payload contains both a Sentry `project.id` and a Notifly API path like `/api/projects/<projectId>/...`, only the Notifly project path is relevant for scope. The Sentry project ID is a different namespace and should not be mapped through DynamoDB.