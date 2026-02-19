import { rm, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Platform } from "./types";
import { NODE_OS, npmName } from "./platforms";

export async function generateNativePackage({
  platform,
  version,
  outputDir,
}: {
  platform: Platform;
  version: string;
  outputDir: string;
}) {
  const { os, arch } = platform;
  console.log(`Generating native package for ${os}-${arch}...`);

  await rm(outputDir, { recursive: true, force: true });
  await mkdir(path.join(outputDir, "bin"), { recursive: true });

  const packageJson = {
    name: npmName(platform),
    version,
    description: `${os} ${arch} binary for @workersio/spec`,
    os: [NODE_OS[os]],
    cpu: [arch],
    files: ["bin"],
    preferUnplugged: true,
    license: "MIT",
  };

  await writeFile(
    path.join(outputDir, "package.json"),
    JSON.stringify(packageJson, null, 2) + "\n"
  );

  console.log(`Native package generated in ${outputDir}`);
}
