# Notifly 워크스페이스 스키마 스냅샷 (2026-07-18 기준)

workspaceId: `661f8a973fe07874b657bb2c` · 콘솔: https://app.trackit.so/notifly
이 문서는 스냅샷이다. 스키마가 바뀌면 `python3 scripts/trackit.py schema --refresh` 후 `schema --entity X`로 실시간 확인.
건수는 2026-07-18 기준 참고치.

## 오브젝트

| slug | 이름 | objectId | 건수 | 용도 |
|---|---|---|---|---|
| companies | Companies | `661f8a973fe07874b657bb2f` | 1,230 | 회사 마스터. 도메인 기준 dedup |
| people | People | `661f8a973fe07874b657bb30` | 3,496 | 연락처. 이메일 기준 dedup |
| tasks | 할 일 | `661f8a973fe07874b657bc19` | 0 | 할 일 (미사용) |
| notes | Notes | `661f8a973fe07874b657bc23` | 63 | 메모 |
| s_leads | Leads | `6659276935795d036ddf70fe` | 359 | 웹폼 인바운드 리드 (트라이얼/문의 신청) |
| interactions | Interactions | `6659969919409c45bf3c4833` | 43 | 이메일/미팅 등 상호작용 로그 |
| braze | Braze | `6923b9f796b0d067d58d2e03` | 184 | Braze 사용 기업 아웃바운드 리스트 |

## 그룹 (파이프라인)

| 이름 | groupId | parent | 건수 |
|---|---|---|---|
| Notifly - Acquisition | `661f8aa63fe07874b657bca6` | companies | 164 |
| Clix - Acquisition | `68b784d8672a4bd3e0f743a2` | companies | 13 |
| Recruiting | `6681e6df06224011d2e22dd0` | people | 68 |
| LinkedIn-Minyong | `670a32724e02731224978632` | companies | 35 |
| Braze 아웃바운드 관리 | `6954c2834a4b4cebad07a6c8` | braze | 184 |

## 주요 속성 (전체 목록은 `schema --entity X`)

### companies

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| name | Name | text | sys | `661f8a973fe07874b657bb33` |
| domains | Domains | domain | multi,sys,uniq | `661f8a973fe07874b657bb34` |
| description | Description | text | sys | `661f8a973fe07874b657bb35` |
| categories | Categories | select | multi,sys | `661f8a973fe07874b657bb36` |
| location | Location | location | sys | `661f8a973fe07874b657bbcf` |
| employee-count | Employee count | number | sys | `661f8a973fe07874b657bbd0` |
| company-size | Company size | select | sys | `661f8a973fe07874b657bbd4` |
| revenue | Revenue | currency | sys | `661f8a973fe07874b657bbea` |
| last-interaction | Last interaction | interaction | sys | `661f8a973fe07874b657bbfa` |
| last-email-interaction | Last email interaction | interaction | sys | `661f8a973fe07874b657bbfc` |
| next-calendar-interaction | Next calendar interaction | interaction | sys | `661f8a973fe07874b657bbff` |
| created-date | Created date | timestamp | sys | `661f8a973fe07874b657bc02` |

categories select 옵션은 152개 (산업 분류) → CLI가 이름으로 해석하므로 여기 나열하지 않음. company-size 옵션: 중소기업/벤처기업/스타트업/중견기업/대기업/대기업\/중견기업/기타.
interaction 타입 sys 속성들(first/last-interaction 등)은 읽기 전용 로그 요약.

