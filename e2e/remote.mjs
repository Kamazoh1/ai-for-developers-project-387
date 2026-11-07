// The same browser scenario against an app that is already running: the container, or the
// public Render URL (`mise run e2e:url -- https://<name>.onrender.com`).
//
// Nothing is started here and nothing is mocked. The scenario creates its own event type and
// a booking through the app, so on a deployed app they stay there until the next restart.
import { spawn } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
// A sleeping free Render service needs about a minute to wake up on the first request.
const WAKE_UP_TIMEOUT_MS = 3 * 60_000;

const target = process.argv[2];
if (!target || !/^https?:\/\//.test(target)) {
  console.error("Usage: mise run e2e:url -- <http(s)://host[:port]>");
  process.exit(2);
}
const baseUrl = target.replace(/\/+$/, "");

async function waitForHealth() {
  const deadline = Date.now() + WAKE_UP_TIMEOUT_MS;
  let last = "no answer";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(15_000) });
      if (response.ok) return;
      last = `HTTP ${response.status}`;
    } catch (error) {
      last = error instanceof Error ? error.message : String(error);
    }
    await new Promise((done) => setTimeout(done, 3_000));
  }
  throw new Error(`${baseUrl}/health did not answer in ${WAKE_UP_TIMEOUT_MS / 1000} s (${last})`);
}

try {
  console.log(`Waiting for ${baseUrl}/health ...`);
  await waitForHealth();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
}

const tests = spawn("npx", ["playwright", "test", ...process.argv.slice(3)], {
  cwd: here,
  env: { ...process.env, E2E_BASE_URL: baseUrl },
  stdio: "inherit",
});
tests.on("exit", (code) => process.exit(code ?? 1));
