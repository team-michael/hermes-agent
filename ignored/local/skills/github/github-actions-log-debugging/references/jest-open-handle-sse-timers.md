# Jest open-handle CI hang: SSE lifecycle timers

## Symptom
A GitHub Actions job appears to take 30+ minutes, but the Jest output itself reports all suites passed and a short runner time, followed by:

```text
Jest did not exit one second after the test run has completed.
```

This means the tests are not still executing. The Node process is alive because something still has a referenced handle.

## Useful investigation path
1. Compare three clocks:
   - workflow/check-run job duration
   - package-manager task duration
   - Jest's own `Time: ...` line
2. If the Jest time is small but the job/task duration is huge, search changed code for open handles:
   - long `setTimeout` / `setInterval`
   - HTTP servers/listeners
   - Redis/DB clients
   - streams/SSE connections
   - abort/close cleanup that may not fire under unit-test request helpers
3. Build a minimal Node repro that opens the suspect path, reads/cancels enough to trigger setup, then waits briefly to see whether the process stays alive.
4. Fix the real handle. Do not use `jest --forceExit` as the primary fix.

## SSE timer pattern
For SSE/long-lived HTTP streams, heartbeat and TTL timers are expected to run while a real socket/server is alive. But those timers should not be the only reason a Node process remains alive after a unit test or shutdown path.

Preferred minimal production-safe fix:

```js
const heartbeatTimer = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
heartbeatTimer.unref?.();

const ttlTimer = setTimeout(closeConnection, MAX_CONNECTION_AGE_MS);
ttlTimer.unref?.();
```

`unref()` does not cancel the timer. It only says: if this timer is the last referenced handle, allow the process to exit. In production, the actual HTTP server/socket/client handles keep the process alive, so the timer still fires normally.

## Regression test shape
A robust regression test can spy/wrap timer creation and assert the returned handles get `unref()` called.

Key details:
- trigger enough of the stream to create both timers, often by reading the first chunk
- flush microtasks after the read if the stream creates timers asynchronously
- clear captured timer handles in test cleanup
- keep assertions about lifecycle narrow: timer handles are unref'ed; broader stream semantics belong in separate tests

## Reporting
When reporting the finding, separate observed facts from inference:
- observed: Jest suites passed in ~N seconds, then Node emitted the non-exit warning
- observed: enclosing CI task ran ~N minutes
- inferred: referenced open handle after tests
- confirmed: minimal repro stayed alive until timer `unref()` was added
