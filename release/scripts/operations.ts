import path from "node:path";
import { mkdir, copyFile, stat, chmod } from "node:fs/promises";
import { execSync } from "node:child_process";
import type { Platform } from "./types";
import { generateNativePackage } from "./native";
import { dirName } from "./platforms";

export interface PackOptions {
  platform: Platform;
  version: string;
  srcDir?: string;
}

export async function packPlatform({
  platform,
  version,
  srcDir = process.cwd(),
}: PackOptions): Promise<string> {
  const { os, arch } = platform;
  console.log(`Packing platform: ${os}-${arch}`);

  const dir = dirName(platform);
  const tarballDir = path.join(srcDir, "dist", `${dir}-${version}`);
  const scaffoldDir = path.join(tarballDir, dir);

  await generateNativePackage({ platform, version, outputDir: scaffoldDir });

  // Copy prebuilt binary from cli/dist-{os}-{arch}/spec
  const binaryName = "spec";
  const sourcePath = path.join(
    srcDir,
    "..",
    "cli",
    `dist-${os}-${arch}`,
    binaryName
  );
  const destPath = path.join(scaffoldDir, "bin", binaryName);

  await mkdir(path.dirname(destPath), { recursive: true });
  await copyFile(sourcePath, destPath);

  const info = await stat(destPath);
  await chmod(destPath, info.mode | 0o111);

  // Create tarball
  const tarName = `${dir}-${version}.tar.gz`;
  const tarPath = path.join(srcDir, "dist", tarName);
  execSync(`tar -czf "${tarPath}" -C "${tarballDir}" "${dir}"`, {
    stdio: "inherit",
  });

  console.log(`Artifact created: ${tarPath}`);
  return path.resolve(tarPath);
}

export function publishArtifacts(artifacts: string[], npmTag: string) {
  for (const artifact of artifacts) {
    const cmd = `npm publish "${artifact}" --tag ${npmTag} --access public`;
    console.log(`Executing: ${cmd}`);
    execSync(cmd, { stdio: "inherit" });
  }
}
