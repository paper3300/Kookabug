// 위젯 호스트 확인 (M6 계획 3.10): kbplugin://<host>/ → 그 플러그인 환경 안 ui 폴더. 렌더러가 아니라 주 프로세스가
// daemon plugins.list에서 직접 읽는다 — 잠금에 있고 환경이 준비된 플러그인만 (렌더러가 경로를 정하지 못한다).
// **껍데기·자원 요청마다** 지금 목록으로 다시 확인한다 (B6 검수 High: 검증에서 탈락한 환경의 파일을 캐시로 계속
// 주지 않게). 캐시는 두지 않고, 확인 도중 무효화(plugins.changed·연결 상태 변화)가 있으면 그 응답을 버리고 다시
// 묻는다. 확인 실패·연결 없음이면 거부한다 (열린 쪽으로 실패하지 않는다)
// electron을 import하지 않는다: vitest가 Electron 없이 검사한다
import { widgetHostDir, type WidgetHost } from "./security";

interface ListEntry {
  env_status?: unknown;
  ui?: { host?: unknown; path?: unknown } | null;
}

/** plugins.list 결과 → 호스트 표 (환경 준비된 것만) */
export function widgetHostsFrom(list: unknown, workspaceRoot: string): Map<string, WidgetHost> {
  const out = new Map<string, WidgetHost>();
  const plugins = (list as { plugins?: unknown } | null)?.plugins;
  if (!Array.isArray(plugins)) return out;
  for (const p of plugins as ListEntry[]) {
    const ui = p?.ui;
    if (p?.env_status !== "ready" || ui == null || typeof ui.host !== "string" || typeof ui.path !== "string") continue;
    const resolved = widgetHostDir(workspaceRoot, ui.path);
    if (resolved !== null) out.set(ui.host, { host: ui.host, ...resolved });
  }
  return out;
}

/** 무효화가 겹쳐 같은 요청을 다시 묻는 횟수 상한 (넘으면 거부) */
const RETRIES = 3;

export class WidgetHosts {
  /** 무효화 세대: 확인을 시작할 때와 끝날 때가 다르면 그 응답은 쓰지 않는다 */
  private generation = 0;

  constructor(
    private readonly deps: {
      /** daemon plugins.list (연결이 없으면 던진다) */
      list(): Promise<unknown>;
      root(): string | null;
    },
  ) {}

  /** 잠금·환경 상태가 바뀌었거나(plugins.changed) daemon 연결 상태가 바뀌었다 */
  invalidate(): void {
    this.generation += 1;
  }

  /** 지금 이 호스트가 잠금에 있고 환경이 준비됐으면 그 ui 폴더. 아니면·확인 실패면 null */
  async lookup(host: string): Promise<WidgetHost | null> {
    for (let attempt = 0; attempt < RETRIES; attempt++) {
      const generation = this.generation;
      const root = this.deps.root();
      if (root === null) return null;
      let list: unknown;
      try {
        list = await this.deps.list();
      } catch {
        return null;
      }
      // 확인 도중 무효화됐거나 워크스페이스가 바뀌었으면 이 응답은 낡았다 → 다시 묻는다
      if (generation !== this.generation || this.deps.root() !== root) continue;
      return widgetHostsFrom(list, root).get(host) ?? null;
    }
    return null;
  }
}
