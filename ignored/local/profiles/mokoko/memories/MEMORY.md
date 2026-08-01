사용자는 Notifly 엔지니어이며 근거 기반·실관측 문제 해결을 선호함. 개인 결제 재현은 `notifly-kokomo`에서 실제 Payple·DDB 영향을 확인함.
§
사용자는 미팅 메모를 ‘요약·배경·논의·후속’으로 구조화하고, 서비스 배경 조사와 기술적 제약을 명시하길 선호함.
§
User has set the 'Mokoko Bot' Notion page (ID: 3971f02665f1803995b7ef168097a253) as the default root page where the agent should create any new documents in the future.
§
사용자는 멱등성 경계를 분리함. Brand provider 멱등성은 delivery retry용이며 Poller 결과 재조회 복구의 선행조건이 아님. stable ID·atomic claim·collision fail-closed·PREPARED→SENDING→UNKNOWN(no-resend)을 요구하고 exactly-once 과설계를 경계함. Poller DDB는 불변 PAYLOAD/가변 STATE를 별도 item으로 두고 PAYLOAD 1회 저장·STATE UpdateItem을 우선함(같은 item 부분 update는 불충분).
§
사용자는 설계·코드·배포·실관측 상태를 구분하며, 운영 이슈는 live mapping/DB/metric으로 ‘현재 발생’과 ‘잠재 결함’을 나눠 답하길 원함. 공유 builder는 Lambda/ECS/one-shot producer별 artifact와 production wire payload로 rollout을 검증하고, cutover 뒤 SQS SentTimestamp로 legacy 잔여를 구분하며 개인정보 없는 집계와 P1 blocker를 솔직히 공유하고 미해결 시 Draft PR을 선호함.
§
사용자는 AI Agent usage를 완료된 14일 KST 기준 대시보드·일별·프로젝트/모델/MCP·Top4 대화·Raw 탭으로 선호함.
§
사용자는 ID·스키마·시스템 정보 확인 시 코드 검색보다 DynamoDB/DB를 직접 조회해 메커니즘을 검증하길 선호함.
§
Notifly 조회는 고객사↔UUID/해시 project ID를 먼저 매핑하며, PG 접속 변수는 RDS_*가 아니라 POSTGRES_*로 주입됨.
§
사용자는 결제·유료 provider 변경 시 실제 credential·호출·과금과 stage의 prod 자원 공유 여부를 확인하고, 최종 SHA를 stage 실경로 검증 후 prod 배포하길 원함.
§
GitHub PR Assignee는 `TheClevers`. 사용자는 합의 범위만 최소 변경하고 push 전 remote head를 확인하며 타인 force-push를 덮지 않길 원함. 폐기한 구현은 미병합 PR 종료에 그치지 않고 병합 코드·Terraform 리소스까지 안전하게 되돌려 정리하길 원함. Linear 이슈는 본인에게 배정하고 PR과 상호 링크하길 선호함.
§
사용자는 Notifly MCP 연결 문서에서 ChatGPT 데스크톱·웹·Codex·Claude 설정을 구분하고 설치·인증·도구 갱신에 집중하길 원함. 변경 중엔 게시 App보다 live Custom MCP를 선호하며 연결 폼 스크린샷 1장이면 충분하다고 봄.
§
사용자는 캠페인 locale을 request→view_state→activation adapter→project별 PG materialization으로 검증함. Draft는 localized를 view_state에만 저장하고 활성화 시 locale별 변환하며, UI는 ‘언어 추가’ 버튼→하단 검색·선택 창과 default 기반 빈 필드 일괄 번역(기존 입력 보존)을 선호함.
§
사용자는 DB read routing을 함수·파일의 인접성이 아니라 같은 데이터에 대한 실제 read-after-write 호출 관계로 판정하고, 결합이 없으면 전용 reader를 쓰는 방식을 선호함.
§
사용자는 MCP 입력 계약(timezone·형식·경계)을 tool/parameter description에, 반환 timezone·조건부 freshness(응답에 없음↔도구 미제공)·빈 결과 해석과 totals↔top_resources 구분을 outputSchema field에도 노출하길 원함. 비유도 prompt로 args/raw result를 검증하며 불가능한 성공은 preview SHA·MCP URL·도구 재발견을 확인함.