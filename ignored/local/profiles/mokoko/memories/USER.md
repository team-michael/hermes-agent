사용자는 ‘모험가’ 호칭을 금하며, 친구 같은 모코코 톤과 이슈의 솔직한 공유를 선호함.
§
사용자는 설정·연동 계정·API 키를 실제 환경에서 재검증하고, 번역 API의 호출 경로·무료 구간·월 비용 상한을 확인하길 원함.
§
사용자는 AI 에이전트의 대화 로그를 조회할 때 토큰이나 레이턴시 등의 상세 필드는 제외하고, 'usermessage', 'assistantresponse', 'createdat', 'sessionid' 네 가지 핵심 필드만 요약해서 보기를 원함.
§
사용자는 API/MCP를 live DB·최신 main의 schema→adapter→DB→UI로 검증하고, canonical shape와 AND/OR 의미 보존을 중시함.
§
사용자는 스킬의 최신·정확성과 제품 고유 dialect·실제 엔진 호환성 검증을 중시하며, 범용 Skill/MCP의 무비판적 권장을 원치 않음.
§
사용자는 MCP 사용 리포트에서 Slack에는 고객사·도구별 집계만 표시하고, 민감할 수 있는 tool parameter는 권한 통제된 상세 조회 링크로 분리하는 방식을 선호함.
§
사용자는 Codex 사용량에서 추상적인 ‘세션’ 명칭보다 API가 반환한 실제 제한 기간(예: 5시간·7일)과 초기화 시각을 정확히 표시하길 원함.
§
사용자는 API·web-console UI 호환을 검증함. Locale UI는 ‘locale 추가’보다 ‘언어 추가’와 하단 검색·선택 창, default 기반 빈 언어 Auto-fill을 선호함. rollout은 Michael 하드코딩, 번역 키는 `.env`·AWS Secrets Manager를 선호함. PG writer 전 live tenant schema와 별도 migration SQL을 기대함.
§
사용자는 Linear에서 `Hyukjun Kang`이며, Parent 대신 개별 Todo 이슈를 마일스톤에 직접 연결하고 본인에게 배정하길 원함.
§
Notifly MCP 문서는 ChatGPT 데스크톱·웹·Codex를 분리하고, 도구 갱신 안내는 ChatGPT에서 제외하되 Claude에는 유지함. 변경은 Draft PR→사용자 미리보기·스크린샷→CI→Ready 순이며 사용자 미리보기 때 에이전트 서버는 종료함.
§
계획·검토만 요청하면 승인 전 이슈 생성·코드 수정·상태 변경을 원하지 않음.
§
사용자는 Poller retry 전 enqueue→checkpoint crash window와 멱등성을 확인하고, partial retry는 handler 응답·event source mapping·live `FunctionResponseTypes`를 모두 검증함. PR 보고 전 remote head/main도 재조회함.
§
‘원시인 모드’는 다음 할 일 하나만 짧게 답하는 형식임.