### people

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| name | Name | text | sys | `661f8a973fe07874b657bc03` |
| email-addresses | Email addresses | email_address | multi,sys,uniq | `661f8a973fe07874b657bc05` |
| company | Company | relation_record | sys | `661f8a973fe07874b657bb31` |
| job-title | Job title | text | sys | `661f8a973fe07874b657bc07` |
| phone-numbers | Phone numbers | phone_number | multi,sys | `661f8a973fe07874b657bc08` |
| linkedin | LinkedIn | url | sys | `661f8a973fe07874b657bc0a` |
| created-date | Created date | timestamp | sys | `661f8a973fe07874b657bc18` |
| 696994c67244d21f1186a164 | 링크드인 사용 기록 (25년 12월 기준) | text |  | `696994c67244d21f1186a164` |
| 696994da39ae6ef7fd911e62 | 서비스명 | text |  | `696994da39ae6ef7fd911e62` |
| 6969973794591b7def2e0c19 | 회사 | text |  | `6969973794591b7def2e0c19` |
| 697705bc2275257633de9f4e | Braze | relation_record | multi | `697705bc2275257633de9f4e` |
| 6a4752c5167d967401020f12 | Contact verification status | select |  | `6a4752c5167d967401020f12` |
| 6a4752e9167d967401020f14 | Outbound readiness | select |  | `6a4752e9167d967401020f14` |
| 6a475319b1a35bc3a0cc0895 | Contact source | select |  | `6a475319b1a35bc3a0cc0895` |
| 6a47532eb1a35bc3a0cc08bf | Verification note | text |  | `6a47532eb1a35bc3a0cc08bf` |

**Outbound readiness (`6a4752e9167d967401020f14`)** (`_id` → 이름):

- `6a4752df9f4ffe2be6a380cc` ready
- `6a4752e09f4ffe2be6a380cd` review_required
- `6a4752e39f4ffe2be6a380ce` do_not_use

**Contact source (`6a475319b1a35bc3a0cc0895`)** (`_id` → 이름):

- `6a4753009f4ffe2be6a380d0` trackit_existing
- `6a4753009f4ffe2be6a380d1` emails_and_names_sheet
- `6a47530b9f4ffe2be6a380d2` both_trackit_and_sheet
- `6a47530d9f4ffe2be6a380d3` manual_research
- `6a4753119f4ffe2be6a380d4` inbound
- `6a4753139f4ffe2be6a380d5` unknown

hex-slug 커스텀 속성(링크드인 사용 기록, 서비스명, 회사 등)은 표시 이름에 공백이 있으므로 `--where`에서는 slug(=attributeId) 사용.

### s_leads (인바운드 리드)

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| id | ID | text | sys,req,uniq | `6661a5d7a60a34e837cd10fe` |
| title | Title | select | sys | `6659276935795d036ddf70ff` |
| name | Submitted name | text | sys | `6659276935795d036ddf7100` |
| company-name | Submitted Company name | text | sys | `6659276935795d036ddf7101` |
| email-address | Submitted Email address | email_address | sys | `6659276935795d036ddf7102` |
| phone-number | Submitted Phone number | phone_number | sys | `6659276935795d036ddf7103` |
| extra | Extra | json | sys | `6659276935795d036ddf7104` |
| customer | Customer | relation_record | sys | `6659276935795d036ddf7105` |
| list-entries | Group entries | relation_record | multi,sys | `6659276935795d036ddf7108` |
| created-by | Created By | actor_reference | sys | `6659276935795d036ddf7109` |
| created-date | Created date | timestamp | sys | `6659276935795d036ddf710a` |
| modified-date | Modified date | timestamp | sys | `691edf0512af507cd6b39595` |
| modified-by | Modified by | actor_reference | sys | `691edf0512af507cd6b39597` |

**title (유입 폼 종류)** (`_id` → 이름):

- `66f3cda73f88cc69a3d3e23a` 노티플라이 30일 무료 트라이얼 신청
- `66fc85236c155ca7da15c96e` 노티플라이에 문의하기
- `67092c5d6eb2da1326f94ae6` Get 30 days free trial - Notifly
- `6750fe551aa5c6d71e2fa542` [디캠프] 노티플라이 3개월 무료 사용 신청
- `6750fefc1aa5c6d71e2faad3` [IBK창공] 노티플라이 3개월 무료 사용 신청
- `6750ff3a56a762be505d8c9f` [디캠프] 노티플라이 3개월 무료 트라이얼 신청
- `6751001a1aa5c6d71e2fb448` 노티플라이 3개월 무료 트라이얼 신청
- `6751005756a762be505d96b5` Get 3-month free trial - Notifly
- `675102fa993a82ce14289626` Get 6-month free trial - Notifly
- `675102fc993a82ce1428964a` 노티플라이 6개월 무료 신청하기
- `675103651aa5c6d71e2fc157` 노티플라이 데모 신청하기
- `675103951aa5c6d71e2fc20d` Get 2-month free trial - Notifly
- `68f57bf106b9c59442ea5d6e` 노티플라이 도입 문의


