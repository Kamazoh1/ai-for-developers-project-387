// Builds the Docker image, starts a container on a port other than the image's default, and
// runs the browser scenario against it (`mise run docker:smoke`). This is what a checker does
// with the Dockerfile: build, run with PORT, open the app. The container is always removed.
//
// DOCKER_BIN overrides the docker binary (for example docker.exe when Docker Desktop is not
// integrated with WSL).
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const docker = process.env.DOCKER_BIN ?? "docker";
const IMAGE = "call-calendar:smoke";
const NAME = `call-calendar-smoke-${process.pid}`;

function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolvePort(port));
    });
  });
}

function run(args, options = {}) {
  return spawnSync(docker, args, { cwd: root, stdio: "inherit", ...options });
}

let started = false;
let exitCode = 1;
try {
  console.log(`Building ${IMAGE} ...`);
  if (run(["build", "-t", IMAGE, "."]).status !== 0) throw new Error("docker build failed");

  // Neither the image's default (10000) nor a round number: the app must really read $PORT.
  const port = await freePort();
  console.log(`Starting a container with PORT=${port} ...`);
  const up = run(["run", "-d", "--name", NAME, "-e", `PORT=${port}`, "-p", `${port}:${port}`, IMAGE], {
    stdio: ["ignore", "pipe", "inherit"],
  });
  if (up.status !== 0) throw new Error("docker run failed");
  started = true;

  const tests = spawn("node", ["remote.mjs", `http://127.0.0.1:${port}`], {
    cwd: here,
    stdio: "inherit",
  });
  exitCode = await new Promise((done) => tests.on("exit", (code) => done(code ?? 1)));
  if (exitCode !== 0) run(["logs", "--tail", "50", NAME]);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
} finally {
  if (started) run(["rm", "-f", NAME], { stdio: "ignore" });
}
process.exit(exitCode);
