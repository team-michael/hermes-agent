‘모험가’ 호칭 금지. 친구 같은 모코코 톤. Slack은 결과만 전달하며 특정인을 조롱 대상으로 지목하지 않음.
§
실운영 검증은 project/product/dev 귀속 대표 prod 표본과 live DB·SHA→artifact→runtime을 선호하며, 내부/dev tiny sample을 threshold 근거로 쓰지 않음. tenant DDL은 inventory→canary→전체. 경보는 원인별 이름.
§
스킬은 설치 목록만으로 부재 단정하지 않고 공식 문서·공개 저장소까지 확인해 존재와 설치를 구분함. 최신성·실엔진·umbrella+references를 선호하고 무비판 추천을 싫어함.
§
MCP 리포트는 프로젝트·프로덕트·도구별 호출량과 호출 주체 귀속·unknown 분류를 선호함.
§
Codex 사용량은 ‘세션’ 대신 API의 실제 제한 기간(5시간·7일)과 초기화 시각을 정확히 표시하길 원함.
§
Locale UI: ‘언어 추가’ 검색·빈 값 Auto-fill, source/fallback tooltip. 다국어 설정은 메시지 설정의 첫 번째 항목을 선호함.
§
Hyukjun Kang/GitHub TheClevers. PR마다 범위별 Linear 이슈를 만들어 본인 Todo로 할당·태그함. Parent는 책임 범위가 같을 때만 연결함.
§
Notifly MCP 문서는 클라이언트별 설정을 구분함. 편집 리소스는 web-console 저장 구조와 맞추고, 여정 진입 segment와 조건 분기 groups를 구분하며 create→편집 round-trip 검증을 선호함. AI 어시스턴트는 내부 tool명만 숨기고 공개 API/SDK명은 유지하며 프롬프트 규칙은 짧게 두길 원함.
§
PR 후속은 상태 전이·iframe·5개 locale key를 실데이터로 대조하고 mock·불필요한 예외/test seam·dead code를 피함.
§
Poller는 handler/ESM/live로 검증하며 fresh main→TDD·실측→remote 확인을 선호함. 호환 PR 배포·drain 뒤 activation PR을 marker-only diff로 rebase해 CI·리뷰를 정리함.
§
‘원시인 모드’는 다음 할 일 하나만 짧게 답함.
§
PR 리뷰는 CodeRabbit·ChatGPT/Codex를 모두 확인하고 핵심·액션만 짧게 설명하며, 승인 후 pull→수정·검증→답변·resolve→재리뷰까지 수행하길 선호함.
§
팀 공유는 전→후 중심 공식 문체(보통 3줄, 요청 시 1줄)를 선호함.
§
프롬프트 규칙은 짧고 고밀도로 쓰길 선호함. Assistant 전용 도구명은 사용자에게 숨기고, 조용히 실행해 결과나 필요한 입력만 안내하길 원함.
§
Ponytail full 모드를 선호함.