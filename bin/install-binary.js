#!/usr/bin/env node

const https = require("https");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { execFileSync } = require("child_process");

const REPO = "workersio/spec";
const BINARY_NAME = "workers-spec";

const COMMANDS_DIR = path.join(__dirname, "..", "commands");

function getPlatformTarget() {
  const platform = os.platform();
  const arch = os.arch();

  const archMap = { x64: "x86_64", arm64: "aarch64" };
  const resolvedArch = archMap[arch];
  if (!resolvedArch) throw new Error(`Unsupported architecture: ${arch}`);

  switch (platform) {
    case "linux":
      return `${resolvedArch}-unknown-linux-musl`;
    case "darwin":
      return `${resolvedArch}-apple-darwin`;
    default:
      throw new Error(`Unsupported platform: ${platform}`);
  }
}

function httpsGet(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "User-Agent": "workers-spec-npm" } }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          return httpsGet(res.headers.location).then(resolve, reject);
        }
        if (res.statusCode !== 200) {
          return reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        }
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => resolve(Buffer.concat(chunks)));
        res.on("error", reject);
      })
      .on("error", reject);
  });
}

async function getLatestVersion() {
  const data = await httpsGet(
    `https://api.github.com/repos/${REPO}/releases/latest`
  );
  return JSON.parse(data.toString()).tag_name;
}

async function downloadBinary() {
  const vendorDir = path.join(__dirname, "..", "vendor");
  const binaryPath = path.join(vendorDir, BINARY_NAME);

  if (fs.existsSync(binaryPath)) {
    console.log("workers-spec binary already installed.");
    return;
  }

  if (process.env.WORKERS_SPEC_SKIP_DOWNLOAD) {
    console.log("Skipping binary download (WORKERS_SPEC_SKIP_DOWNLOAD set).");
    return;
  }

  const target = getPlatformTarget();
  const version = await getLatestVersion();
  const url = `https://github.com/${REPO}/releases/download/${version}/${BINARY_NAME}-${target}.tar.gz`;

  console.log(`Downloading ${BINARY_NAME} ${version} for ${target}...`);

  const tarball = await httpsGet(url);
  const tmpFile = path.join(os.tmpdir(), `workers-spec-${Date.now()}.tar.gz`);
  fs.writeFileSync(tmpFile, tarball);
  fs.mkdirSync(vendorDir, { recursive: true });
  execFileSync("tar", ["xzf", tmpFile, "-C", vendorDir]);
  fs.unlinkSync(tmpFile);
  fs.chmodSync(binaryPath, 0o755);

  console.log(`Installed ${BINARY_NAME} ${version}`);
}

function installCommands() {
  const commandsDir = path.join(os.homedir(), ".claude", "commands");
  fs.mkdirSync(commandsDir, { recursive: true });

  const commands = fs.readdirSync(COMMANDS_DIR).filter((f) => f.endsWith(".md"));
  for (const file of commands) {
    const content = fs.readFileSync(path.join(COMMANDS_DIR, file), "utf8");
    fs.writeFileSync(path.join(commandsDir, file), content);
  }
  const names = commands.map((f) => "/" + f.replace(".md", "")).join(" and ");

  console.log(`Installed ${names} commands to ~/.claude/commands/`);
}

async function main() {
  try {
    await downloadBinary();
  } catch (err) {
    console.error(`Failed to download binary: ${err.message}`);
    console.error(`Install from source: cargo install --git https://github.com/${REPO} workers-spec-cli`);
  }

  try {
    installCommands();
  } catch (err) {
    console.error(`Failed to install commands: ${err.message}`);
  }

  console.log("\nReady! Use /share in Claude Code to share a session.");
}

main();