### braze (아웃바운드 리스트)

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| 694e2d62fafff0a8c4e2c48a | 링크드인 | url | multi | `694e2d62fafff0a8c4e2c48a` |
| 694e2d7ea8ffea700a1d5d33 | 링크드인 사용 기록 | text |  | `694e2d7ea8ffea700a1d5d33` |
| 694e2ea86e56a67d029ad539 | 회사 | text |  | `694e2ea86e56a67d029ad539` |
| 694e2ff8a8ffea700a1d5d5a | 레코드 | text |  | `694e2ff8a8ffea700a1d5d5a` |
| 6951df6794412bb8cde9d09c | 25년 2월 리스트와 중복여부 | text |  | `6951df6794412bb8cde9d09c` |
| 6951df8d4b67642344e6edea | 도메인 | text |  | `6951df8d4b67642344e6edea` |
| 6951dfbf94412bb8cde9d09e | Braze 사용 확률 | text |  | `6951dfbf94412bb8cde9d09e` |
| 6951dfc74a4b4cebad078941 | 우선순위 | text |  | `6951dfc74a4b4cebad078941` |
| 6951dfeccd5442bd4457c5d3 | 홈페이지 | domain |  | `6951dfeccd5442bd4457c5d3` |
| 6951e0a24a4b4cebad07895c | 유관 부서 이메일 출처 | text |  | `6951e0a24a4b4cebad07895c` |
| 6951e0b74a4b4cebad07895e | 제휴 폼 링크 | url |  | `6951e0b74a4b4cebad07895e` |
| 6951e0df5ad16ffeecbdb981 | 기존 리스트업 근거 출처 | text |  | `6951e0df5ad16ffeecbdb981` |
| 6951e0e65ad16ffeecbdb991 | 신규 리스트업 근거 출처 | text |  | `6951e0e65ad16ffeecbdb991` |
| 6951e0ec59beac8a4f74c26e | 비고 | text |  | `6951e0ec59beac8a4f74c26e` |
| 6951e0f559beac8a4f74c270 | 대표연락처 | email_address |  | `6951e0f559beac8a4f74c270` |
| 6951e0fb59beac8a4f74c272 | 유관 부서 이메일 | email_address |  | `6951e0fb59beac8a4f74c272` |
| 6951e1d859beac8a4f74c274 | 노티플라이 기존 미팅 여부 | select |  | `6951e1d859beac8a4f74c274` |
| 695202075ad16ffeecbdbc03 | 이름 | text |  | `695202075ad16ffeecbdbc03` |
| 6952021b5ad16ffeecbdbc05 | 실무자 이메일 | email_address |  | `6952021b5ad16ffeecbdbc05` |
| 6952022bcd5442bd4457c867 | 직책 | text |  | `6952022bcd5442bd4457c867` |
| 695202c14a4b4cebad078b7c | 회신 | status |  | `695202c14a4b4cebad078b7c` |
| 6951df794b67642344e6ede8 | 서비스명 | text | uniq | `6951df794b67642344e6ede8` |
| 697705bc2275257633de9f4d | 고객 | relation_record |  | `697705bc2275257633de9f4d` |

**노티플라이 기존 미팅 여부 (`6951e1d859beac8a4f74c274`)** (`_id` → 이름):

- `6951e1b4581a2c27da03dab3` 지정안함
- `6951e1b6581a2c27da03dab4` 미팅 이력 x
- `6951e1bd581a2c27da03dab5` 미팅 이력 o
- `6951e2001e530bd2848a158e` no
- `6951e2001e530bd2848a158f` yes

'회신' status(`695202c14a4b4cebad078b7c`)는 옵션이 0개로 비어 있음 (실제 회신 상태는 ' Braze 아웃바운드 관리' 그룹의 status 사용).

