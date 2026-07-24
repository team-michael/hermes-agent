# Notifly `/authenticate` 빈 자격증명 요청의 source IP 추적

Notifly `api-service`에서 고객이 토큰 `null` 저장 시각과 함께 `/authenticate`의 빈 `accessKey`/`secretKey` 호출 IP를 요청할 때 쓰는 읽기 전용 CloudWatch 조사 패턴이다.

## 핵심 메커니즘

현재 요청 경로는 `services/server/api-service/lib/app.js`의 `/authenticate` → `lib/api/authenticate.js`다. 필수 키가 없거나 빈 문자열이면 400을 반환한다.

`http-metrics` 미들웨어는 요청마다 두 종류의 증거를 남길 수 있다.

- EMF 요청 메트릭: `StatusCode`, `NormalizedPath`, `ProjectId`, `Method`, `RawPath`; IP는 없음
- 구조화된 `error-response`: `projectId`, `status`, `path`, `normalizedPath`, `ip`, `userAgent`, `responseBody`; IP 확인은 이 레코드를 사용

`extractProjectId()`가 요청 body의 `accessKey`를 `accessKey:<value>`로 남기므로, `accessKey`는 있고 `secretKey`가 비어 있는 400 요청은 고객 accessKey로 좁힐 수 있다. 둘 다 비어 있으면 `ProjectId=unknown`일 수 있어 고객별 귀속은 불가능할 수 있다.

## 조사 절차

1. 고객이 준 UTC 시각의 ±1분을 정확히 계산한다.
2. `/aws/ecs/notifly-services-prod/api-service`에서 `/authenticate` + `StatusCode=400`을 먼저 조회해 후보 수와 시각을 확정한다.
3. 고객 accessKey가 제공되면 `ProjectId`/`projectId = accessKey:<value>`로 좁힌다. secret 값은 검색·출력하지 않는다.
4. 같은 창의 구조화된 `error-response`에서 `ip`, `userAgent`, `responseBody`만 선택한다.
5. `ip`가 `client, proxy` 형태이면 leftmost를 원 요청 IP로 보고, 뒤 값은 Cloudflare/proxy hop으로 구분한다.
6. 정확한 UTC 시각, leftmost IP, User-Agent, 후보 건수, 기존 IP와 신규 IP의 차이만 짧게 보고한다.

## Logs Insights 예시

후보 요청:

```sql
fields @timestamp, StatusCode, NormalizedPath, ProjectId, Method, RawPath
| filter NormalizedPath = "/authenticate" and StatusCode = "400"
| sort @timestamp asc
| limit 100
```

source IP 확인:

```sql
fields @timestamp, projectId, status, method, path, normalizedPath, ip, userAgent, responseBody
| filter projectId like /<access-key-prefix>/
    and status = 400
    and normalizedPath = "/authenticate"
| sort @timestamp asc
| limit 100
```

accessKey 전체를 명령/공유 로그에 반복 노출하지 않도록 충돌하지 않을 만큼의 prefix로 필터링하고, 최종 보고에는 전체 값을 다시 쓰지 않는다.

## 해석과 주의점

- EMF 레코드만 보고 “IP가 로그에 없다”고 결론 내리지 않는다. 같은 요청의 `error-response` 레코드를 별도로 조회한다.
- 400만으로 `secretKey`가 빈 값이었다고 단정하지 않는다. 배포된 응답 계약과 `responseBody`, 같은 시각의 `Invalid authentication keys` 로그를 함께 확인한다. 잘못된 secret 등 다른 400 경로가 있으면 분리한다.
- `X-Forwarded-For` 전체 문자열의 마지막 프록시 IP를 고객 서버 IP로 보고하지 않는다.
- request body나 secretKey 원문을 출력하지 않는다. 필요한 식별자는 accessKey 또는 짧은 prefix뿐이다.
- 사용자가 준 애플리케이션 저장 시각과 서버 로그 시각은 수백 ms 차이가 날 수 있으므로 가장 가까운 한 건만 고르지 말고 ±1분 전체 후보를 확인한다.
