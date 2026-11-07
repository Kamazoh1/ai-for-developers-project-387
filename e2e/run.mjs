// Single entry point of the browser suite (`mise run e2e`): starts the real backend on a
// temporary SQLite file and the real Vite dev server on free ports, runs Playwright against
// them, and stops both afterwards, whatever the outcome.
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const HOST = "127.0.0.1";
const STARTUP_TIMEOUT_MS = 60_000;

function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, HOST, () => {
      const { port } = server.address();
      server.close(() => resolvePort(port));
    });
  });
}

const servers = [];

/** Starts a server in its own process group, so uv/npm and the process they spawn stop together. */
function start(name, command, args, options) {
  const child = spawn(command, args, {
    ...options,
    detached: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const server = { name, child, output: [], exited: false };
  const keep = (chunk) => {
    server.output.push(chunk);
    if (server.output.length > 200) server.output.shift();
  };
  child.stdout.on("data", keep);
  child.stderr.on("data", keep);
  child.on("exit", () => (server.exited = true));
  servers.push(server);
  return server;
}

function signalAll(signal) {
  for (const { child } of servers) {
    try {
      process.kill(-child.pid, signal);
    } catch {
      // already gone
    }
  }
}

/** Stops both servers and waits until they are gone (SIGKILL if they ignore SIGTERM for 5 s). */
async function stopAll() {
  signalAll("SIGTERM");
  const deadline = Date.now() + 5_000;
  while (servers.some((server) => !server.exited) && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 50));
  }
  signalAll("SIGKILL");
}

async function waitFor(server, url) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (server.exited) {
      throw new Error(`${server.name} exited during startup:\n${server.output.join("")}`);
    }
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(
    `${server.name} did not answer ${url} within ${STARTUP_TIMEOUT_MS / 1000}s:\n${server.output.join("")}`,
  );
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    await stopAll();
    process.exit(130);
  });
}

let tempDir;
let exitCode = 1;
try {
  tempDir = await mkdtemp(join(tmpdir(), "call-calendar-e2e-"));
  const backendPort = await freePort();
  const frontendPort = await freePort();
  const apiUrl = `http://${HOST}:${backendPort}`;
  const baseUrl = `http://${HOST}:${frontendPort}`;

  const backend = start(
    "backend",
    "uv",
    [
      "run",
      "--project",
      join(root, "backend"),
      "uvicorn",
      "--factory",
      "app.main:create_app",
      "--host",
      HOST,
      "--port",
      String(backendPort),
    ],
    {
      cwd: join(root, "backend"),
      env: {
        ...process.env,
        DATABASE_PATH: join(tempDir, "e2e.db"),
        CALENDAR_TIMEZONE: "Europe/Moscow",
      },
    },
  );
  const frontend = start(
    "frontend",
    "npm",
    [
      "run",
      "dev",
      "--prefix",
      join(root, "frontend"),
      "--",
      "--host",
      HOST,
      "--port",
      String(frontendPort),
      "--strictPort",
    ],
    { cwd: join(root, "frontend"), env: { ...process.env, API_PROXY_TARGET: apiUrl } },
  );
  await waitFor(backend, `${apiUrl}/health`);
  // Through the Vite proxy: proves the browser's same-origin `/api` reaches the backend.
  await waitFor(frontend, `${baseUrl}/api/calendar`);

  const tests = spawn("npx", ["playwright", "test", ...process.argv.slice(2)], {
    cwd: here,
    env: { ...process.env, E2E_BASE_URL: baseUrl },
    stdio: "inherit",
  });
  exitCode = await new Promise((done) => tests.on("exit", (code) => done(code ?? 1)));
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
} finally {
  await stopAll();
  if (tempDir) await rm(tempDir, { recursive: true, force: true });
}
process.exit(exitCode);
