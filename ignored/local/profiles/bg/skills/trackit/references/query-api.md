# Trackit Record Query API (raw 필터가 필요할 때)

Base `https://api.trackit.so/v1`, 헤더 `Authorization: Bearer $TOKEN`, `X-Timezone: Asia/Seoul`(상대 날짜 기준), 응답은 `{"result": ...}`, 에러는 `{"detail":{"message":...}}` (401 인증 / 422 본문 형식 / 400 도메인 검증 / 404 없음).

CLI의 `raw` 명령으로 호출: `python3 scripts/trackit.py raw --method POST --path /objects/companies/records/ids --body '{...}'`

## 엔드포인트

| 용도 | Method · Path |
|---|---|
| 오브젝트 목록 | `GET /objects` |
| 그룹 목록 | `GET /groups` |
| 속성 목록 | `GET /objects/{object}/attributes`, `GET /groups/{group}/attributes` |
| 레코드 ID 조회 | `POST /objects/{object}/records/ids` |
| 레코드 값 배치 | `POST /objects/{object}/records/attribute-values` |
| 엔트리 ID 조회 | `POST /groups/{group}/entries/ids` |
| 엔트리 값 배치 | `POST /groups/{group}/entries/attribute-values` |
| select 옵션 | `GET /objects/{object}/attributes/{attr}/select-options` (groups 동일) |
| status 옵션 | `GET /objects/{object}/attributes/{attr}/status-options` (groups 동일) |
| 멤버 | `GET /members` |

`{object}`=objectId 또는 slug, `{group}`=groupId, `{attr}`=attributeId.
조회 파이프라인: ① ids(필터·정렬·페이지네이션, `totalCount` 포함) → ② attribute-values(raw 값, ID 형태) → ③ 옵션/멤버 목록으로 ID→이름 해석.

## ids 요청/응답

```json
{"filter": {...}, "sorts": [...], "offset": 0, "limit": 100}
```
limit 최대 500, 기본 100. sorts 생략 시 `_id` 내림차순(최신순). 응답:
```json
{"result": {"workspaceId": "...", "entityId": "...", "entityInstanceIds": ["..."], "totalCount": 1234}}
```

## attribute-values 요청/응답

```json
{"recordIds": ["..."], "attributeIds": ["..."]}     // 엔트리는 entryIds
```
recordIds 최대 500, attributeIds 최대 100. 응답 `records[].attributes[].values[]` (엔트리는 `entries[].entryId`).
**값이 없는 속성/레코드는 응답에서 생략됨(sparse).** `values`는 단일값도 배열. 다중값 타입(url, domain, email_address, phone_number, select, record, relation_record, actor_reference, file)은 여러 항목 가능.

## filter 구조

```json
{"operator": "and|or", "forms": [
  {"type": "condition", "path": [...], "constraints": [...]},
  {"type": "group", "operator": "or", "forms": [...]}
]}
```
중첩 `group`으로 `(A AND B) OR C` 표현. filter 생략/forms 비면 전체 레코드.

condition의 path 노드 (필터용, 1개면 충분):
```json
{"entityType": "objects|groups", "entityId": "<objectId|groupId>",
 "attributeType": "<타입>", "attributeId": "<attrId>", "referencedEntityId": null}
```

constraint:
```json
{"field": "<하위필드>", "operator": "<연산자>", "value": <값>, "valueType": "static", "fieldLocation": "value"}
```
같은 condition에 constraints 여러 개 = 같은 속성에 함께 적용 (날짜 from+until 범위, select 옵션 여러 개 OR).

### field 기본값 (타입별)

`text/number/url/domain/checkbox/date/timestamp/rating`→`value`, `select`→`selectOptionId`, `status`→`statusOptionId`, `email_address`→`emailAddress`, `phone_number`→`phoneNumber`, `currency`→`currencyValue`, `record/relation_record`→`recordId`, `actor_reference`→`actorId`, `location`→`addressLine|city|state|countryCode` 중 명시.

### 연산자 (타입별)

- 텍스트류: `contains not_contains starts_with ends_with is is_not empty not_empty` (값: 문자열)
- 숫자류: `is is_not greater_than less_than empty not_empty` (값: 숫자)
- 날짜: `is is_not before after from until empty not_empty` (값: ISO-8601 예 `"2026-01-15T00:00:00+09:00"`) + 상대(값 null): `today this_week this_month this_quarter this_year last_7_days last_1_month last_3_months last_6_months last_1_year`
- 체크박스: `is_true is_false` (값 null)
- select/status: `contains#list not_contains#list empty not_empty` (값: 옵션 ID 1개. 다중 OR은 constraint 나열)
- record/relation_record: `contains#list not_contains#list empty not_empty` (값: recordId)
- actor_reference: `is is_not empty not_empty` (값: userId)

주의: 옵션·참조·담당자 필터의 value는 **이름이 아니라 ID**. `is_current_user`는 API 토큰에서 무시됨.

## sorts 구조 (path 노드가 필터와 다름!)

```json
{"path": [{"workspaceId": "661f8a973fe07874b657bb2c", "entityType": "objects", "entityId": "...",
           "entitySlug": "...", "attributeId": "...", "attributeSlug": "...",
           "attributeType": "...", "referencedEntityId": null}],
 "field": "value", "direction": "asc|desc"}
```
배열 순서 = 1차·2차 정렬. null 값은 항상 뒤. select/status는 옵션 표시 순서(orderValue), 담당자는 멤버 이름 기준 정렬.

## 값(raw) 해석

| 타입 | 형태 | 사람이 읽을 값 |
|---|---|---|
| text/number/url/domain/checkbox/rating | `{"value": ...}` | value |
| currency | `{"currencyCode","currencyValue"}` | 둘 조합 |
| email_address | `{"emailAddress","emailDomain"}` | emailAddress |
| phone_number | `{"countryCode","phoneNumber"}` | phoneNumber |
| location | `{"countryCode","state","city","addressLine"}` | 조합 |
| date | `{"value","timezone","calendarDate"}` | **calendarDate** (UTC value로 날짜 해석 금지) |
| timestamp | `{"value","timezone"}` | value |
| select | `{"selectOptionId"}` | select-options의 `_id` 매핑 |
| status | `{"statusOptionId"}` | status-options의 `_id` 매핑 |
| actor_reference | `{"actorId","actorType"}` | actorType=user일 때 members의 **userId** 매핑 (`_id` 아님!) |
| record/relation_record | `{"objectId","objectSlug","recordId"}` | 대상 오브젝트에서 이름 속성 별도 조회 (전용 API 없음) |
| file | `{"url","filename","size","contentType"}` | filename |

## 페이지네이션

offset/limit (커서 없음). `totalCount` 기준 `offset += limit` 반복. 전수 추출은 limit 500.
