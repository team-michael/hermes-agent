# Notifly AWS Chatbot custom actions

Use when investigating or extending Slack `#monitoring` / `#incidents` buttons such as `Run query` on AWS-originated notifications.

## Key mechanism

AWS Chatbot / Amazon Q Developer custom actions are responsible for the button and the thread reply:

1. AWS service notification or custom notification is delivered to Slack through AWS Chatbot.
2. Custom action button invokes a configured action target: CLI command, SSM Automation, or Lambda.
3. For Lambda actions, the Lambda receives a JSON payload containing variables extracted from the notification.
4. The Lambda returns text, usually `{ statusCode: 200, body: "..." }` in Notifly's worker.
5. AWS Chatbot posts the returned body back to the original Slack message thread.

Do not look for Slack Web API calls in the worker for the thread reply; the worker only returns text.

## Notifly implementation evidence

Repo path: `services/lambda/aws-chatbot-custom-action-worker`.

- `index.js` routes payload combinations.
- `metricAlarmName + timestamp` calls `fetchCloudWatchLogs(event)`.
- `lib/cloudwatch.js` fetches CloudWatch log events or Logs Insights results and returns a formatted string.

Existing live Slack channel configuration can be inspected with:

```bash
aws chatbot describe-slack-channel-configurations --region us-east-2 --output json --no-cli-pager
aws chatbot list-custom-actions --region us-east-2 --output json --no-cli-pager
```

AWS Chatbot API is not available in every region; use an AWS Chatbot-supported control-plane region such as `us-east-2` when the ap-northeast-2 endpoint fails.

## Extending the pattern

To add another button on a Chatbot-delivered message:

1. Ensure the message is delivered by AWS Chatbot, not Slack Incoming Webhook.
2. If it is a custom app/report message, publish an AWS Chatbot custom notification to the SNS topic wired to the target channel.
3. Put action variables under `metadata.additionalContext` and set `metadata.enableCustomActions = true`.
4. Create/update a Chatbot custom action with attachment criteria matching the notification variable, e.g. `reportType == ai-agent-usage`.
5. Configure the action payload to pass variables to Lambda, e.g. `{ "action": "aiAgentUsageAthena", "targetDate": "$targetDate" }`.
6. Add a narrow route in `aws-chatbot-custom-action-worker` for the new action.
7. Verify Lambda role permissions and timeout for the downstream data source.

## Pitfall

Slack webhook messages cannot receive AWS Chatbot custom-action buttons. If the user asks for “same as Run query button,” first move the notification path to SNS → AWS Chatbot or choose a separate Slack App interactivity implementation.
