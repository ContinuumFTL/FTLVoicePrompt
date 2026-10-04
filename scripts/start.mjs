import { existsSync, readdirSync, statSync } from "node:fs";
import { dirname, delimiter, join, resolve, sep } from "node:path";
import { homedir } from "node:os";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export function resolvePython(root, override, probe = (file) => spawnSync(file, ["-c", "import sys"], { windowsHide: true }).status === 0) {
  const candidates = override ? [override] : [
    join(root, ".venv", "Scripts", "python.exe"),
    join(root, ".venv", "python.exe"),
    join(root, "backend", ".venv", "Scripts", "python.exe"),
    join(root, "backend", ".venv", "python.exe"),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate) && probe(candidate)) {
      return resolve(candidate);
    }
  }
  throw new Error("Project Python is unavailable. Run pnpm run setup, or set FTL_VOICE_PROMPT_PYTHON to a working interpreter.");
}

export function newestSource(root) {
  let newest = 0;
  const scan = (path) => {
    if (!existsSync(path)) return;
    const info = statSync(path);
    if (info.isFile()) newest = Math.max(newest, info.mtimeMs);
    else for (const name of readdirSync(path)) scan(join(path, name));
  };
  for (const path of ["src", "src-tauri/src", "src-tauri/icons", "src-tauri/capabilities",
    "src-tauri/Cargo.toml", "src-tauri/Cargo.lock", "src-tauri/build.rs", "src-tauri/tauri.conf.json",
    "package.json", "pnpm-lock.yaml", "index.html", "tsconfig.json", "vite.config.ts"]) scan(join(root, path));
  return newest;
}

function run(file, args, options) {
  const result = spawnSync(file, args, { ...options, stdio: "inherit", windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${file} failed (${result.status ?? result.signal}).`);
}

function main() {
  if (process.platform !== "win32") throw new Error("The desktop application currently supports Windows only.");
  const args = process.argv.slice(2);
  if (args.some((arg) => !["--dev", "--check"].includes(arg))) throw new Error("Usage: start.mjs [--dev] [--check]");
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const python = resolvePython(root, process.env.FTL_VOICE_PROMPT_PYTHON);
  const env = { ...process.env, FTL_VOICE_PROMPT_PYTHON: python, PYTHONUTF8: "1" };
  const pathKey = Object.keys(env).find((key) => key.toLowerCase() === "path") ?? "PATH";
  env[pathKey] = `${join(homedir(), ".cargo", "bin")}${delimiter}${env[pathKey] ?? ""}`;
  const options = { cwd: root, env };
  run(python, ["-m", "voice_prompt_sidecar.manage", "doctor"], { ...options, cwd: join(root, "backend") });
  const cli = join(root, "node_modules", "@tauri-apps", "cli", "tauri.js");
  if (!existsSync(cli)) throw new Error("Frontend dependencies are missing. Run pnpm install --frozen-lockfile.");
  const target = process.env.CARGO_TARGET_DIR ? resolve(root, process.env.CARGO_TARGET_DIR) : join(root, "src-tauri", "target");
  const binary = join(target, "release", "ftl-voice-prompt.exe");
  const needsBuild = !existsSync(binary) || statSync(binary).mtimeMs < newestSource(root);
  if (args.includes("--check")) {
    run("cargo.exe", ["--version"], options);
    console.log(JSON.stringify({ mode: args.includes("--dev") ? "development" : "release", needsBuild,
      pythonLayout: python.includes(`${sep}Scripts${sep}`) ? "venv" : "project", startsApplication: false }));
    return;
  }
  if (args.includes("--dev")) run(process.execPath, [cli, "dev"], options);
  else {
    if (needsBuild) {
      console.log("Preparing the release executable from the current source. The first build can take several minutes.");
      run(process.execPath, [cli, "build", "--no-bundle"], options);
    }
    run(binary, [], options);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
