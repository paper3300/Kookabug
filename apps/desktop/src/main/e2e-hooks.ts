// E2E 검사 전용 주 프로세스 훅 (T11). Playwright app.evaluate가 주 프로세스 전역에서 부른다: daemon·실행은 두고
// 연결만 끊는다. 렌더러는 contextIsolation이라 주 프로세스 전역에 닿지 않는다.
// 배포에서 막는 장치가 둘이다 (T11 검수 1차 High):
// - 패키징된 앱(app.isPackaged)이면 환경 변수와 무관하게 등록하지 않는다
// - 배포 빌드(`build.mjs --release`)는 __KOOKABUG_E2E_HOOKS__를 false로 정해 이 모듈과 부르는 코드가 번들에서
//   빠진다 (e2e-hooks.test.ts가 실제 배포 번들로 확인한다). T13 패키징은 배포 빌드를 쓴다

export const E2E_HOOKS_ENV = "KOOKABUG_E2E_HOOKS";
export const E2E_HOOKS_GLOBAL = "__kookabugE2E";

export interface E2EHooks {
  dropDaemonConnection(): boolean;
}

/** 훅을 켤 수 있는가: 패키징되지 않은 앱이고 환경 변수가 "1" */
export function e2eHooksEnabled(packaged: boolean, env: Readonly<Record<string, string | undefined>>): boolean {
  return !packaged && env[E2E_HOOKS_ENV] === "1";
}

/** 켤 수 있으면 target(주 프로세스 globalThis)에 훅을 단다. 달았으면 true */
export function installE2EHooks(
  target: object,
  options: { packaged: boolean; env: Readonly<Record<string, string | undefined>>; hooks: E2EHooks },
): boolean {
  if (!e2eHooksEnabled(options.packaged, options.env)) return false;
  Object.defineProperty(target, E2E_HOOKS_GLOBAL, { value: options.hooks, configurable: true });
  return true;
}
