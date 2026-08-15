사용자는 08:00 Daily Breef(5분 훑기+필수 원문, 총 30분 이내)와 같은 Slack 스레드의 08:05 한국어 팟캐스트(5~10분)·정리본·Q&A를 선호한다. 자연스러운 음성, 실제 사례, A/B 근거를 중시한다.
§
사용자는 짧은 목록형 답변을 선호한다. 오래 걸리면 시작과 검증 결과를 나눠 받길 원한다. Standup 순서는 컨디션, 어제, 오늘, blocker이며 항목은 가능하면 영어 `[분류] 내용` 형식이다.
§
Slack DM 새 세션의 첫 루트 메시지는 제목 전용이라 답하지 않고, 하위 스레드의 다음 메시지부터 답한다. 채널은 `@haro`로 호출한 첫 질문부터 답한다.
§
사용자는 운영·인프라 검증에서 개념보다 실제 리소스와 명령·쿼리를 먼저 보고, 집계 지표와 tenant 증거를 구분하며 메시징은 Queue/consumer 경계의 실제 저장·전달 속성을 중시한다.
§
사용자는 기능 PR과 Dashboard/IaC PR을 분리하되, 이메일 대량 발송 관측은 기존 `Email_Circuit_Breaker_Dashboard`에 통합하길 선호한다. 범위는 project별 발송량, MessageGroupId, Fair Queue, Queue/Lambda/DLQ, SES 지표다.
§
GitHub PR 생성 시 assignee를 `intersoom`(Soomin Lee)으로 설정하는 것을 선호한다.
§
Slack manifest는 `slack-manifest-agent-reactions-minimal.json` 기준 최소 변경한다. 기존 앱·메시징, `agent_view`, `assistant:write`, Agent 이벤트, user `reactions:write`를 유지하고 요청 없으면 `slash_commands`·bot `commands`를 추가하지 않는다.
§
사용자는 Git/PR 작업에서 진행 설명보다 깨끗한 작업공간의 빠른 실행·검증된 결과를 선호한다. CodeRabbit 의견은 선별 반영하고, 미반영 사유 댓글 후 review thread를 resolve하길 원한다.
§
사용자는 웹 URL 확인 시 브라우저나 검색보다 `curl` 직접 요청을 항상 먼저 시도하길 선호한다.
§
일정은 작업을 순차·배타적으로만 배치하지 않는다. `아티클 읽기`와 `계정 모니터링`은 매일 유지하며 핵심 작업과 병행하거나 틈에 수행하고 임의로 보류하지 않는다.
§
백필은 실패 group의 project/entity를 산출해 project별 selected workflow로 실행한다. `entity_ids`는 실제 entity ID이며, 완료는 Step Functions가 아니라 Glue run·DB 결과로 검증한다.