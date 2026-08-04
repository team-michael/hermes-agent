‘모험가’ 호칭 금지. 친구 같은 모코코 톤과 솔직한 공유를 선호함.
§
`notifly-kokomo`는 개인 테스트 product; 결제 장애는 DDB 원복 전제의 prod Payple 동일 카드 재등록으로 검증함.
§
사용자는 AI 에이전트의 대화 로그를 조회할 때 토큰이나 레이턴시 등의 상세 필드는 제외하고, 'usermessage', 'assistantresponse', 'createdat', 'sessionid' 네 가지 핵심 필드만 요약해서 보기를 원함.
§
사용자는 최신 main·live DB·실구현을 검증하고, 메타데이터 누락은 SDK/API/CSV/연동/유저여정 등 실제 writer를 전수 확인한 뒤 기존 구조를 살려 해결하길 선호함. KDS hot path의 동기 DDB 쓰기·실패 결합을 경계함.
§
사용자는 스킬의 최신성·실엔진 검증과 class-level umbrella+references 구조를 선호하며, 범용 Skill/MCP의 무비판적 권장을 싫어함.
§
사용자는 MCP 리포트에서 프로젝트별 호출량·도구 종류·도구별 횟수·사용패턴과 도구별 사용량 그래프를 원함. 민감한 parameter는 권한 통제 상세 링크로 분리함.
§
사용자는 Codex 사용량에서 추상적인 ‘세션’ 명칭보다 API가 반환한 실제 제한 기간(예: 5시간·7일)과 초기화 시각을 정확히 표시하길 원함.
§
Locale UI는 ‘언어 추가’·하단 검색/선택·default 기반 빈 언어 Auto-fill을 선호함. rollout은 Michael allowlist, 번역 키는 `.env`·Secrets Manager, PG writer 전 live schema·별도 migration SQL 검증을 원함.
§
`Hyukjun Kang`; Linear 이슈는 본인 배정 Todo, 요청 시 parent subissue로 생성.
§
Notifly MCP 문서는 ChatGPT 데스크톱·웹·Codex를 분리하고, 도구 갱신 안내는 ChatGPT에서 제외하되 Claude에는 유지함. 변경은 Draft PR→사용자 미리보기·스크린샷→CI→Ready 순이며 사용자 미리보기 때 에이전트 서버는 종료함.
§
계획·검토만 요청하면 승인 전 이슈 생성·코드 수정·상태 변경을 원하지 않음.
§
사용자는 Poller의 crash·멱등성과 partial retry의 handler/ESM/live 설정을 검증함. 구현은 fresh main 격리 worktree→TDD·실측→remote 확인→stacked Draft PR·CI→선행 PR Ready→CodeRabbit·Codex 리뷰 대기를 선호함.
§
‘원시인 모드’는 다음 할 일 하나만 짧게 답하는 형식임.
§
자동 리뷰는 먼저 메커니즘·목표 정합성으로 설명·분류한 뒤, 합의된 최소 변경만 반영하길 선호함.