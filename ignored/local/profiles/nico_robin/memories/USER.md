호칭: 경서님(Jaden); '경우' 금지.
GitHub: ConvCommits; clix-so-bot; human reviewer는 지명 시만; codebase>bot; PR goal 유지.
§
Remote/API validation: live target/config/code/data 증거 우선; 통합 장애는 제품 수정·재배포/추측 전에 격리 API probe로 status/body 확보. 변경 코드/TC는 처음부터 재검증. 수동 rerun/requeue/resend/recovery/live send는 승인 필수; 수신자 정확히 검증. Deploy monitoring=logs/alarms/queues/metrics.
§
Notifly RCA: terse KR/current case; 원인은 live logs/data로 증명. 상관·로그부재=추론; observed≠inferred. 서버/데이터/시점 후 SDK 판단; signOut/deleteToken은 timestamp 필수; FCM404≠401.
§
DM infra explanations: tailor to Mobile/iOS+SDK Eng; only matching analogies; flag SDK contract/retry/offline/telemetry/DX implications. Persona/app descriptions: broad core-engineering > overly SDK-specific.
§
Slack: KR terse/no tables. 링크/채널 이력은 API/helper 우선; browser/tool 부재≠접근불가. scope/token/member/runtime 구분; missing_scope 없이 reinstall 금지. not_in_channel=봇 초대; 첨부 확인.
§
Vendor/MSP tickets: no internal refs; cause-only/minimal; paste-ready plain text, no code fences.
§
BDM: source-only; facts≠estimates; playbook 로드. Linear·Google·Trackit 등 외부 변경은 명시된 범위만 실행; 검토·모호한 표현을 승인으로 간주하지 않음.
§
Docs/specs: KR humanized; requested contract만 작성—임의 wrapper/활용법/한계 금지. 고객 API 명칭에 내부·provider 용어 금지. 사실≠추론. 필드 매트릭스는 Sheets 선호; 후속 단계 컬럼은 미리 만들되 요청 전 값은 비움.
§
GFSA 외부심사용 문서는 내부 ID/PR/티켓/SHA/Slack 링크를 빼고, 기능·KR 진행률·근거만 간결히 쓴다.