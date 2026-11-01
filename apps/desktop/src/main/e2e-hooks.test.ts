// E2E 검사 전용 주 프로세스 훅이 배포에서 꺼져 있는지 (T11 검수 1차 High).
// - 패키징된 앱이면 환경 변수와 무관하게 달지 않는다
// - 패키징 검사(T13 대비): 배포 빌드(build.mjs --release와 같은 설정)의 실제 main 번들에 훅 코드가 없다
import * as esbuild from "esbuild";
import { describe, expect, test } from "vitest";
import { mainOptions } from "../../scripts/build-options.mjs";
import { E2E_HOOKS_ENV, E2E_HOOKS_GLOBAL, e2eHooksEnabled, installE2EHooks, ResponseDelays } from "./e2e-hooks";

const hooks = { dropDaemonConnection: () => true, delayResponses: () => {} };

describe("훅 등록 조건", () => {
  test("test_packaged_app_never_installs_hook_even_with_env", () => {
    const target = {};
    expect(installE2EHooks(target, { packaged: true, env: { [E2E_HOOKS_ENV]: "1" }, hooks })).toBe(false);
    expect(Object.hasOwn(target, E2E_HOOKS_GLOBAL)).toBe(false);
    expect(e2eHooksEnabled(true, { [E2E_HOOKS_ENV]: "1" })).toBe(false);
  });

  test("개발 실행은 환경 변수가 정확히 1일 때만", () => {
    expect(e2eHooksEnabled(false, {})).toBe(false);
    expect(e2eHooksEnabled(false, { [E2E_HOOKS_ENV]: "true" })).toBe(false);
    const target = {};
    expect(installE2EHooks(target, { packaged: false, env: { [E2E_HOOKS_ENV]: "1" }, hooks })).toBe(true);
    expect((target as Record<string, unknown>)[E2E_HOOKS_GLOBAL]).toBe(hooks);
  });
});

async function mainBundle(release: boolean): Promise<string> {
  const result = await esbuild.build({ ...mainOptions({ release }), write: false, sourcemap: false, metafile: false });
  const out = result.outputFiles?.find((f) => f.path.endsWith(".cjs"));
  if (out === undefined) throw new Error("main 번들이 없다");
  return out.text;
}

describe("응답 지연 (delayResponses)", () => {
  test("메서드별로 차례로 꺼내고 다 쓰면 0", () => {
    const d = new ResponseDelays();
    d.set("target.preview", [1500, 0, 20]);
    expect([d.next("target.preview"), d.next("graph.open"), d.next("target.preview"), d.next("target.preview")]).toEqual([1500, 0, 0, 20]);
    expect(d.next("target.preview")).toBe(0);
    d.set("x", [-5, 99_999]);
    expect([d.next("x"), d.next("x")]).toEqual([0, 30_000]);
  });
});

describe("배포 빌드 번들", () => {
  test("test_release_main_bundle_has_no_e2e_hook", async () => {
    const text = await mainBundle(true);
    expect(text).not.toContain(E2E_HOOKS_GLOBAL);
    expect(text).not.toContain(E2E_HOOKS_ENV);
    expect(text).not.toContain("dropDaemonConnection");
    expect(text).not.toContain("delayResponses");
    expect(text).not.toContain("ResponseDelays");
    // 번들 자체는 정상 (연결 관리는 그대로 있다)
    expect(text).toContain("dropConnection");
  }, 30_000);

  test("개발 빌드에는 있다 (검사가 빈 번들을 보지 않았다는 대조)", async () => {
    const text = await mainBundle(false);
    expect(text).toContain(E2E_HOOKS_GLOBAL);
    expect(text).toContain("isPackaged");
  }, 30_000);
});
