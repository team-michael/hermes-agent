# Trackit 쓰기 API (HTTP API)

공식 문서: https://docs.trackit.so/integrations/http-api.md
오브젝트 레코드만 지원. **그룹 엔트리 쓰기 API는 미제공** (stage 변경 등은 UI에서).
속성 지정은 attributeId가 아니라 **slug** (`schema --entity X`로 확인).
가능하면 raw 호출 대신 CLI(`create`/`update`/`delete`)를 사용할 것. 미리보기와 다중 매칭 차단이 내장되어 있다.

## 생성

```
POST /objects/{slug}/records
{"values": {"name": ["장토스"], "email-addresses": ["jang@toss.im"]}}
```
- 값은 속성 slug를 키로 하는 **배열** 형태.
- people 생성 시 이메일이 있으면 회사 레코드 자동 생성. companies 생성 시 `team`에 이메일 배열을 주면 people도 함께 생성.
- 중복 검사: people은 `email-addresses`, companies는 `domains` 기준. 중복이면 에러 (예: `W109: The value of the "email-addresses" attribute must be unique.`).

## 수정

```
PUT /objects/{slug}/records
{"filter": {"email-addresses": ["jang@toss.im"]},
 "values": {"name": "한토스"},
 "allowMultiple": false}
```
- **filter에 매칭되는 모든 레코드가 수정된다.** 반드시 `allowMultiple: false`로 시작.
- filter는 slug 키 + 값 배열의 단순 매칭 (Query API의 filter와 전혀 다른 형식).
- 수정 전 Query API로 같은 조건을 조회해 매칭 건수를 확인할 것 (CLI update가 자동으로 함).

## 삭제

```
POST /objects/{slug}/records/delete      ← Request body 때문에 DELETE 대신 POST
{"filter": {"email-addresses": ["jang@toss.im"]}, "allowMultiple": false}
```
- 응답: `{"result": "ok"}`
- CLI delete는 1건 매칭일 때만 실행하도록 제한되어 있다. 이 제한을 우회하지 말 것.

## 에러 처리

HTTP 코드 + `{"detail": {"code": "...", "message": "..."}}` 확인. 에러 코드 목록은 공식 문서 기준 추후 보완 예정 상태.

## 값 형식 (실측 검증 결과, 2026-07-18)

| 속성 타입 | values에 넣을 값 | 비고 |
|---|---|---|
| text / email / url 등 | 문자열 배열 `["..."]` | |
| select | **옵션 이름 그대로** `["ready"]` | 옵션 ID 불필요. 이름으로 검증 완료 |
| relation_record (company 등) | **recordId** `["670a39df..."]` | 이름 문자열은 에러. `lookup`으로 recordId 확보 후 사용 |
| 커스텀 속성 (hex slug) | slug 자리에 attributeId 그대로 | 예: `{"6a4752e9167d967401020f14": ["ready"]}` |

## 검증 이력

- 2026-07-18 notes: create → query → delete(1건 매칭) → 0건 확인 왕복 검증.
- 2026-07-18 people: 이메일 없는 create(회사 자동생성 없음 확인) → select를 옵션 이름으로 update → relation을 recordId로 update → delete 왕복 검증.
