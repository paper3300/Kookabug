/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `PluginLock`'s JSON-Schema
 * via the `definition` "LockSha256".
 */
export type LockSha256 = string;
/**
 * This interface was referenced by `PluginLock`'s JSON-Schema
 * via the `definition` "PluginId".
 */
export type PluginId = string;
/**
 * 원천 출처 (재설치·upgrade용, sync는 쓰지 않는다). 사용자 정보(인증)는 지운다
 *
 * This interface was referenced by `PluginLock`'s JSON-Schema
 * via the `definition` "LockSource".
 */
export type LockSource =
  | {
      commit: string;
      kind: "git";
      ref: string | null;
      url: string;
    }
  | {
      kind: "wheel";
      path?: string;
      sha256: LockSha256;
      url?: string;
    }
  | {
      kind: "path";
      path: string;
    };

/**
 * kookabug.lock (M6 계획 3.3): 설치한 플러그인과 해결된 의존성 환경. 커밋한다. 다른 PC는 잠금과 커밋된 plugins/wheels/만으로 같은 환경을 다시 만든다
 */
export interface PluginLock {
  environments: {
    [k: string]: LockEnvironment | undefined;
  };
  format: "kookabug.lock/0";
  /**
   * 의존성 인덱스 URL (사용자 정보 없음)
   */
  index: string;
  platform: string;
  /**
   * id 순
   */
  plugins: LockPlugin[];
  /**
   * Python 소판 (예: 3.14)
   */
  python: string;
  python_full: string;
  sdk: {
    version: string;
    wheel_sha256: LockSha256;
  };
}
/**
 * 실행 환경 하나. fingerprint = sha256(정규 JSON {python, platform, sdk, packages, 그 환경 플러그인 wheel_sha256 목록}) — 환경 찾기의 근거. digest = 환경 Lib/site-packages 실제 파일 바이트 해시 (재현 판정)
 *
 * This interface was referenced by `PluginLock`'s JSON-Schema
 * via the `definition` "LockEnvironment".
 */
export interface LockEnvironment {
  digest: LockSha256;
  fingerprint: LockSha256;
  packages: LockPackage[];
  plugins: PluginId[];
}
/**
 * 환경의 의존성 하나 (wheel만, uv pip compile --generate-hashes 결과)
 *
 * This interface was referenced by `PluginLock`'s JSON-Schema
 * via the `definition` "LockPackage".
 */
export interface LockPackage {
  /**
   * @minItems 1
   */
  hashes: [string, ...string[]];
  name: string;
  version: string;
}
/**
 * This interface was referenced by `PluginLock`'s JSON-Schema
 * via the `definition` "LockPlugin".
 */
export interface LockPlugin {
  /**
   * isolated_because = conflict일 때 공유 환경과 판이 맞지 않는 패키지 이름
   */
  conflicts?: string[];
  dist: string;
  env: string;
  id: PluginId;
  isolated_because: "declared" | "conflict" | null;
  manifest: LockManifest;
  requires: string[];
  schema_sha256: LockSha256;
  source: LockSource;
  version: string;
  /**
   * plugins/wheels/<wheel_sha256>/<원래 wheel 파일명> (워크스페이스 기준, 커밋)
   */
  wheel: string;
  wheel_sha256: LockSha256;
}
/**
 * 설치한 플러그인의 스키마 머리 (id·version 뺀 나머지). modules로 워커를 띄운다
 *
 * This interface was referenced by `PluginLock`'s JSON-Schema
 * via the `definition` "LockManifest".
 */
export interface LockManifest {
  isolation?: "auto" | "shared" | "isolated";
  min_core?: string;
  /**
   * @minItems 1
   */
  modules: [string, ...string[]];
  permissions: ("capture" | "input" | "process" | "filesystem" | "network" | "secrets")[];
  title?: string;
  ui?: string;
}
