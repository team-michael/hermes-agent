Notifly 관리자. ‘모험가’ 호칭 금지, 친구 같은 모코코 톤. Slack 결과만, 특정인 조롱 금지.
§
threshold는 고객 prod 발송분포로 결정, 내부/dev 제외. 누락 1건도 중요·큰 모수 gap≈5%. 조정과 신규 anomaly는 별도 PR, 신규 PR 전 수치 보고·승인. SHA→artifact→runtime·가역 fault injection 선호.
§
스킬은 공식 문서·공개 저장소로 존재/설치를 구분하고 최신성·실엔진·umbrella+references를 중시함.
§
MCP 리포트는 프로젝트·프로덕트·도구별 호출량과 호출 주체 귀속·unknown 분류를 선호함.
§
Codex 사용량은 API 제한 기간(5시간·7일)·초기화 시각을 정확히 표시하길 원함.
§
Locale UI: ‘언어 추가’ 검색·빈 값 Auto-fill, source/fallback tooltip. 다국어 설정은 메시지 설정의 첫 번째 항목을 선호함.
§
Hyukjun Kang/GitHub TheClevers. PR은 독립 배포 단위로 분리하되 한 check면 묶음. 동일 작업 분리 PR은 Linear 공유·본인 In Progress; 책임이 다르면 이슈·parent 연결 금지.
§
Notifly MCP는 web-console create→편집 round-trip과 entry wrapper/branch direct groups를 구분하며, 신규 생성 오염을 ‘미복구’가 아닌 생성 시 표현 불일치로 설명하길 원함.
§
E2E는 mock seam보다 실데이터·통제된 canary를 선호하고, merge 전 branch runner를 실제 환경에 연결해 검증함. Web Console 저장→scheduler snapshot→consumer를 추적함.
§
Poller는 handler/ESM/live로 검증하며 fresh main→TDD·실측→remote 확인을 선호함. 호환 PR 배포·drain 뒤 activation PR을 marker-only diff로 rebase해 CI·리뷰를 정리함.
§
원시인/Ponytail full은 최소 작업·짧은 결론, 장애 조사는 live DB·계약 우선이며 지연 시 확인점을 즉시 원함.
§
PR 제목은 Semantic PR CI 준수. 리뷰는 head 정당성·무시 가능성을 설명하고 승인 전 무대응; 승인 후 RED→수정·검증→push→댓글·resolve→재조회.
§
팀·Notion 문서는 전→후 중심 고밀도 공식 문체(보통 3줄, 요청 시 1줄)를 선호함.
§
설계는 UI/schema/저장/runtime 경계·확정/미결을 구분함. helper는 이름 대신 구현·SQL을 확인함. SDK hot path는 넓은 getter보다 조건부 좁은 조회·device/event query 제거를 선호함.