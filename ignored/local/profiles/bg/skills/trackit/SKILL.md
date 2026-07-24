---
name: trackit
description: Notifly 팀의 Trackit(트래킷, trackit.so) CRM을 Open API로 조회·리포트·등록·수정한다. Trackit/트래킷/CRM이 언급되거나, 잠재 고객·리드·딜·파이프라인 조회, owner(담당자) 확인, 아웃바운드·콜드메일 이력 확인, 영업 현황 리포트, CRM 리스트 추출/CSV, 레코드 등록·수정 요청이 있으면 반드시 이 스킬을 사용할 것. "이 회사 CRM에 있어?", "파이프라인 현황", "리드 뽑아줘", "Braze 아웃바운드 상태", "담당자 누구야" 같은 요청도 트리거다. TRACKIT_API_TOKEN 환경변수 필요. companies/people/s_leads/braze 오브젝트와 Notifly·Clix Acquisition, LinkedIn-Minyong, Recruiting, Braze 아웃바운드 파이프라인을 다룬다.
---

# Trackit CRM 스킬

Trackit은 EAV 구조(오브젝트=테이블, 속성=컬럼, 레코드=행, 그룹=오브젝트 하위 파이프라인 테이블, 엔트리=그룹의 행)의 커스텀 CRM이다. 옵션·담당자·참조 값이 전부 ID로 저장되기 때문에 직접 API를 조립하지 말고 **번들 CLI(`scripts/trackit.py`)를 사용**한다. CLI가 스키마 캐시, ID↔이름 해석, 페이지네이션, 쓰기 안전장치를 전부 처리한다.

## 준비

```bash
export TRACKIT_API_TOKEN=...   # 또는 TRACKIT_API_TOKEN_FILE, ~/.config/trackit/token, ./.trackit_token 파일
python3 scripts/trackit.py schema          # 캐시 없으면 자동 생성 (~15초)
python3 scripts/trackit.py schema --refresh  # 스키마·옵션 변경 후 갱신
```

- 토큰은 워크스페이스 전체 스코프다. **코드·노트·커밋에 절대 저장하지 않는다.**
- BG 프로필에서는 `TRACKIT_API_TOKEN_FILE`과 `TRACKIT_CACHE_DIR`이 이미 전용 경로로 설정되어 있다. 토큰을 다른 위치로 복사하거나 인증을 다시 설정하지 않는다.
- 캐시는 `~/.cache/trackit/schema.json`. 속성/옵션이 안 찾아지면 먼저 `--refresh`.
- rate limit이 문서화되어 있지 않다. CLI가 페이지 사이 0.15초씩 쉬지만, 수천 건 반복 호출은 자제.

## 명령 치트시트

```bash
T=scripts/trackit.py
python3 $T schema                          # 오브젝트/그룹/멤버 요약
python3 $T schema --entity companies       # 속성 + select/status 옵션 상세
python3 $T lookup "무신사"                  # 통합 검색: 회사·사람·braze·리드 + 파이프라인 이력
python3 $T lookup "amondz" -o companies    # 아웃리치 전 owner·이력 확인 (핵심 용도)
python3 $T pipeline                        # Notifly - Acquisition 단계별 현황
python3 $T pipeline -g "Clix - Acquisition"
python3 $T pipeline --stage 협상
python3 $T query -o companies -w "name contains 클래스" 
python3 $T query -o "Notifly - Acquisition" -w "stage is 제안" -w "owner is minyong@greyboxhq.com"
python3 $T query -o s_leads -w "created-date last_1_month" --csv leads.csv
python3 $T query -o companies -w "domains is class101.net" --count
python3 $T query -o braze -w "회신 not_empty" -f "서비스명,회사,회신"
python3 $T query -o companies --group-by company-size          # 속성값별 건수 집계
python3 $T query -o "Notifly - Acquisition" --group-by stage   # 단계별 분포
python3 $T members                         # userId ↔ 이름 매핑
python3 $T create -o people --values '{"name":["김철수"],"email-addresses":["kim@acme.co"]}' --yes
python3 $T create -o people --csv leads.csv --yes              # CSV 일괄 등록 (헤더=slug 또는 표시 이름)
python3 $T update -o companies -m "domains=acme.co" --values '{"description":"..."}' --yes
python3 $T delete -o notes -m "title=..." --yes
python3 $T raw --method POST --path /objects/companies/records/ids --body '{"limit":1}'   # 쓰기 경로는 --allow-write
```

