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
  /**
   * 그 메서드의 다음 응답들을 차례로 늦춘다 (ms, 응답을 받은 뒤 렌더러에 넘기기 전). 응답이 요청 순서와
   * 다르게 도착하는 경우를 만든다 (T12 target.preview 역순 응답 검사)
   */
  delayResponses(method: string, delaysMs: number[]): void;
  /** 녹화 전역 단축키를 누른 것처럼 (M4 T9). 등록돼 있지 않으면 false */
  pressRecorderHotkey(role: "stop" | "mark_secret"): boolean;
  /** 지금 등록된 녹화 단축키 가속기 */
  recorderAccelerators(): string[];
  /** 다음 등록에서 이 가속기를 다른 앱이 쥔 것처럼 실패시킨다 (null이면 되돌림) */
  blockRecorderHotkey(accelerator: string | null): void;
}

/** 메서드별 남은 응답 지연 (delayResponses). 꺼낼 때마다 하나씩 줄어든다 */
export class ResponseDelays {
  private readonly queues = new Map<string, number[]>();

  set(method: string, delaysMs: readonly number[]): void {
    this.queues.set(method, delaysMs.map((d) => Math.max(0, Math.min(30_000, Number(d) || 0))));
  }

  /** 이 응답을 늦출 시간 (없으면 0) */
  next(method: string): number {
    const queue = this.queues.get(method);
    const d = queue?.shift() ?? 0;
    if (queue !== undefined && queue.length === 0) this.queues.delete(method);
    return d;
  }
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
