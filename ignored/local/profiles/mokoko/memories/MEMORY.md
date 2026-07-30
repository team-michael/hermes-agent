사용자는 Notifly 엔지니어이며, 노션/Athena/DynamoDB 기반의 기술 리서치와 투명한 문제 해결을 선호함. '모험가' 단어 사용을 금지하며, 모코코 페르소나와 다양한 이모지(예: :shy_mokoko:) 사용을 즐기는 친구 같은 대화 방식을 원함. 이슈 시 솔직한 공유와 우회 방안 제시를 기대하며, 대화 로그 조회 시 필수 4개 필드만 요약 보고를 선호함.
§
사용자는 미팅 메모를 바탕으로 '요약, 배경, 논의, 후속' 4가지 카테고리로 구조화된 문서를 작성하는 것을 선호함. 또한 문서 작성 시 서비스에 대한 배경 조사를 포함하고, 기술적 상황(프론트엔드 리소스 부족 등)을 명확하게 명시하는 것을 중요하게 생각함.
§
사용자는 Notion API 기반의 프로젝트 자동화와 기술 문서화를 선호하며, 명시적으로 권한을 부여한 페이지를 작업 루트로 사용함.
§
User has set the 'Mokoko Bot' Notion page (ID: 3971f02665f1803995b7ef168097a253) as the default root page where the agent should create any new documents in the future.
§
사용자는 Notifly 기술 설명에서 작은 멘탈 모델→실패 순서→핵심 메커니즘→구현 순서를 선호하며, ‘관측됨’과 ‘복구·해결됨’을 엄격히 구분함. 변경 함수별 필요 이유·실제 상태 전이·장애 경계를 직접 재현하는 회귀 테스트로 주장을 검증하길 원함.
§
사용자는 배포 시스템(GitHub Actions/Cloudflare Workers)의 내부 로직, 동적 설정, URL 매핑 등의 기술적 메커니즘을 상세히 파악하고 직접 코드(yml, js 등)를 통해 검증하는 것을 선호함. 에이전트가 기술적 장벽 발생 시 상황을 투명하게 공유하고 직접적인 코드 근거를 제시하길 기대함.
§
사용자는 피드백을 정리할 때 표(Table) 형식을 선호하며, 각 고객사별로 핵심 내용을 구조화하여 보여주는 것을 좋아함.
§
사용자는 ID·스키마·시스템 정보 확인 시 코드 검색보다 DynamoDB/DB를 직접 조회해 메커니즘을 검증하길 선호함.
§
Notifly 조회는 고객사↔UUID/해시 project ID를 먼저 매핑하며, PG 접속 변수는 RDS_*가 아니라 POSTGRES_*로 주입됨.
§
사용자는 Notifly의 AI 기능을 활용하여 마케터들의 업무 효율을 높이는 홍보 문구를 작성할 때, '시간 절약'과 '성과(지표 개선)'라는 키워드를 중심으로 하는 것을 선호함.
§
GitHub PR은 Assignee를 `TheClevers`로 지정함. 사용자는 요청한 변경만 최소 범위로 구현하고, Linear 설명에 함께 적힌 별도 동작 변경(예: 에러 전파)도 명시적 합의 없이 포함하지 않길 원함. 구현 전 배포 단위를 확인하며 주석은 꼭 필요한 경우만 두는 것을 선호함.
§
사용자는 Notifly MCP 문서에서 ChatGPT 데스크톱 앱·웹·Codex·Claude 설정을 구분하길 원함. 데스크톱은 MCP server Restart, 웹은 Developer Mode/Plugins Refresh 흐름을 별도 섹션으로 설명하고, 연결 가이드는 기능·예시 프롬프트/응답보다 설치·인증·도구 갱신에 집중하길 선호함. 도구 변경 중에는 게시형 App보다 live Custom MCP를 선호하며 스크린샷은 연결 폼 1장으로 충분하다고 봄.
§
사용자는 캠페인 locale을 request→view_state→activation adapter→project별 PG materialization으로 검증함. Draft는 localized를 view_state에만 저장하고 활성화 시 locale별 변환하며, UI는 ‘언어 추가’ 버튼→하단 검색·선택 창과 default 기반 빈 필드 일괄 번역(기존 입력 보존)을 선호함.
§
사용자는 DB read routing을 함수·파일의 인접성이 아니라 같은 데이터에 대한 실제 read-after-write 호출 관계로 판정하고, 결합이 없으면 전용 reader를 쓰는 방식을 선호함.