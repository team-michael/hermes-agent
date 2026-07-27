#!/usr/bin/env node
'use strict';

const Redis = require('ioredis');

const host = process.env.REDIS_HOST;
const port = Number(process.env.REDIS_PORT || '6379');
if (!host) {
  console.error('REDIS_HOST is required');
  process.exit(2);
}

const prefix = process.env.REDIS_TEST_PREFIX || `hermes:redis-proxy-smoke:${Date.now()}`;
const client = new Redis({
  host,
  port,
  lazyConnect: true,
  enableOfflineQueue: false,
  maxRetriesPerRequest: 1,
  connectTimeout: Number(process.env.REDIS_CONNECT_TIMEOUT_MS || '2000'),
  commandTimeout: Number(process.env.REDIS_COMMAND_TIMEOUT_MS || '2000'),
});

client.on('error', (err) => {
  console.error(JSON.stringify({ event: 'client_error', message: err.message }));
});

async function step(name, fn) {
  const started = Date.now();
  try {
    const result = await fn();
    console.log(JSON.stringify({ step: name, ok: true, ms: Date.now() - started, result }));
    return result;
  } catch (err) {
    console.log(JSON.stringify({ step: name, ok: false, ms: Date.now() - started, error: err.message, name: err.name }));
    throw err;
  }
}

async function main() {
  await step('connect', async () => {
    await client.connect();
    return { status: client.status };
  });

  await step('PING', () => client.ping());

  const stringKey = `${prefix}:string`;
  await step('SET/GET', async () => {
    await client.set(stringKey, 'ok', 'EX', 120);
    return await client.get(stringKey);
  });

  const hashKey = `${prefix}:{campaign}:delivery`;
  await step('HINCRBY/HGET/EXPIRE', async () => {
    const n = await client.hincrby(hashKey, 'sent', 3);
    await client.expire(hashKey, 120);
    const got = await client.hget(hashKey, 'sent');
    return { hincrby: n, hget: got };
  });

  await step('MULTI/EXEC hash-tagged', async () => {
    const txKey = `${prefix}:{tx}:counter`;
    const res = await client.multi().hincrby(txKey, 'n', 1).expire(txKey, 120).exec();
    const got = await client.hget(txKey, 'n');
    return { exec: res, hget: got };
  });

  await step('32 keys across slots via standalone client', async () => {
    const mismatches = [];
    for (let i = 0; i < 32; i += 1) {
      const key = `${prefix}:slot:${i}`;
      await client.set(key, String(i), 'EX', 120);
      const got = await client.get(key);
      if (got !== String(i)) mismatches.push({ key, expected: String(i), got });
    }
    return { tested: 32, mismatches };
  });

  await step('quit', () => client.quit());
}

main().catch(() => {
  try { client.disconnect(); } catch (_) {}
  process.exit(1);
});
