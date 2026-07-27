# RDS VolumeReadIOPs Scope Attribution via Performance Insights

When investigating `VolumeReadIOPs` or `CPUUtilization` alarms on Aurora, the CloudWatch helper script may not always resolve a specific `project_id` or `campaign_id` from the metric alone.

## Pattern: PI Table Reference Extraction

If the helper output contains `rds_performance_insights`, check the `top_sql` entries.

1. **Identify `table_refs`**: Look for `table_refs` within the `top_sql` objects.
2. **Extract `project_id`**: The `table_pattern` (e.g., `users_<project_id>`) or a direct `project_id` field in the reference provides the most direct link to the workload.
3. **Map via DynamoDB**: Use the extracted `project_id` to query the `project` table to resolve the product name and human-readable project name.
4. **Verify with SQL**: If the `project_id` is found, you can often bypass broad `SELECT *` queries and instead target the specific sharded table (e.g., `SELECT count(*) FROM users_32d8d9d6294d52e7a5427c036b471f91`) to verify the load.

This method is significantly more reliable than attempting to resolve scope from unstructured log lines or generic RDS metric dimensions.
