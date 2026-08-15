문서: 사고는 Draft에 사실만, 미확정=‘작성 필요’; 복구=Timeline, 조치=강제형. Tech spec은 1pager로 짧게 쓰고 append 대신 재조립. 구현은 내부 checkpoint로 연속 진행하고 권한·credential만 요청.
§
설계·코드·배포·실관측 구분. tenant DDL=RO→canary→전체. create_tables CI=PG16.11 base/merge diff↔DDB project·prod catalog. 검증은 test tenant 하나에 probe 컬럼만 적용해 나머지 mismatch 실패 확인. 비-required; 전용 PG role 전엔 기존 read-only+timeout·catalog-only.
§
Notifly 조회는 고객↔project 먼저 매핑. DDB 부재는 Git·offboarding 확인. 수동 차단은 blame·live activity 확인. SDK 공개 경로는 API key를 가정하지 않고 middleware→tenant binding→shard ID를 추적. PG 변수는 POSTGRES_*.
§
Payple 접근 정책: 공유 키 O(n) scan·명시적 race. 확정 무효만 web-console 7일 유예 후 차단, 미확인 오류는 영구 fail-open·marker 유지. 저장 후 transient는 0/1/3/10초 status-only 재확인하며 key 재발급 금지. blocked-origin 잠금은 blocked 관측이 아니라 사용자가 recovery를 시작한 때부터 유지함.
§
PR Assignee `TheClevers`; 인증≠commit author. 최소 변경·remote head·타인 변경 비덮기 선호. 코드 변경의 ‘커밋’ 요청은 원격 branch push까지 포함함. 리뷰어 확인→답변·resolve·재검토하며 push 직후 CI 대기 없이 알림. Linear는 작업별 새 이슈를 본인 할당하고 관련 없는 parent/subissue 연결 금지.
§
사용자는 Notifly MCP 연결 문서에서 ChatGPT 데스크톱·웹·Codex·Claude 설정을 구분하고 설치·인증·도구 갱신에 집중하길 원함. 변경 중엔 게시 App보다 live Custom MCP를 선호하며 연결 폼 스크린샷 1장이면 충분하다고 봄.
§
Locale: Console=`zh-CN`/`zh-TW`; 원문 보존. WireBarley `lang`에만 `zh→zh-CN`, `zh-Hant→zh-TW` 하드코딩; `$locale`·device 미적용, `lang` 제거 시 삭제. 장기=SDK 수집+$locale override. BCP47 유효성≠key 매칭. 출처는 분포 추정 후 고객 코드·payload로 확정.
§
User SoT=`users_*`(encrypted). Read=`executeUserQuery`; `user_*` shadow 복원 금지.
§
장애는 stack만으로 수동 요청을 단정하지 않고 정상 UI·Cloudflare와 대조. 보안은 credential≠tenant binding, 기존 취약점≠PR 확장.
§
Schema CI: merge 전 prod test tenant probe→나머지 mismatch 실패→복구. tenant/global 독립 check, 둘 다 변경 시 둘 다; tenant 실검증 후 global 구현.
§
Kakao Direct: Brand v2 result·Alimtalk responseAll은 본문 미반환. Event Export success `message_data`는 발송시점 전문 snapshot. Alimtalk는 기존 outbound `raw_request_body`를 Poller terminal에서 gzip+base64로 붙여 SQS·DDB 중복을 피하고 Kinesis·S3 증가만 허용; Brand는 template detail+수신자 변수로 재구성. Exporter는 압축/평문 지원. Poll retry는 안전, failover·N resend는 멱등성 후 partial retry.
§
유저여정/API는 validation↔downstream 실패, helper 로직↔함수 이동을 분리. localized map은 default 필수·없을 때만 legacy message; runner→Web Console 배포.
§
사용자는 이벤트 필드 추가 전 SQS·DDB·PG·Kinesis·S3 전달 경로와 중복 저장·용량 부하를 먼저 확인하길 원함.