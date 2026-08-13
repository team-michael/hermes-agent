사용자는 오전 8시 우선순위형 Daily Breef(5분 훑기+필수 원문, 총 30분 이내)와 같은 Slack 스레드의 8시 5분 한국어 팟캐스트(5~10분)·정리본·후속 Q&A를 선호하며, 자연스러운 음성과 실제 사례·A/B 근거를 중시한다.
§
사용자는 짧은 목록형 답변을 선호한다. 오래 걸리는 작업은 시작을 먼저 알리고 검증 결과를 별도로 받길 원한다. Standup은 컨디션, 어제 한 일, 오늘 할 일, blocker 순서이며 항목은 가능하면 영어로 `[분류] 내용` 형식으로 쓴다.
§
사용자는 Slack 새 세션의 첫 루트 메시지를 형식과 무관하게 제목 전용으로 쓰고, Haro가 루트에는 아무 응답도 보내지 않은 채 같은 하위 스레드의 두 번째 사용자 메시지부터 답변하는 방식을 선호한다.
§
사용자는 인프라 검증에서 실제 리소스·활성화 메커니즘을 먼저 확인하고, 집계 지표와 tenant별 증거를 구분하길 선호한다.
§
사용자는 기능 PR과 Dashboard/IaC PR을 분리하되, 이메일 대량 발송 관측은 기존 `Email_Circuit_Breaker_Dashboard`에 통합하길 선호한다. 범위는 project별 발송량, MessageGroupId, Fair Queue, Queue/Lambda/DLQ, SES 지표다.
§
사용자는 운영 변경 검증 설명에서 개념이나 대시보드 제안보다 실제 값을 어디서 어떤 명령·쿼리로 확인하는지 먼저 제시받길 선호한다. 특히 메시징 변경은 producer 의도보다 Queue/consumer 경계에서 실제 저장·전달된 속성을 검증하는 방식을 중시한다.
§
GitHub PR 생성 시 assignee를 `intersoom`(Soomin Lee)으로 설정하는 것을 선호한다.
§
Slack manifest 변경 시 `slack-manifest-agent-reactions-minimal.json` 구성을 기준으로 최소 변경한다: 기존 앱·메시징 설정, `agent_view`, `assistant:write`, Agent 이벤트(`app_context_changed`, `app_home_opened`, `message.im`), user scope `reactions:write`는 유지하고, 별도 요청 없으면 `slash_commands`와 bot scope `commands`는 추가하지 않는다.
§
사용자는 Git/PR 작업에서 진행 설명보다 깨끗한 작업공간의 빠른 실행·검증된 결과를 선호한다. CodeRabbit 의견은 선별 반영하고, 미반영 사유 댓글 후 review thread를 resolve하길 원한다.
§
사용자는 웹 URL 확인 시 브라우저나 검색보다 `curl` 직접 요청을 항상 먼저 시도하길 선호한다.