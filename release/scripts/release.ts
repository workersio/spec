import path from "node:path";
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { PLATFORMS } from "./platforms";
import { packPlatform, publishArtifacts } from "./operations";

const { values } = parseArgs({
  args: Bun.argv.slice(2),
  options: {
    "skip-publish": { type: "boolean", default: false },
    tag: { type: "string", default: "latest" },
  },
});

const skipPublish = values["skip-publish"]!;
const npmTag = values.tag!;

function getVersion(): string {
  const cargoPath = path.join(__dirname, "..", "..", "cli", "Cargo.toml");
  const cargo = readFileSync(cargoPath, "utf-8");
  const match = cargo.match(/^version\s*=\s*"(.+)"/m);
  if (!match) {
    console.error("Could not read version from cli/Cargo.toml");
    process.exit(1);
  }
  return match[1];
}

async function main() {
  const version = getVersion();
  console.log(`Version: ${version}`);
  console.log(`NPM tag: ${npmTag}`);
  console.log(`Skip publish: ${skipPublish}`);
  console.log(
    `Platforms: ${PLATFORMS.map((p) => `${p.os}-${p.arch}`).join(", ")}\n`
  );

  const artifacts: string[] = [];

  for (const platform of PLATFORMS) {
    const artifact = await packPlatform({
      platform,
      version,
      srcDir: path.join(__dirname, ".."),
    });
    artifacts.push(artifact);
  }

  console.log(`\nAll platforms packed. ${artifacts.length} artifacts created.`);

  if (!skipPublish) {
    console.log("\nPublishing artifacts...");
    publishArtifacts(artifacts, npmTag);
    console.log("Published successfully.");
  } else {
    console.log("\nSkipping publish (--skip-publish).");
  }
}

main().catch((err) => {
  console.error("Release failed:", err);
  process.exit(1);
});
