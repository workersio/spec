#!/usr/bin/env node

const { execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");
const https = require("https");

const REPO = "workersio/spec";
const BINARY_NAME = "workers-spec";

function getVendorPath() {
  return path.join(__dirname, "..", "vendor", BINARY_NAME);
}

function getBinaryPath() {
  // Check local vendor dir first (installed via postinstall or first-run download)
  const vendorPath = getVendorPath();
  if (fs.existsSync(vendorPath)) {
    return vendorPath;
  }

  // Check if binary is on PATH
  const ext = os.platform() === "win32" ? ".exe" : "";
  const name = BINARY_NAME + ext;

  const selfPath = fs.realpathSync(__filename);
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    const full = path.join(dir, name);
    if (fs.existsSync(full)) {
      // Skip if this resolves back to our own cli.js (npm symlink)
      try {
        if (fs.realpathSync(full) === selfPath) continue;
      } catch {}
      return full;
    }
  }

  return null;
}

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

async function downloadBinary() {
  const target = getPlatformTarget();

  const versionData = await httpsGet(
    `https://api.github.com/repos/${REPO}/releases/latest`
  );
  const version = JSON.parse(versionData.toString()).tag_name;
  const url = `https://github.com/${REPO}/releases/download/${version}/${BINARY_NAME}-${target}.tar.gz`;

  console.log(`Downloading ${BINARY_NAME} ${version} for ${target}...`);

  const tarball = await httpsGet(url);
  const tmpFile = path.join(os.tmpdir(), `workers-spec-${Date.now()}.tar.gz`);
  const vendorDir = path.join(__dirname, "..", "vendor");

  fs.writeFileSync(tmpFile, tarball);
  fs.mkdirSync(vendorDir, { recursive: true });
  execFileSync("tar", ["xzf", tmpFile, "-C", vendorDir]);
  fs.unlinkSync(tmpFile);

  const binaryPath = getVendorPath();
  fs.chmodSync(binaryPath, 0o755);
  console.log(`Installed ${BINARY_NAME} ${version}\n`);
  return binaryPath;
}

async function main() {
  let binary = getBinaryPath();

  if (!binary) {
    try {
      binary = await downloadBinary();
    } catch (err) {
      console.error(
        `Error: Failed to download workers-spec binary: ${err.message}\n` +
          "Install from source:\n" +
          `  cargo install --git https://github.com/${REPO} workers-spec-cli`
      );
      process.exit(1);
    }
  }

  const args = process.argv.slice(2);

  try {
    execFileSync(binary, args, { stdio: "inherit" });
  } catch (err) {
    if (err.status != null) {
      process.exit(err.status);
    }
    throw err;
  }
}

main();
