# EIC `CREATE INDEX CONCURRENTLY` rollout plan

작성 시각: 2026-06-01 13:09 UTC / 22:09 KST  
대상 테이블: `public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd`

## 0. 범위와 전제

- 이 계획은 **인덱스 1개 추가 작업만** 다룬다.
- DDL 대상은 아래 테이블 하나로 제한한다.

```sql
public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd
```

- 실행 방식은 `psql` + `CREATE INDEX CONCURRENTLY`.
- `CREATE INDEX CONCURRENTLY`는 명시적 transaction 안에서 실행하면 안 된다.
- Slack Web API `conversations.replies`를 `SLACK_BOT_TOKEN`으로 직접 조회했다.
  - channel: `C07LCLRS79T`
  - thread_ts: `1780049341.699459`
  - fetched messages: 44
  - raw cache: `/home/ubuntu/.hermes/profiles/andrej/slack_api_cache/thread_C07LCLRS79T_1780049341_699459.json`
  - summary cache: `/home/ubuntu/.hermes/profiles/andrej/slack_api_cache/thread_C07LCLRS79T_1780049341_699459_summary.json`

## 1. 스레드/이전 작업 히스토리 요약

확인한 히스토리의 핵심은 다음이다.

1. 기존 hot query는 EIC에서 대략 아래 access pattern을 가진다.

```sql
WHERE notifly_user_id IN (...)
  AND name IN (...)
  AND dt ...
```

2. 이전 접근으로 `id` lexical range 기반 fast path를 검토/구현했지만, EIC migration/merge 로직 때문에 아래와 같은 row가 실제로 존재할 수 있음이 확인됐다.

```text
notifly_user_id = new_user
id              = old_user_..._new_user
```

즉 `notifly_user_id` 컬럼 기준으로는 맞는 row인데, `id` prefix 기준 range에서는 빠질 수 있다.

3. 따라서 이 작업의 안전한 목적은 코드 fast path가 아니라, 실제 predicate 컬럼을 그대로 태우는 composite btree index 추가다.

```sql
(notifly_user_id, name, dt)
```

이 접근은 user-scope query를 빠르게 만들면서도 `id` prefix normalization 가정에 의존하지 않는다.

## 2. 사전 확인 결과

### 2.1 DB / writer 확인

- Aurora PostgreSQL cluster: `notifly-db-prod-cluster`
- 현재 writer instance: `notifly-db-prod-c`
- instance class: `db.r6g.4xlarge`
- Performance Insights: enabled
- psql direct cluster writer endpoint 접속 확인: `transaction_read_only = off`
- `.env`의 `POSTGRES_RW_HOST` 재접근 테스트 완료.
  - value: `notifly-db-prod-cluster.cluster-cwvdx2o498bl.ap-northeast-2.rds.amazonaws.com`
  - DNS: `10.0.130.137`
  - psql 접속 성공, backend `inet_server_addr() = 10.0.130.137/32`
  - `transaction_read_only = off`, 즉 direct writer RW 접속 가능
  - default `statement_timeout = 15min`, `lock_timeout = 0`
- `.env`의 `POSTGRES_RW_HOST`가 이제 direct writer cluster endpoint를 가리키므로 DDL 실행 host로 사용 가능하다.

### 2.2 대상 테이블 크기

```text
estimated rows: ~418,215,008
heap size:      87 GB
index size:     76 GB
total size:     163 GB
```

새 `(notifly_user_id, name, dt)` index는 수십 GB 규모가 될 가능성이 높다. 계획값은 대략 45~60GB로 잡는다.

### 2.3 현재 대상 테이블 index

```text
eic_dt_idx_ffde3a7a000b5b2198961b3fff400acd             4293 MB  ON (dt)
eic_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd        4995 MB  ON (name, dt)
event_intermediate_counts_ffde..._noti                  4481 MB  ON (notifly_user_id)
event_intermediate_counts_ffde..._pkey                  63 GB    ON (id), unique
```

### 2.4 naming convention

EIC non-PK index convention은 아래 형태다.

```text
eic_<column>_idx_<project_id>
eic_<column1>_<column2>_idx_<project_id>
```

예:

```text
eic_dt_idx_<project_id>
eic_name_dt_idx_<project_id>
```

따라서 새 index명은 다음으로 한다.

```text
eic_user_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd
```