### 그룹: Notifly - Acquisition

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| id | ID | text | sys,req,uniq | `6661a5d7a60a34e837cd10b0` |
| parent-record | Parent record | relation_record | sys,req | `661f8aa63fe07874b657bca7` |
| stage | Stage | status |  | `661f8aa63fe07874b657bca8` |
| main-point-of-contact | Main point of contact | record |  | `661f8aa63fe07874b657bcb1` |
| owner | Owner | actor_reference |  | `661f8aa63fe07874b657bcb2` |
| priority | Priority | select |  | `661f8aa63fe07874b657bcb3` |
| estimated-contract-value | Estimated contract value | currency |  | `661f8aa63fe07874b657bcb9` |
| projected-close-date | Projected close date | date |  | `661f8aa63fe07874b657bcba` |
| close-confidence | Close confidence | rating |  | `661f8aa63fe07874b657bcbb` |
| close-lost-reason | Close lost reason | select |  | `661f8aa63fe07874b657bcbc` |
| note | Note | text |  | `661f8aa63fe07874b657bcc1` |
| created-by | Added to group by | actor_reference | sys | `661f8aa63fe07874b657bcc2` |
| created-date | Added to group at | timestamp | sys | `661f8aa63fe07874b657bcc3` |
| modified-date | Modified date | timestamp | sys | `691edf0512af507cd6b3959d` |
| modified-by | Modified by | actor_reference | sys | `691edf0512af507cd6b3959f` |

**stage/status 옵션** (`_id` → 이름):

- `661f8aa63fe07874b657bcaa` 자격 심사
- `661f8aa63fe07874b657bcab` 미팅
- `661f8aa63fe07874b657bcac` 제안
- `661f8aa63fe07874b657bcad` 협상
- `695dfad0ef37c302cebd6e18` 무료트라이얼시작
- `695dfaeb94f0ae943d214a86` paid 로 전환
- `695dfb13ef37c302cebd6e2e` 보류 및 홀드
- `695dfb2394f0ae943d214a88` 실패(경쟁사 도입)
- `695dfb334723d11006fb45d7` 실패
- `661f8aa63fe07874b657bcae` 성공(~2025)

**Priority 옵션** (`_id` → 이름):

- `661f8aa63fe07874b657bcb4` 가장 높음
- `661f8aa63fe07874b657bcb5` 높음
- `661f8aa63fe07874b657bcb6` 중간
- `661f8aa63fe07874b657bcb7` 낮음
- `661f8aa63fe07874b657bcb8` 가장 낮음

**Close lost reason 옵션** (`_id` → 이름):

- `661f8aa63fe07874b657bcbd` Competition
- `661f8aa63fe07874b657bcbe` Price
- `661f8aa63fe07874b657bcbf` Went close
- `661f8aa63fe07874b657bcc0` Not the right time


### 그룹: Clix - Acquisition

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| id | 시스템 ID | text | sys,req,uniq | `68b784d8672a4bd3e0f743a3` |
| parent-record | 데이터 | relation_record | sys,req | `68b784d8672a4bd3e0f743a4` |
| stage | 상태 | status |  | `68b784d8672a4bd3e0f743a5` |
| main-point-of-contact | 키맨 | record |  | `68b784d8672a4bd3e0f743ae` |
| owner | 담당자 | actor_reference |  | `68b784d8672a4bd3e0f743af` |
| priority | 우선순위 | select |  | `68b784d8672a4bd3e0f743b0` |
| estimated-contract-value | 예상 매출 | currency |  | `68b784d8672a4bd3e0f743b6` |
| projected-close-date | 예상 수주 일자 | date |  | `68b784d8672a4bd3e0f743b7` |
| close-confidence | 수주 확률 | rating |  | `68b784d8672a4bd3e0f743b8` |
| close-lost-reason | 실패 사유 | select |  | `68b784d8672a4bd3e0f743b9` |
| note | 노트 | text |  | `68b784d8672a4bd3e0f743be` |
| created-by | 등록자 | actor_reference | sys | `68b784d8672a4bd3e0f743bf` |
| created-date | 등록일 | timestamp | sys | `68b784d8672a4bd3e0f743c0` |
| modified-date | Modified date | timestamp | sys | `691edf0512af507cd6b395a1` |
| modified-by | Modified by | actor_reference | sys | `691edf0612af507cd6b395a3` |

**stage/status 옵션** (`_id` → 이름):

