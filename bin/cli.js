#!/usr/bin/env node

const { execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

function getBinaryPath() {
  // Check local vendor dir first (installed via postinstall)
  const vendorPath = path.join(__dirname, "..", "vendor", "workers-spec");
  if (fs.existsSync(vendorPath)) {
    return vendorPath;
  }

  // Check if binary is on PATH
  const ext = os.platform() === "win32" ? ".exe" : "";
  const name = "workers-spec" + ext;

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

  console.error(
    "Error: workers-spec binary not found.\n" +
      "Run `npm install` to download it, or install from source:\n" +
      "  cargo install --git https://github.com/workersio/spec workers-spec-cli"
  );
  process.exit(1);
}

const binary = getBinaryPath();
const args = process.argv.slice(2);

try {
  execFileSync(binary, args, { stdio: "inherit" });
} catch (err) {
  if (err.status != null) {
    process.exit(err.status);
  }
  throw err;
}