`user`는 실제 컬럼명이 아니라 `notifly_user_id`를 축약한 기존 EIC naming style에 맞춘 readable alias다. 전체 컬럼명을 다 넣으면 이름이 길어지고, 기존 `eic_name_dt_idx_*`와도 결이 다르다.

## 3. 최종 DDL

사전 점검에서 동일 이름의 valid/invalid index가 없는 것을 확인한 뒤 아래만 실행한다.

```sql
CREATE INDEX CONCURRENTLY eic_user_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd
ON public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd
USING btree (notifly_user_id, name, dt);
```

주의:

- `CREATE INDEX CONCURRENTLY`는 autocommit 상태에서 단독 statement로 실행한다.
- `IF NOT EXISTS`는 invalid index가 남은 경우를 조용히 숨길 수 있으므로, preflight에서 상태를 확인하고 **정상적으로 absent일 때만** 위 DDL을 실행한다.
- 세션 설정은 `PGOPTIONS`로 넣어서 DDL 자체는 단일 `-c` statement로 실행한다.

## 4. 실행 방식

### 4.1 권장 실행 시간

최근 3일 writer metric 기준 권장 시작 시간:

```text
1순위: KST 2026-06-02 02:00 시작
보수적: KST 2026-06-02 01:30 시작
늦어도: KST 03:00 전 시작
피할 시간: KST 08:00~12:00, 18:00~23:00
```

이유:

- 테이블 규모상 2~6시간 예상.
- 03시에 시작하면 08~09시 고부하 구간에 걸릴 가능성이 있다.
- 01:30~02:00 시작이 06~08시 전에 끝날 확률이 가장 높다.

### 4.2 세션 끊김 대비

primary: `systemd-run --user` transient unit로 실행한다. 이 환경에서 `systemd-run`, `tmux`, `nohup`, `psql` 모두 사용 가능함을 확인했다.

실행 전, `~/.hermes/profiles/andrej/ops/eic-index-rollout-<timestamp>/run_create_index.sh` 형태의 script를 준비한다. script는 기존 env file을 source하고 secret을 로그/명령행에 노출하지 않는다.

예시 skeleton:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
set +x

source /home/ubuntu/.hermes/profiles/andrej/.env
export PGPASSWORD="$POSTGRES_PASSWORD"
export PGOPTIONS="-c lock_timeout=5s -c statement_timeout=0"
DDL_HOST="notifly-db-prod-cluster.cluster-cwvdx2o498bl.ap-northeast-2.rds.amazonaws.com"

psql \
  "host=$DDL_HOST port=$POSTGRES_PORT user=$POSTGRES_USER dbname=$POSTGRES_DB sslmode=require connect_timeout=10 application_name=eic_user_name_dt_idx_ffde3a7a_rollout" \
  -v ON_ERROR_STOP=1 \
  -P pager=off \
  -c "CREATE INDEX CONCURRENTLY eic_user_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd ON public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd USING btree (notifly_user_id, name, dt);"
```

실행:

```bash
systemd-run --user \
  --unit=notifly-eic-index-ffde3a7a \
  --description='Create EIC user/name/dt index concurrently for ffde3a7a' \
  --collect \
  /bin/bash /home/ubuntu/.hermes/profiles/andrej/ops/eic-index-rollout-<timestamp>/run_create_index.sh
```

fallback:

```bash
tmux new-session -d -s notifly-eic-index-ffde3a7a \
  '/bin/bash /home/ubuntu/.hermes/profiles/andrej/ops/eic-index-rollout-<timestamp>/run_create_index.sh >> /home/ubuntu/.hermes/profiles/andrej/ops/eic-index-rollout-<timestamp>/create.log 2>&1'
