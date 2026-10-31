// kookabug CLI 찾기 (M2 계획 2.3 "CLI 찾기 순서"). electron을 import하지 않는다 (vitest)
import path from "node:path";

/** 패키지 앱의 설치 폴더 기준 CLI 위치. 설치 구성(T13)이 바뀌면 이 상수 하나만 고친다 */
export const PACKAGED_CLI = ["bin", "kookabug.exe"] as const;
/** 개발 모드: 레포 루트 기준 uv 가상 환경의 CLI */
export const DEV_CLI = [".venv", "Scripts", "kookabug.exe"] as const;
export const CLI_ENV = "KOOKABUG_CLI";

export interface CliLocateInput {
  env: Readonly<Record<string, string | undefined>>;
  /** app.isPackaged */
  packaged: boolean;
  /** 패키지 앱의 설치 폴더 (Kookabug.exe가 있는 곳) */
  installDir: string;
  /** 개발 모드의 레포 루트 */
  repoRoot: string;
  exists(file: string): boolean;
}

export interface CliLocation {
  /** 찾은 CLI. 없으면 null */
  path: string | null;
  /** 차례로 본 경로 (오류 화면에 모두 보여 준다) */
  tried: string[];
}

/** 환경 변수 → 패키지 앱의 설치 폴더 → 개발 모드 레포 `.venv` 순서. 먼저 있는 것을 쓴다 */
export function locateCli(input: CliLocateInput): CliLocation {
  const candidates: string[] = [];
  const fromEnv = input.env[CLI_ENV]?.trim();
  if (fromEnv) candidates.push(path.resolve(fromEnv));
  if (input.packaged) candidates.push(path.join(input.installDir, ...PACKAGED_CLI));
  else candidates.push(path.join(input.repoRoot, ...DEV_CLI));
  const tried: string[] = [];
  for (const file of candidates) {
    tried.push(file);
    if (input.exists(file)) return { path: file, tried };
  }
  return { path: null, tried };
}
