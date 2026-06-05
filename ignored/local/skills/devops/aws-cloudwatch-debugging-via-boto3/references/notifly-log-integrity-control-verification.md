# Notifly log integrity / tamper-resistance control verification

Use this reference when answering partner/security-audit questions about whether log integrity controls are actually implemented, especially claims such as “Lambda-based automatic integrity verification is planned/implemented”, “CloudWatch Logs immutable”, “S3 Versioning”, “Object Lock”, or CloudTrail validation.

## Goal

Do not repeat planned-control language as fact. Verify the live control plane and IaC first, then state whether the control is **implemented**, **partially covered by adjacent controls**, or **not currently evidenced**.

## Minimal evidence chain

1. **Repository/IaC check**
   - Search the current source-of-truth repo, preferably `origin/main`, for:
     - `integrity`, `tamper`, `checksum`, `verify`, `verifier`
     - `object_lock`, `object lock`, `versioning`
     - `lambda.*integrity`, `integrity.*lambda`, `log.*integrity`, `cloudwatch.*checksum`
   - In Notifly, default source is `team-michael/notifly-event`, especially `infra/terraform/prod/ap-northeast-2`.

2. **Lambda inventory**
   - List Lambda functions across active regions, not just the current default region.
   - Keyword-match function name and description for integrity/tamper/checksum/verify/audit/log terms.
   - A generic logging Lambda is not evidence of log integrity verification unless its code/name/description and schedule show that purpose.

3. **Scheduler / EventBridge trigger check**
   - Inspect both classic EventBridge rules and EventBridge Scheduler.
   - For each scheduled rule with Lambda targets, inspect target Lambda names.
   - Absence of a schedule is strong evidence that a “regular automatic check” is not operating.

4. **CloudWatch Logs subscription/export check**
   - Inspect subscription filters on relevant log groups to see whether logs are routed to a verifier Lambda/Kinesis/Firehose path.
   - Check recent CloudWatch Logs export tasks only as supporting evidence; export tasks alone are not integrity verification.

5. **CloudTrail validation**
   - Inspect trails and `LogFileValidationEnabled`.
   - CloudTrail management-event logging is not the same as application access-log integrity verification.

6. **S3 retention/tamper-resistance controls**
   - For log-like buckets, inspect:
     - `get_bucket_versioning`
     - `get_object_lock_configuration`
     - lifecycle rules if retention is claimed
   - Versioning disabled + Object Lock not configured means the S3 bucket is not immutable in the WORM sense, even if access is restricted and encrypted.

## Interpretation pattern

- **Implemented**: IaC/code + live Lambda + scheduled trigger/subscription + output/alert evidence all align.
- **Partial / adjacent controls only**: logs are stored, encrypted, access-controlled, monitored, or retained, but no independent integrity verifier exists.
- **Not evidenced**: no IaC/code/live Lambda/schedule/subscription/CloudTrail validation/Object Lock evidence.

## Partner-facing wording pattern

When no Lambda integrity verifier is found, avoid saying it was implemented. Use language like:

> 접속기록 및 주요 시스템 로그는 CloudWatch Logs, S3/Athena 등 클라우드 로그 저장소를 통해 보관하고 있으며, IAM 권한통제, 암호화, 접근제어를 적용하여 임의 접근 및 변경을 제한하고 있습니다. 다만 별도 Lambda 기반의 정기 무결성 자동 검증 체계는 현재 수립 완료 상태로 확인되지 않아, 추가 구축 예정입니다.

If the reviewer specifically asked whether a planned Q4 control exists, answer directly:

> Lambda 기반 자동 무결성 검증 체계는 현재 운영 중인 체계로 확인되지 않으며, 향후 개선 과제로 관리하고 있습니다.

## Pitfalls

- Do not treat CloudWatch Logs retention or S3 encryption as immutable storage.
- Do not treat S3 Versioning as present because Terraform has a versioning resource; inspect each bucket’s actual configured status.
- Do not treat CloudTrail `describe_trails` existence as log-file integrity validation; check `LogFileValidationEnabled` explicitly.
- Do not cite internal account IDs, bucket names, Lambda names, or repo paths in external partner-facing text unless the user explicitly wants internal evidence.