`--values`의 키와 `--csv` 헤더는 slug와 표시 이름 둘 다 인식하고, 스칼라는 자동으로 배열로 감싼다. 존재하지 않는 속성명은 후보 목록과 함께 에러가 난다.

## `--where` DSL

형식: `"<속성> <연산자> [값]"`. 반복하면 AND, `--or` 플래그로 OR 결합. 복잡한 중첩(AND+OR 혼합)은 `raw` + 직접 필터 JSON(→ `references/query-api.md`).

- 속성: slug, 한글/영문 표시 이름, attributeId 모두 인식. **이름에 공백이 있으면 slug나 attributeId 사용.**
- 값 자동 해석: select/status 옵션 이름→옵션 ID, 멤버 이메일/이름→userId, 레코드 참조 이름→recordId (모호하면 후보를 보여주고 중단).
- 연산자 (타입별):
  - 텍스트·url·domain·email·phone: `contains` `not_contains` `starts_with` `ends_with` `is` `is_not` `empty` `not_empty`
  - 숫자·rating·currency: `is` `greater_than` `less_than` `empty` `not_empty`
  - 날짜: `from` `until` `before` `after` (값 `YYYY-MM-DD` 가능) + 상대: `today` `this_week` `this_month` `this_quarter` `this_year` `last_7_days` `last_1_month` `last_3_months` `last_6_months` `last_1_year` (값 없음, Asia/Seoul 기준)
  - select/status/레코드참조: `is`(→contains#list로 변환) `is_not` `empty` `not_empty`
  - 담당자: `is` `is_not` `empty` `not_empty` / 체크박스: `is_true` `is_false`
- 하위 필드 지정: `location.city contains 서울`, `email-addresses.emailDomain is acme.co`

## 쓰기 안전 수칙 (중요)

쓰기 API의 update/delete는 **filter 매칭 방식이라 여러 레코드를 한 번에 바꿀 수 있다**. CLI에 안전장치가 내장되어 있고, 이를 우회하지 않는다:

1. `--yes` 없이 한 번 실행해 **미리보기(매칭 레코드 목록)를 먼저 확인**하고, 의도와 일치할 때만 `--yes`로 재실행한다.
2. update가 2건 이상 매칭되면 차단된다. 전부 수정할 의도가 확실할 때만 `--allow-multiple`을 추가한다.
3. delete는 1건 매칭일 때만 실행된다. 여러 건 삭제는 한 건씩 처리한다.
4. Minyong의 정확하고 명시적인 쓰기 요청은 미리보기와 매칭 확인 후 해당 작업을 승인한 것으로 본다. 다른 Slack 사용자의 create/update/delete는 반드시 Minyong의 승인을 받아야 한다. delete는 Minyong이 정확한 삭제 대상을 명시한 경우에만 수행한다. 대량 쓰기 전에는 대상 건수를 보고하고 별도 승인을 받는다.
5. `raw`로 쓰기 엔드포인트를 호출하지 않는다 (미리보기가 없다).
6. 그룹 엔트리(파이프라인 stage 등)의 쓰기 API는 미제공. 엔트리 변경은 UI에서 한다.
7. people 생성 시 이메일이 있으면 회사 레코드가 자동 생성되고, 이메일/도메인으로 중복 검사된다 (`references/write-api.md`).
8. 쓰기 값 형식: select/status는 옵션 이름 그대로(`["ready"]`), 레코드 참조(company 등)는 이름이 아니라 **recordId**(`lookup`으로 확보). hex slug 커스텀 속성은 attributeId를 키로 사용.

## Notifly - Acquisition UI 작업

Open API는 그룹 엔트리(stage·owner·note 등) 변경을 지원하지 않으므로, 해당 값의 추가·수정은 아래 보드 UI를 사용한다.

- 보드 URL: `https://app.trackit.so/notifly/groups/661f8aa63fe07874b657bca6/views/661f8aa63fe07874b657bcc4`
- 제목: **Notifly - Acquisition**. 우측 상단에 `Add Company`, `View settings`가 있고, 본문은 stage별 칸반 보드다.
- 카드 표시 순서: 회사명 → Projected close date → Owner → Main point of contact → Note → Estimated contract value → 경과일수.

### 회사 추가

1. `+ Add Company`를 클릭하고 회사명을 검색한다.
2. 기존 회사가 검색되면 해당 레코드를 선택한다. 없으면 `Create “<회사명>”...`를 선택한다.
3. 추가 후 원하는 stage로 카드를 드래그하거나, 상세 패널의 Stage 필드를 수정한다.
4. 이름이 같은 회사가 존재할 수 있으므로 기존 회사를 선택하거나 수정할 때는 **회사 ID(URL의 `/companies/<id>`)와 현재 stage를 함께 확인**한다.

### 필드 수정

- 빠른 수정: 카드의 날짜·Note·Estimated contract value 등을 클릭해 인라인 편집하고 `Enter` 또는 포커스 아웃으로 저장한다.
- 정확한 수정(권장): 카드 hover 시 나타나는 펼침 아이콘을 눌러 상세 패널을 연다.
  - **Record Details**: Name, Domains, Description, Categories, Location, Employee count, CEO, Foundation date, Sub category, Company size, Stock type, Revenue, Operating profit, Net income, Credit rating, SNS 등. 필요하면 `Show all values`를 누른다.
  - **Groups**: Stage, Main point of contact, Owner, Priority, Estimated contract value, Projected close date, Close confidence, Close lost reason, Note 등.
- 필드를 클릭해 입력/선택 후 `Enter` 또는 포커스 아웃으로 저장한다. `Esc`는 취소이며, 패널은 좌측 상단 `X`/`ESC` 또는 키보드 `Escape`로 닫는다.
- 텍스트는 자유 입력, 날짜는 날짜 선택기, Company size/Credit rating 등은 드롭다운 태그를 사용한다.
- 저장 후 카드를 다시 확인해 값과 stage가 실제 반영됐는지 검증한다.

## 워크스페이스 구조 (2026-07 기준)

오브젝트: `companies`(회사 1,230) `people`(연락처 3,496) `s_leads`(인바운드 리드 359, 웹폼 유입) `braze`(Braze 사용 기업 아웃바운드 리스트 184) `interactions` `notes` `tasks`

그룹(파이프라인, parent 오브젝트의 하위): 
- **Notifly - Acquisition** (companies 하위, 주력 세일즈 파이프라인 164건) — stage: 자격 심사→미팅→제안→협상→무료트라이얼시작→paid 로 전환 / 보류 및 홀드 / 실패 / 실패(경쟁사 도입) / 성공(~2025)
- **Clix - Acquisition** (companies 하위) — stage: 탐색→자격 심사→미팅→제안→협상→성공/보류
- **LinkedIn-Minyong** (companies 하위) — 링크드인 아웃바운드: 연락필요/연락중/답변완료/답장없음/미팅요청/미팅예정 등
- **Recruiting** (people 하위) — 채용 파이프라인
- **Braze 아웃바운드 관리** (braze 하위) — 1차~4차 콜드메일/회신 팔로업 중/미팅/paid 전환 등

멤버 이름·userId는 `members` 명령으로. 상세 스키마·옵션 ID·속성 목록은 `references/workspace.md` 참조 (실시간 확인은 `schema --entity X`).

## 자주 하는 작업 레시피

**1. 아웃리치 전 중복·owner 확인** (콜드 메일/부스 방문 전 필수)
```bash
python3 $T lookup "회사명 또는 도메인"
```
한글/영문 표기가 다를 수 있다 (예: amondz ↔ 아몬즈). 도메인으로 한 번, 이름으로 한 번 검색하는 것이 안전하다.
매칭 레코드 + 그 레코드가 속한 파이프라인 엔트리(stage·owner·note)까지 한 번에 나온다 (companies→Notifly/Clix/LinkedIn, braze→Braze 아웃바운드 관리, people→Recruiting). owner가 있으면 cold 접근 대신 해당 owner에게 warm 인계.

**2. 주간 파이프라인 리포트**
```bash
python3 $T pipeline                        # 단계별 표 + 예상 금액 합계
python3 $T query -o "Notifly - Acquisition" -w "created-date this_week"   # 이번 주 신규
```

**3. 세그먼트 리스트 추출 → CSV**
```bash
python3 $T query -o companies -w "categories is SAAS" --all --csv out.csv
python3 $T query -o people -w "email-addresses not_empty" -w "company not_empty" --all --csv contacts.csv
```

**4. 데이터 위생 점검**
```bash
python3 $T query -o "Notifly - Acquisition" -w "projected-close-date before 2026-07-01" -w "stage is 제안"   # 기한 지난 딜
python3 $T query -o companies -w "domains empty" --count   # 도메인 없는 회사
```

**4b. 분포·집계 리포트**
```bash
python3 $T query -o companies --group-by categories            # 산업별 회사 수
python3 $T query -o "Notifly - Acquisition" -w "created-date this_year" --group-by owner   # 올해 담당자별
```

**4c. 행사 리드 리스트 일괄 등록** (헤더 예: `name,email-addresses,job-title`)
```bash
python3 $T create -o people --csv event_leads.csv        # 미리보기 (컬럼 매핑 + 샘플)
python3 $T create -o people --csv event_leads.csv --yes  # 실행. 행별 성공/실패 리포트, 중복은 unique 에러로 표시
```

**5. 인바운드 리드 확인 후 등록 (회사 연결 포함)**
```bash
python3 $T query -o s_leads -w "created-date last_7_days"
python3 $T create -o people --values '{"name":["..."],"email-addresses":["..."]}'   # 미리보기 → --yes
python3 $T lookup "회사명" -o companies --no-entries                                # recordId 확보
python3 $T update -o people -m "email-addresses=..." --values '{"company":["<recordId>"]}'
```

**6. 특정 회사 관련 메모·상호작용 이력**
```bash
python3 $T lookup "회사명" -o companies --no-entries       # recordId 확보
python3 $T query -o interactions -w "referenced-records is <recordId>"
python3 $T query -o notes -w "referenced-records is <recordId>"
```

## 문제 해결·주의

- 값이 없는 속성은 응답에서 **아예 생략**된다(빈 값 ≠ 오류). 0건이면 필터 없이 `--count`로 교차 확인.
- **interaction 타입 속성(first/last-interaction 등)은 필터가 동작하지 않는다** (`not_empty`도 0건 반환, 2026-07-18 실측). "오래 미접촉" 분석은 interactions 오브젝트를 조회해 클라이언트에서 집계하거나 그룹 엔트리의 날짜 속성을 쓴다.
- date 값은 `calendarDate`(달력 날짜) 기준으로 CLI가 렌더링한다. UTC value로 날짜 해석하지 말 것.
- `is_current_user` 계열 필터는 API 토큰에서 무시된다. 담당자는 이메일로 명시.
- 401이면 토큰 미설정/만료. 422면 필터 구조 오류 → `references/query-api.md`로 raw 필터 검증.
- 필터 JSON을 직접 조립해야 하면 `references/query-api.md`, 쓰기 API 상세는 `references/write-api.md`, 이 워크스페이스의 속성·옵션 ID는 `references/workspace.md`를 읽는다.
- Codex 등 다른 에이전트도 이 문서와 스크립트를 그대로 사용 가능 (python3 표준 라이브러리만 사용).
