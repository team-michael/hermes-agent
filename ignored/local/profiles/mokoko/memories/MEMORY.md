사용자는 Notifly 엔지니어로 노션·Athena·DynamoDB 근거와 투명한 문제 해결을 선호함.
§
사용자는 미팅 메모를 ‘요약·배경·논의·후속’으로 구조화하고, 서비스 배경 조사와 기술적 제약을 명시하길 선호함.
§
User has set the 'Mokoko Bot' Notion page (ID: 3971f02665f1803995b7ef168097a253) as the default root page where the agent should create any new documents in the future.
§
사용자는 Notifly 설명에서 작은 멘탈 모델→실패 순서→메커니즘→구현을 선호하며, Notion에 명시된 설계와 현재 코드에서 도출한 구현 사실을 명확히 구분하길 원함. 관측·후보 식별·자동 감지·복구도 엄격히 구분하고, ‘발견 가능’에는 alarm/log query/수동 DB inventory 등 위치·방법·자동화 여부를 요구함. 상태 전이·장애 경계를 회귀 테스트로 검증하길 원함.
§
사용자는 설계·코드·배포 상태를 구분하고, 공유 builder는 Lambda/ECS/one-shot producer별 artifact와 production wire payload로 rollout을 검증하길 선호함. cutover 뒤 SQS SentTimestamp로 legacy 잔여를 구분하고, 개인정보 없는 집계와 partial rollout의 솔직한 공유를 기대함.
§
사용자는 AI Agent usage를 완료된 14일 KST 기준 대시보드·일별·프로젝트/모델/MCP·Top4 대화·Raw 탭으로 선호함.
§
사용자는 ID·스키마·시스템 정보 확인 시 코드 검색보다 DynamoDB/DB를 직접 조회해 메커니즘을 검증하길 선호함.
§
Notifly 조회는 고객사↔UUID/해시 project ID를 먼저 매핑하며, PG 접속 변수는 RDS_*가 아니라 POSTGRES_*로 주입됨.
§
사용자는 유료 외부 API를 도입·차용할 때 실제 credential·호출 경로·운영 사용량을 검증하고, 요청 제한뿐 아니라 과금 기준(예: 월간 처리 문자량) 기반의 비용 상한을 두길 원함.
§
GitHub PR Assignee는 `TheClevers`. 사용자는 합의 범위만 최소 변경하며, push 전 remote head·새 커밋·force-push actor를 확인해 타인 변경을 덮어쓰지 않길 원함. 작업 branch가 타인에게 force-push·재사용되면 되돌려 덮지 않고 최신 main에서 새 branch/PR을 만들며, 지정된 Linear parent 아래 하위 이슈를 생성해 PR과 상호 링크하는 방식을 선호함.
§
사용자는 Notifly MCP 문서에서 ChatGPT 데스크톱 앱·웹·Codex·Claude 설정을 구분하길 원함. 데스크톱은 MCP server Restart, 웹은 Developer Mode/Plugins Refresh 흐름을 별도 섹션으로 설명하고, 연결 가이드는 기능·예시 프롬프트/응답보다 설치·인증·도구 갱신에 집중하길 선호함. 도구 변경 중에는 게시형 App보다 live Custom MCP를 선호하며 스크린샷은 연결 폼 1장으로 충분하다고 봄.
§
사용자는 캠페인 locale을 request→view_state→activation adapter→project별 PG materialization으로 검증함. Draft는 localized를 view_state에만 저장하고 활성화 시 locale별 변환하며, UI는 ‘언어 추가’ 버튼→하단 검색·선택 창과 default 기반 빈 필드 일괄 번역(기존 입력 보존)을 선호함.
§
사용자는 DB read routing을 함수·파일의 인접성이 아니라 같은 데이터에 대한 실제 read-after-write 호출 관계로 판정하고, 결합이 없으면 전용 reader를 쓰는 방식을 선호함.
§
사용자는 ID·중복 방어에서 계층·유일성 범위를 엄격히 구분함: 여정↔노드, SQS chunk↔recipient_list↔recipient, 사용자 ID↔논리적 발송 ID.
§
사용자는 MCP 생성 도구에서 정적 input schema뿐 아니라 사전 describe 도구로 시나리오별 완성 payload를 안내하고, campaign·user journey의 일관성을 중시함.