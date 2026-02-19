import type { Platform, SupportedOS, NpmOS } from "./types";

export const PLATFORMS: Platform[] = [
  { os: "darwin", arch: "arm64" },
  { os: "darwin", arch: "x64" },
  { os: "linux", arch: "x64" },
  { os: "linux", arch: "arm64" },
];

export const NODE_OS: Record<SupportedOS, NpmOS> = {
  darwin: "darwin",
  linux: "linux",
};

export function npmName(platform: Platform): string {
  return `@workersio/spec-${NODE_OS[platform.os]}-${platform.arch}`;
}

export function dirName(platform: Platform): string {
  return `spec-${NODE_OS[platform.os]}-${platform.arch}`;
}
