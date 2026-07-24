# Clix CloudWatch Read-Only Access Pattern

Use this reference when the user asks what AWS permissions the agent should have for Clix observability/debugging.

## Session finding

For `clix-so/clix`, infrastructure is managed under:

- `infra/terraform/prod/global/common/iam/`
- GitHub Actions workflows under `.github/workflows/`

The existing role:

```text
clix-github-oidc-build-and-deploy
```

is assumed by GitHub Actions through OIDC and has AWS managed policy:

```text
AdministratorAccess
```

which expands to:

```json
{"Effect":"Allow","Action":"*","Resource":"*"}
```

So it is not appropriate for routine agent CloudWatch investigation.

## Desired access

The user wants the agent to have **Clix AWS CloudWatch read-only access only**, not broad admin/operator access.

Prefer a separate role such as:

```text
clix-hermes-cloudwatch-readonly
```

Attach only:

```text
CloudWatchReadOnlyAccess
CloudWatchLogsReadOnlyAccess
```

Optionally add `AWSXRayReadOnlyAccess` only if traces are explicitly needed.

## Recommended Terraform shape

```hcl
resource "aws_iam_role" "hermes_cloudwatch_readonly" {
  name = "clix-hermes-cloudwatch-readonly"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = "arn:aws:iam::702197142747:user/notifly-internal-agent"
        }
      }
    ]
  })

  tags = local.default_tags
}

resource "aws_iam_role_policy_attachment" "hermes_cloudwatch_readonly_cloudwatch" {
  role       = aws_iam_role.hermes_cloudwatch_readonly.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "hermes_cloudwatch_readonly_logs" {
  role       = aws_iam_role.hermes_cloudwatch_readonly.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsReadOnlyAccess"
}
```

If possible, add an `ExternalId` condition to the trust policy.

## Cross-account gotcha

A target-account role trust policy is only half of cross-account access. The source principal also needs an identity policy allowing:

```json
{
  "Effect": "Allow",
  "Action": "sts:AssumeRole",
  "Resource": "arn:aws:iam::<CLIX_ACCOUNT_ID>:role/clix-hermes-cloudwatch-readonly"
}
```

## Investigation behavior

When investigating Clix CloudWatch after this access exists:

1. Assume the read-only role first.
2. Confirm identity with `sts get-caller-identity`.
3. Use CloudWatch/CloudWatch Logs read APIs only.
4. Do not use the existing `clix-github-oidc-build-and-deploy` admin role for routine observability unless the user explicitly approves that broader path.