```

Hermes에서 직접 실행할 경우에는 `terminal(background=true, notify_on_complete=true)`로도 실행해 process exit 알림을 받는다. 단, DB 작업 자체는 위 script/process 안의 `psql`이 수행한다.

## 5. 실행 전 preflight

### 5.1 index 상태 확인

```sql
SELECT
  c.relname,
  i.indisready,
  i.indisvalid,
  i.indisunique,
  pg_size_pretty(pg_relation_size(c.oid)) AS index_size
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE i.indrelid = 'public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd'::regclass
ORDER BY c.relname;
```

동일 이름 index가 invalid로 남아 있으면 먼저 복구 절차의 `DROP INDEX CONCURRENTLY`를 수행한다.

### 5.2 long transaction / old snapshot 확인

```sql
SELECT
  pid,
  usename,
  application_name,
  state,
  now() - xact_start AS xact_age,
  wait_event_type,
  wait_event
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY xact_start
LIMIT 20;
```

실행 직전 기준 `xact_age > 10~15m`가 있으면 시작을 미룬다. 현재 테스트 시점에서는 `10m+ long xact = 0`이었다.

### 5.3 writer baseline 확인

시작 10~15분 전 기준:

```text
CPUUtilization < 35%
DBLoad < 15~20
WriteIOPS roughly <= 15k~20k/s
ReadIOPS roughly <= 2k/s
ReadLatency / WriteLatency baseline 수준
DatabaseConnections 급증 없음
```

## 6. 모니터링 방법

### 6.1 psql progress

```sql
SELECT
  pid,
  relid::regclass AS table_name,
  index_relid::regclass AS index_name,
  phase,
  lockers_total,
  lockers_done,
  current_locker_pid,
  blocks_total,
  blocks_done,
  round(100.0 * blocks_done / nullif(blocks_total, 0), 2) AS blocks_pct,
  tuples_total,
  tuples_done,
  round(100.0 * tuples_done / nullif(tuples_total, 0), 2) AS tuples_pct
FROM pg_stat_progress_create_index
WHERE relid = 'public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd'::regclass;
```

주의해서 볼 phase:

```text
building index
waiting for writers before build
waiting for writers before validation
waiting for old snapshots
index validation: scanning table
```

`waiting ...` phase가 30분 이상 정체되면 원인 transaction/writer를 확인한다.

### 6.2 wait / lock 상태

```sql
SELECT
  pid,
  state,
  wait_event_type,
  wait_event,
  now() - query_start AS query_age,
  left(query, 160) AS query_prefix
FROM pg_stat_activity
WHERE wait_event_type IS NOT NULL
ORDER BY query_start
LIMIT 50;
```

### 6.3 CloudWatch / PI 지표

writer `notifly-db-prod-c` 기준으로 아래를 1분~5분 단위로 본다.

RDS CloudWatch:

```text
CPUUtilization
DBLoad / DBLoadCPU / DBLoadNonCPU
DatabaseConnections
ReadIOPS / WriteIOPS
ReadLatency / WriteLatency
FreeableMemory
VolumeReadIOPs / VolumeWriteIOPs
CommitLatency / CommitThroughput
Deadlocks
AuroraReplicaLag / ReplicaLagMaximum
```

Application-side:

```text
kds-consumer Lambda duration p95/p99
kds-consumer errors/timeouts
RDS Proxy connection/timeouts
API 5xx / timeout logs
Postgres statement timeout / recovery conflict logs
reader CPU and replica lag
```

Performance Insights:

```text
db.load.avg
os.cpuUtilization.total.avg
db.sampledload.avg grouped by db.wait_event_type
top SQL tokenized dimensions if DBLoad spikes
```

### 6.4 접근 테스트 결과

CloudWatch metric access 테스트 완료:

```text
writer: notifly-db-prod-c
range: last 30m, period 60s
points: 29~30 per metric
latest sample at test time:
  CPUUtilization       ~31.24%
  DBLoad               ~7.37
  WriteIOPS            ~17.85k/s
  ReadIOPS             ~695/s
  ReadLatency          ~1.81 ms
  WriteLatency         ~0.56 ms
  DatabaseConnections  ~700
```

Performance Insights access 테스트 완료:

```text
last 15m:
  db.load.avg                  latest ~0.85
  os.cpuUtilization.total.avg  latest ~33.4
