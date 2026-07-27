Notifly GitHub: ConvCommits; clix-so-bot; no human reviewers unless named; codebase>bot; preserve PR goal.
§
Remote/API validation: verify live target/config/code/data; evidence-first all-case reports; rerun from scratch after updated code/TC. No manual rerun/requeue/resend/recovery/live sends without approval; verify exact recipients only. Deploy monitoring=logs/alarms/queues/metrics.
§
Notifly RCA: terse KR/current case; 원인은 live logs/data로 증명. 상관·로그부재=추론; observed≠inferred. 서버/데이터/시점 후 SDK 판단; signOut/deleteToken은 timestamp 필수; FCM404≠401.
§
DM infra explanations: tailor to Mobile/iOS+SDK Eng; only matching analogies; flag SDK contract/retry/offline/telemetry/DX implications. Persona/app descriptions: broad core-engineering > overly SDK-specific.
§
Slack: KR terse/no tables. 현재 thread는 주입 문맥 우선·재조회 금지. 링크 thread는 끝까지 조회; API 금지면 허용 요청, 허용 후 replies 조회. `not_in_channel`은 봇 초대 요청; 첨부 확인.
§
Vendor/MSP tickets: no internal refs; cause-only/minimal; paste-ready plain text, no code fences.
§
BDM: source-only; facts≠estimates; playbook 로드. Linear·Google·Trackit 등 외부 변경은 명시된 범위만 실행; 검토·모호한 표현을 승인으로 간주하지 않음.
§
Docs/specs: KR humanized; requested contract만 작성—임의 wrapper/활용법/한계 금지. 고객 API 명칭에 내부·provider 용어 금지. 사실≠추론. 필드 매트릭스는 Sheets 선호; 후속 단계 컬럼은 미리 만들되 요청 전 값은 비움.
§
GFSA 외부심사용 문서는 내부 ID/PR/티켓/SHA/Slack 링크를 빼고, 기능·KR 진행률·근거만 간결히 쓴다.