- `68b784d8672a4bd3e0f743a6` 탐색
- `68b784d8672a4bd3e0f743a7` 자격 심사
- `68b784d8672a4bd3e0f743a8` 미팅
- `68b784d8672a4bd3e0f743a9` 제안
- `68b784d8672a4bd3e0f743aa` 협상
- `68b784d8672a4bd3e0f743ab` 성공
- `68b784d8672a4bd3e0f743ad` 보류


### 그룹: LinkedIn-Minyong

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| id | ID | text | sys,req,uniq | `670a32724e02731224978633` |
| parent-record | Parent record | relation_record | sys,req | `670a32724e02731224978634` |
| stage | Stage | status |  | `670a32724e02731224978635` |
| main-point-of-contact | Main point of contact | record |  | `670a32724e0273122497863e` |
| owner | Owner | actor_reference |  | `670a32724e0273122497863f` |
| priority | Priority | select |  | `670a32724e02731224978640` |
| estimated-contract-value | Estimated contract value | currency |  | `670a32724e02731224978646` |
| projected-close-date | Projected close date | date |  | `670a32724e02731224978647` |
| close-confidence | Close confidence | rating |  | `670a32724e02731224978648` |
| close-lost-reason | Close lost reason | select |  | `670a32724e02731224978649` |
| note | Note | text |  | `670a32724e0273122497864e` |
| created-by | Added to group by | actor_reference | sys | `670a32724e0273122497864f` |
| created-date | Added to group at | timestamp | sys | `670a32724e02731224978650` |
| 670a34008661f7efb9a9726c | 연락일 | date |  | `670a34008661f7efb9a9726c` |
| modified-date | Modified date | timestamp | sys | `691edf0612af507cd6b395a9` |
| modified-by | Modified by | actor_reference | sys | `691edf0612af507cd6b395ab` |

**stage/status 옵션** (`_id` → 이름):

- `670a32724e02731224978636` 연락필요
- `670a32724e02731224978637` 답변완료
- `670a32724e02731224978638` 미팅요청
- `670a32724e02731224978639` 연락중
- `670a32724e0273122497863b` 미팅예정
- `670a32724e0273122497863c` 실패
- `670a32724e0273122497863d` 보류
- `670a33294e02731224978673` 답장없음


### 그룹: Recruiting

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| id | ID | text | sys,req,uniq | `6681e6df06224011d2e22dd1` |
| parent-record | Parent record | relation_record | sys,req | `6681e6df06224011d2e22dd2` |
| stage | Stage | status |  | `6681e6df06224011d2e22dd3` |
| applying-for | Applying for | select |  | `6681e6df06224011d2e22ddb` |
| role-level | Role level | select |  | `6681e6df06224011d2e22de4` |
| team | Team | select |  | `6681e6df06224011d2e22dea` |
| manager | Manager | actor_reference |  | `6681e6df06224011d2e22df5` |
| employment-status | Employment status | select |  | `6681e6df06224011d2e22df6` |
| potential-start-date | Potential start date | date |  | `6681e6df06224011d2e22dfd` |
| source-type | Source type | select |  | `6681e6df06224011d2e22dfe` |
| source | Source | select |  | `6681e6df06224011d2e22e03` |
| created-by | Added to group by | actor_reference | sys | `6681e6df06224011d2e22e0b` |
| created-date | Added to group at | timestamp | sys | `6681e6df06224011d2e22e0c` |
| 68b78561661752c92043b1c2 | Company | text |  | `68b78561661752c92043b1c2` |
| modified-date | Modified date | timestamp | sys | `691edf0612af507cd6b395a5` |
| modified-by | Modified by | actor_reference | sys | `691edf0612af507cd6b395a7` |

**stage/status 옵션** (`_id` → 이름):

- `6681e6df06224011d2e22dd4` Qualified
- `6681e6df06224011d2e22dd5` Contacted
- `6681e6df06224011d2e22dd6` Coffee Chat
- `6681e6df06224011d2e22dd7` Waiting for Interview
- `6681e6df06224011d2e22dd8` Interview
- `6681e6df06224011d2e22dd9` Offer
- `68b78510672a4bd3e0f743d6` Pool
- `6681e6df06224011d2e22dda` Dropped out
- `6681e95206224011d2e22ed3` No interest from both sides
- `6681e96b2124667d4ebd853a` No reply
- `6685e293ce1bcc98e9cfb480` Rejected
- `68b7845f672a4bd3e0f74382` Accepted