```

psql monitoring access 테스트 완료:

```text
pg_stat_progress_create_index rows for target: 0
10m+ long transactions: 0
wait_event summary reachable
```

## 7. 중단 기준

아래 중 하나가 지속되면 즉시 중단 검토한다.

```text
writer CPUUtilization 80%+ sustained
DBLoad 평소 대비 2~3x sustained
ReadLatency / WriteLatency 3x+ sustained
replica lag가 tens of seconds ~ minutes로 증가
kds-consumer timeout/error 증가
RDS Proxy connection/timeout 증가
pg_stat_progress_create_index waiting phase 30m+ 정체
long transaction이 validation/build phase를 막고 있음
```

중단 전 확인:

1. index build backend pid 확인
2. 현재 phase 확인
3. CloudWatch/PI 지표가 실제 서비스 영향과 맞물리는지 확인
4. user-facing/API/Lambda error 증가 여부 확인

## 8. 중지 / 리커버리 계획

### 8.1 graceful cancel

```sql
SELECT pid, phase
FROM pg_stat_progress_create_index
WHERE relid = 'public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd'::regclass;
```

```sql
SELECT pg_cancel_backend(<pid>);
```

`pg_cancel_backend` 후 psql process 종료와 DB load 회복을 확인한다.

### 8.2 emergency terminate

`pg_cancel_backend`가 먹히지 않고 서비스 영향이 명확할 때만 사용한다.

```sql
SELECT pg_terminate_backend(<pid>);
```

### 8.3 invalid index cleanup

중단/실패 후에는 invalid index가 남을 수 있다.

```sql
SELECT
  c.relname,
  i.indisready,
  i.indisvalid,
  pg_size_pretty(pg_relation_size(c.oid)) AS size
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname = 'eic_user_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd';
```

invalid이면 autocommit 상태에서 다음을 실행한다.

```sql
DROP INDEX CONCURRENTLY IF EXISTS public.eic_user_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd;
```

그 다음 부하 안정화 후 재시도한다.

## 9. 완료 판단

완료 조건은 모두 만족해야 한다.

1. `pg_stat_progress_create_index`에서 대상 row가 사라짐.
2. `pg_index`에서 새 index가 `indisready = true`, `indisvalid = true`.
3. `pg_relation_size(index)`가 0이 아니고 수십 GB 수준으로 생성됨.
4. CloudWatch/PI 지표가 baseline으로 돌아옴.
5. representative hot query의 `EXPLAIN`에서 새 index 사용 가능성이 보임.

완료 확인 SQL:

```sql
SELECT
  c.relname,
  i.indisready,
  i.indisvalid,
  pg_size_pretty(pg_relation_size(c.oid)) AS size
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname = 'eic_user_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd';
```

planner 확인 예시:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT notifly_user_id
FROM public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd
WHERE notifly_user_id = '<known_user>'
  AND name = '<known_event_name>'
  AND dt >= '<lower_dt>'
GROUP BY notifly_user_id;
```

대표 파라미터는 이전 성능 비교에서 사용한 known hot query를 사용하되, broad scan이 되지 않도록 user/name/dt predicate를 반드시 포함한다.

## 10. 완료 알림 설정

실행 시 아래 둘을 같이 둔다.

1. process-level 알림
   - Hermes 실행이면 `terminal(background=true, notify_on_complete=true)` 사용.
   - systemd/tmux 실행이면 monitor script가 log를 남김.

2. DB-state polling 알림
   - 5분마다 아래를 체크한다.
     - progress row 존재 여부
     - `indisvalid/indisready`
     - invalid index 발생 여부
     - CloudWatch CPU/DBLoad/latency 임계치
   - `indisvalid=true AND indisready=true`가 되면 Slack origin thread에 완료 메시지를 보낸다.
   - invalid index 또는 abort threshold 지속 시 경고 메시지를 보낸다.

polling query:

```sql
SELECT
  now() AS checked_at,
  COALESCE((
    SELECT phase
    FROM pg_stat_progress_create_index
    WHERE relid = 'public.event_intermediate_counts_ffde3a7a000b5b2198961b3fff400acd'::regclass
    LIMIT 1
  ), 'no_progress_row') AS phase,
  i.indisready,
  i.indisvalid,
  pg_size_pretty(pg_relation_size(c.oid)) AS index_size
FROM pg_class c
JOIN pg_index i ON i.indexrelid = c.oid
WHERE c.relname = 'eic_user_name_dt_idx_ffde3a7a000b5b2198961b3fff400acd';
```

index row가 아직 없으면 `creating/not_started`로 해석한다.

## 11. 최종 실행 checklist

- [ ] 작업 시간 확정: KST 01:30~02:00 시작.
- [ ] 동일 이름 index 상태 확인: absent 또는 invalid cleanup 완료.
- [ ] long transaction 없음.
- [ ] writer baseline 정상.
- [ ] monitor SQL / CloudWatch / PI 접근 확인.
- [ ] background/deemon 실행 방식 준비: systemd-run primary, tmux fallback.
- [ ] 완료/실패 알림 poller 준비.
- [ ] `CREATE INDEX CONCURRENTLY` 단일 DDL 실행.
- [ ] 진행률/서비스 지표 모니터링.
- [ ] 완료 후 `indisvalid=true`, planner 사용 여부 확인.
- [ ] 실패 시 `pg_cancel_backend` → invalid index 확인 → `DROP INDEX CONCURRENTLY` cleanup.
