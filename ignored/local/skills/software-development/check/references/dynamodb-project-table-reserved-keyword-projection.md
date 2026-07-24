# DynamoDB `project` table — reserved keyword in `ProjectionExpression`

## Problem

When mapping a `project_id` to product/name via the DynamoDB `project` table
(per the "DynamoDB project mapping rule" in SKILL.md), a naive projection like:

```python
t.get_item(
    Key={'id': project_id},
    ProjectionExpression='id, product_id, name, dev, plan',
)
```

raises:

```
botocore.exceptions.ClientError: An error occurred (ValidationException) when
calling the GetItem operation: Invalid ProjectionExpression: Attribute name is
a reserved keyword; reserved keyword: plan
```

`name` is also a DynamoDB reserved keyword and will fail the same way if
`plan` is removed but `name` is left unaliased.

## Fix

Alias every reserved-keyword attribute through `ExpressionAttributeNames`, or
just drop non-essential reserved-keyword fields from the projection:

```python
resp = t.get_item(
    Key={'id': project_id},
    ProjectionExpression='id, product_id, #n, dev',
    ExpressionAttributeNames={'#n': 'name'},
)
item = resp.get('Item')
# {'dev': False, 'id': '<project_id>', 'name': '<product name>', 'product_id': '<slug>'}
```

`dev: False` on the returned item confirms the project is a real
production/customer project, not an internal test project (project names
starting with `notifly-`, slug `michael`, or `console-stage.notifly.tech` are
internal — see the internal-testing-scope note in memory/SKILL.md). Use this
same minimal-projection pattern whenever you need a fast dev/prod check during
scope attribution instead of debugging the full DynamoDB reserved-word list
mid-triage.

## When this matters operationally

This came up while confirming that a project surfaced by `logs.current_error_details`
(e.g. `regather` / `b57754a9497a545ab9b0e4aadd6f53b6`) triggering a `/track-event`
401 flood was a real paying customer project (`dev: False`) rather than an
internal test tenant — which changed the classification from `no_action` to
`needs_fix` in the final Slack answer.
