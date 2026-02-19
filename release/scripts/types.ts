export type SupportedOS = "darwin" | "linux";
export type SupportedArch = "x64" | "arm64";
export type NpmOS = "darwin" | "linux";

export interface Platform {
  os: SupportedOS;
  arch: SupportedArch;
}