### 그룹: Braze 아웃바운드 관리

| slug | 이름 | 타입 | 플래그 | attributeId |
|---|---|---|---|---|
| id | ID | text | sys,req,uniq | `6954c2834a4b4cebad07a6c9` |
| parent-record | Braze | relation_record | sys,req | `6954c2834a4b4cebad07a6cb` |
| created-by | Added to group by | actor_reference | sys,req | `6954c2834a4b4cebad07a6cd` |
| created-date | Added to group at | timestamp | sys,req | `6954c2834a4b4cebad07a6cf` |
| modified-by | Modified by | actor_reference | sys,req | `6954c2834a4b4cebad07a6d1` |
| modified-date | Modified date | timestamp | sys,req | `6954c2834a4b4cebad07a6d3` |
| 6954c2bd94412bb8cde9eb92 | 텍스트 | status |  | `6954c2bd94412bb8cde9eb92` |
| 695c9d1a0dcb7bfe367a7baf | 콜드메일 전략 | text |  | `695c9d1a0dcb7bfe367a7baf` |
| 695e2396f45e0c242f6f9274 | 마지막 회신일 | date |  | `695e2396f45e0c242f6f9274` |

**stage/status 옵션** (`_id` → 이름):

- `6954c2c54b67642344e70b0c` 1차 콜드메일
- `695c9dff6a827714210b5cb2` 2차 콜드메일
- `695c9e03f8e6897f8bc05a57` 3차 콜드메일 
- `695c9e08744d622fc31240b3` 4차 콜드메일
- `695c9e2f0dcb7bfe367a7bb4` 회신 팔로업 중
- `695c9e42987effe5d42d7518` 회신 없음
- `695c9e3b744d622fc31240b4` 미팅
- `695c9e25987effe5d42d7517` 메일 발송 중단
- `695c9e404af920e13b223fef` paid 전환


## 멤버

| 이름 | 이메일 | 상태 | userId |
|---|---|---|---|
| Minyong Lee | minyong@greyboxhq.com | admin | `661f8a8bf7408ac088e68e81` |
| Bogeon Chae | bogeon@greyboxhq.com | suspended | `661f8c7c00d7d09265aa5769` |
| Minkyu Cho | minkyu@greyboxhq.com | admin | `661f8d15f7408ac088e68e83` |
| Gyumin Choi | dq@greyboxhq.com | suspended | `661f8e50f7408ac088e68e85` |
| Kyungseo Jeong | kyungseo@greyboxhq.com | admin | `67f7789293e8be2e9cc287ae` |
| 박소현 | sohyun@greyboxhq.com | suspended | `691d451b816b174a6d6a2146` |
| Kahyeon Yu | kahyeon@greyboxhq.com | member | `695c78040dfe0adb484f9ed7` |
| 성기봉 | dante@trackit.so | suspended | `65c3e287b8cd60b65d8cf130` |
| Yoon Seol Kwon | yoonseol@greyboxhq.com | member | `6a544ccaf5626a549ccb7c9d` |

담당자(actor) 필터·해석의 매핑 키는 멤버의 `_id`가 아니라 **`userId`**.

## 알려진 특이사항

- 'Braze 아웃바운드 관리' 그룹의 status 속성 표시 이름이 '텍스트'로 되어 있음 (slug 없음 → attributeId `6954c2bd94412bb8cde9eb92` 사용).
- Recruiting 그룹의 'Company' 속성은 hex slug (`68b78561661752c92043b1c2`).
- tasks 오브젝트는 현재 미사용 (0건).
- Notifly stage '성공(~2025)'은 과거 성공 딜 아카이브 성격. 현재 성공은 'paid 로 전환'.- braze 오브젝트의 '도메인' 속성은 웹 도메인이 아니라 산업 분류 텍스트다 (예: "패션/악세사리 커머스"). 실제 웹 도메인은 '홈페이지'(domain 타입)에 있음.
