‘모험가’ 호칭 금지. 친구 같은 모코코 톤. Slack은 결과만 전달하며 특정인을 조롱 대상으로 지목하지 않음.
§
실운영 검증은 귀속된 prod 표본·SHA→artifact→runtime을 선호하고 내부/dev 표본을 threshold 근거로 쓰지 않음. 가역적 fault injection 선호. tenant DDL은 inventory→canary→전체, create_tables 변경은 prod schema CI.
§
스킬은 설치 목록만으로 부재 단정하지 않고 공식 문서·공개 저장소까지 확인해 존재와 설치를 구분함. 최신성·실엔진·umbrella+references를 선호하고 무비판 추천을 싫어함.
§
MCP 리포트는 프로젝트·프로덕트·도구별 호출량과 호출 주체 귀속·unknown 분류를 선호함.
§
Codex 사용량은 ‘세션’ 대신 API의 실제 제한 기간(5시간·7일)과 초기화 시각을 정확히 표시하길 원함.
§
Locale UI: ‘언어 추가’ 검색·빈 값 Auto-fill, source/fallback tooltip. 다국어 설정은 메시지 설정의 첫 번째 항목을 선호함.
§
Hyukjun Kang/GitHub TheClevers. 동일 작업을 배포 단위별 독립 PR로 나눌 때는 Linear 이슈 하나를 공유 태그하고 본인 할당·In Progress로 둠; 책임 범위가 다른 작업은 이슈 재사용·parent 연결하지 않음.
§
Notifly MCP는 web-console 저장 구조와 create→편집 round-trip을 맞추고, entry wrapper와 branch direct groups를 구분함. 신규 생성 오염을 근거 없이 ‘미복구’로 부르지 않고 생성 시 표현 불일치로 설명하길 원함.
§
E2E는 실데이터의 Web Console 저장→scheduler snapshot→consumer를 추적하며 mock/test seam을 피하고 dev resolver는 임시 로그로 확인함.
§
Poller는 handler/ESM/live로 검증하며 fresh main→TDD·실측→remote 확인을 선호함. 호환 PR 배포·drain 뒤 activation PR을 marker-only diff로 rebase해 CI·리뷰를 정리함.
§
원시인/Ponytail full은 최소 작업·짧은 결론, 장애 조사는 live DB·계약 우선이며 지연 시 확인점을 즉시 원함.
§
PR 리뷰는 CodeRabbit·ChatGPT/Codex 모두 확인해 핵심·액션만 짧게 설명함. pull→수정·검증→답변·resolve→재리뷰하며 커밋은 기본적으로 push까지 기대함.
§
팀 공유·Notion 기술문서는 전→후 중심의 짧고 고밀도인 공식 문체(보통 3줄, 요청 시 1줄)를 선호함.
§
설계 질문은 확정·미결·추천안을 한 번에 받길 원함.