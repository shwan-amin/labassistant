import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiClient, ApiError } from "../api";

type Call = { url: string; init?: RequestInit };

function fakeFetch(status: number, body: unknown, calls: Call[] = []): typeof fetch {
  return (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
  }) as typeof fetch;
}

test("posts a check as JSON to the backend", async () => {
  const calls: Call[] = [];
  const api = new ApiClient("http://127.0.0.1:8000/", fakeFetch(200, { session: {}, next_question: null }, calls));
  await api.startCheck({ files: [], selected_path: "a.py", selection: { start: 1, end: 2 } });

  assert.equal(calls[0].url, "http://127.0.0.1:8000/checks");
  assert.equal(calls[0].init?.method, "POST");
  assert.equal(JSON.parse(String(calls[0].init?.body)).selected_path, "a.py");
});

test("answers encode the session id", async () => {
  const calls: Call[] = [];
  await new ApiClient("http://x", fakeFetch(200, {}, calls)).submitAnswer("a/b", 0, "hi");
  assert.equal(calls[0].url, "http://x/checks/a%2Fb/answers");
});

const errorCases: [number, string][] = [
  [413, "too large"],
  [422, "can't check this selection: selection lines 9-9 are outside"],
  [502, "couldn't use"],
  [503, "unavailable: daily quota"],
  [500, "backend error (500)"],
];

for (const [status, expected] of errorCases) {
  test(`HTTP ${status} becomes a friendly message`, async () => {
    const detail = status === 422 ? "selection lines 9-9 are outside" : "daily quota";
    const api = new ApiClient("http://x", fakeFetch(status, { detail }));
    await assert.rejects(api.getCheck("s"), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.ok(error.message.includes(expected), error.message);
      return true;
    });
  });
}

test("unreachable backend explains how to start it", async () => {
  const failing = (async () => {
    throw new TypeError("fetch failed");
  }) as typeof fetch;
  await assert.rejects(new ApiClient("http://127.0.0.1:8000", failing).getCheck("s"), /uv run labassistant-api/);
});

test("thumbnails become data URIs, or null on failure", async () => {
  const png = new Uint8Array([137, 80, 78, 71]);
  const ok = (async () => new Response(png, { status: 200 })) as typeof fetch;
  assert.equal(await new ApiClient("http://x", ok).thumbnailDataUri("/t/1"), "data:image/png;base64,iVBORw==");
  assert.equal(await new ApiClient("http://x", fakeFetch(404, "")).thumbnailDataUri("/t/1"), null);
});
