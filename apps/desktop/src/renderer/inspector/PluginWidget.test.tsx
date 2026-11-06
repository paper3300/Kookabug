// 플러그인 위젯 세션 (M6 계획 3.10): 메시지 출처·세션 검사, 재적재 뒤 옛 세션, 값 검사, 읽기 전용, 5초 대체 편집기,
// 비밀값 항목 마운트 금지. 실제 iframe·CSP·프레임 이동은 E2E plugin-widget.spec.ts
import { describe, expect, test } from "vitest";
import type { FieldSpec } from "./fields";
import {
  checkWidgetValue,
  newSessionNonce,
  widgetBlock,
  WidgetSession,
  type WidgetEndReason,
  type WidgetPlugin,
} from "./widgetSession";

const COLOR: FieldSpec = { name: "color", type: "string", required: false, default: "#3366ff", widget: "sample.color" };

function rig(over: Partial<{ spec: FieldSpec; readOnly: boolean; value: unknown }> = {}) {
  const posted: Record<string, unknown>[] = [];
  const commits: unknown[] = [];
  const ends: WidgetEndReason[] = [];
  const heights: number[] = [];
  const frame = { name: "지금 iframe" };
  const session = newSessionNonce();
  const s = new WidgetSession({
    session,
    widget: "sample.color",
    spec: over.spec ?? COLOR,
    value: over.value ?? "#3366ff",
    readOnly: over.readOnly ?? false,
    theme: { dark: true, colors: { fg: "#ccc" } },
    post: (m) => posted.push(m),
    commit: (v) => commits.push(v),
    end: (r) => ends.push(r),
    resize: (h) => heights.push(h),
  });
  s.frameLoaded();
  const send = (data: unknown, source: unknown = frame) => s.receive(source, frame, data);
  return { s, session, frame, posted, commits, ends, heights, send };
}

describe("PluginWidget", () => {
  test("rejects other sources and stale session", () => {
    const r = rig();
    // 다른 창·다른 세션·모양이 틀린 메시지는 ready로 치지 않는다
    r.send({ kb: "ready", session: r.session }, { name: "다른 창" });
    r.send({ kb: "ready", session: "0".repeat(32) });
    r.send({ kb: "ready" });
    r.send("ready");
    r.send(null);
    r.s.receive(r.frame, null, { kb: "ready", session: r.session });
    expect(r.s.state).toBe("loading");
    expect(r.posted).toEqual([]);

    r.send({ kb: "ready", session: r.session });
    expect(r.s.state).toBe("ready");
    expect(r.posted).toHaveLength(1);
    expect(r.posted[0]).toMatchObject({
      kb: "init",
      api: 1,
      session: r.session,
      widget: "sample.color",
      value: "#3366ff",
      readOnly: false,
      schema: { name: "color", type: "string", default: "#3366ff" },
    });
    r.send({ kb: "change", session: r.session, value: "#ff0000" }, { name: "다른 창" });
    r.send({ kb: "change", session: "f".repeat(32), value: "#ff0000" });
    expect(r.commits).toEqual([]);
    r.send({ kb: "change", session: r.session, value: "#ff0000" });
    expect(r.commits).toEqual(["#ff0000"]);
    expect(r.posted).toHaveLength(2); // init, 받은 값 알림
    expect(r.posted[1]).toEqual({ kb: "value", session: r.session, value: "#ff0000", readOnly: false });

    // 재적재(두 번째 load): 같은 창·같은 세션의 메시지라도 더는 받지 않고 기본 편집기로
    r.s.frameLoaded();
    expect(r.ends).toEqual(["reloaded"]);
    expect(r.s.state).toBe("ended");
    r.send({ kb: "change", session: r.session, value: "#00ff00" });
    r.send({ kb: "ready", session: r.session });
    r.send({ kb: "resize", session: r.session, height: 300 });
    expect(r.commits).toEqual(["#ff0000"]);
    expect(r.heights).toEqual([]);
    expect(r.posted).toHaveLength(2);
    // 마운트마다 nonce가 다르다
    expect(newSessionNonce()).toMatch(/^[0-9a-f]{32}$/);
    expect(newSessionNonce()).not.toBe(newSessionNonce());
  });

  test("invalid change ignored", () => {
    const r = rig();
    r.send({ kb: "ready", session: r.session });
    for (const value of [42, null, ["#fff"], { $secret: "x" }, { $link: "a.b" }, "x".repeat(70_000)]) {
      r.send({ kb: "change", session: r.session, value });
      // 버린 값이면 위젯 표시를 지금 값으로 되돌린다
      expect(r.posted.at(-1)).toEqual({ kb: "value", session: r.session, value: "#3366ff", readOnly: false });
    }
    r.send({ kb: "change", session: r.session });
    expect(r.commits).toEqual([]);

    // 수·정수·범위·enum·사각형·JSON 아닌 값
    const int: FieldSpec = { name: "n", type: "int", required: true, minimum: 1, maximum: 10 };
    expect(checkWidgetValue(int, 5)).toBeNull();
    expect(checkWidgetValue(int, 5.5)).not.toBeNull();
    expect(checkWidgetValue(int, 11)).not.toBeNull();
    expect(checkWidgetValue(int, Number.NaN)).not.toBeNull();
    expect(checkWidgetValue(int, 2 ** 60)).not.toBeNull();
    expect(checkWidgetValue({ name: "e", type: "string", required: true, enum: ["a", "b"] }, "c")).not.toBeNull();
    expect(checkWidgetValue({ name: "r", type: "rect", required: true }, [0, 0, 0, 5])).not.toBeNull();
    expect(checkWidgetValue({ name: "r", type: "rect", required: true }, [0, 0, 4, 5])).toBeNull();
    expect(checkWidgetValue({ name: "j", type: "any", required: true }, new Date())).not.toBeNull();
    expect(checkWidgetValue({ name: "j", type: "any", required: true }, { a: [1, "x", true, null] })).toBeNull();
    expect(checkWidgetValue({ name: "j", type: "any", required: true }, { a: Infinity })).not.toBeNull();

    // B6 검수 Mid: 선언 타입 전체를 재귀로 (편집기 모양이 아니라)
    const spec = (type: string): FieldSpec => ({ name: "x", type, required: true });
    const bad: [string, unknown][] = [
      ["list[int]", ["bad"]],
      ["dict[str,int]", { a: "bad" }],
      ["list[point]", [[1]]],
      ["list[rect]", [[0, 0, 0, 1]]],
      ["dict[str,list[string]]", { a: [1] }],
      ["list[int]", [1.5]],
      ["string|int", 1.5],
      ["list[string|int]", [true]],
      ["int", 2 ** 60],
      ["target", "targets/a.target.json"],
      ["window", 1],
      ["any", { a: { $secret: "accounts.qa" } }],
    ];
    for (const [type, value] of bad) expect(checkWidgetValue(spec(type), value), `${type} ← ${JSON.stringify(value)}`).not.toBeNull();
    const good: [string, unknown][] = [
      ["string|int", 7],
      ["string|int", "a"],
      ["list[int]", [1, 2]],
      ["dict[str,int]", { a: 1 }],
      ["list[point]", [[1, 2]]],
      ["list[string|int]", ["a", 1]],
      ["dict[str,list[rect]]", { a: [[0, 0, 1, 1]] }],
      ["float", 1.5],
      ["acme.Color", { r: 1 }],
      ["int|rect", [0, 0, 2, 2]],
    ];
    for (const [type, value] of good) expect(checkWidgetValue(spec(type), value), `${type} ← ${JSON.stringify(value)}`).toBeNull();
    // 범위는 수 값에만, 깊이 제한
    expect(checkWidgetValue({ ...spec("int|string"), minimum: 1 }, 0)).not.toBeNull();
    expect(checkWidgetValue({ ...spec("int|string"), minimum: 1 }, "x")).toBeNull();
    let deep: unknown = 1;
    for (let i = 0; i < 70; i++) deep = [deep];
    expect(checkWidgetValue(spec("any"), deep)).not.toBeNull();

    // 실제 세션: 원소 타입이 틀린 목록은 commit되지 않는다
    const list = rig({ spec: { name: "x", type: "list[int]", required: true }, value: [] });
    list.send({ kb: "ready", session: list.session });
    list.send({ kb: "change", session: list.session, value: ["bad"] });
    expect(list.commits).toEqual([]);
    list.send({ kb: "change", session: list.session, value: [9] });
    expect(list.commits).toEqual([[9]]);

    // 크기가 틀린 resize는 범위로 자른다, 수가 아니면 버린다
    r.send({ kb: "resize", session: r.session, height: 5 });
    r.send({ kb: "resize", session: r.session, height: 99_999 });
    r.send({ kb: "resize", session: r.session, height: "big" });
    expect(r.heights).toEqual([28, 480]);
  });

  test("readOnly ignores change", () => {
    const r = rig({ readOnly: true });
    r.send({ kb: "ready", session: r.session });
    expect(r.posted[0]).toMatchObject({ kb: "init", readOnly: true });
    r.send({ kb: "change", session: r.session, value: "#ff0000" });
    expect(r.commits).toEqual([]);
    expect(r.posted.at(-1)).toEqual({ kb: "value", session: r.session, value: "#3366ff", readOnly: true });
    // 실행이 끝나 편집 가능해지면 위젯에 알리고, 그 뒤 바뀜은 받는다
    r.s.update("#3366ff", false);
    expect(r.posted.at(-1)).toEqual({ kb: "value", session: r.session, value: "#3366ff", readOnly: false });
    r.send({ kb: "change", session: r.session, value: "#ff0000" });
    expect(r.commits).toEqual(["#ff0000"]);
    // 다시 실행 중(읽기 전용)이면 버린다
    r.s.update("#ff0000", true);
    r.send({ kb: "change", session: r.session, value: "#00ff00" });
    expect(r.commits).toEqual(["#ff0000"]);
  });

  test("fallback on timeout", () => {
    const r = rig();
    r.s.timeout();
    expect(r.ends).toEqual(["timeout"]);
    expect(r.s.state).toBe("ended");
    // 늦게 온 ready는 받지 않는다 (init을 보내지 않음)
    r.send({ kb: "ready", session: r.session });
    expect(r.posted).toEqual([]);
    // ready 뒤의 기한은 아무 일 없다
    const ok = rig();
    ok.send({ kb: "ready", session: ok.session });
    ok.s.timeout();
    expect(ok.ends).toEqual([]);
    expect(ok.s.state).toBe("ready");
  });

  test("never mounts for secret fields", () => {
    const plugin: WidgetPlugin = { id: "sample", env_status: "ready", ui: { host: "sample-0123456789ab", widgets: ["sample.color"] } };
    expect(widgetBlock(COLOR, "config", "#fff", plugin, "sample")).toBeNull();
    // 비밀값 타입 (유니온·목록 안 포함), 비밀값 참조 값
    // 중첩 유니온 안의 secret도 (B6 검수 참고 — SDK·설치 검사와 겹으로)
    for (const type of ["secret", "string|secret", "list[secret]", "dict[str,secret]", "list[string|secret]", "dict[str,int|secret]", "list[list[secret]]"]) {
      expect(widgetBlock({ ...COLOR, type }, "config", undefined, plugin, "sample"), type).toBe("secret");
    }
    expect(widgetBlock(COLOR, "config", { $secret: "accounts.qa" }, plugin, "sample")).toBe("secret");
    expect(widgetBlock({ ...COLOR, type: "any" }, "config", { a: [{ $secret: "k" }] }, plugin, "sample")).toBe("secret");
    // 그 밖의 마운트 조건: config만, 자기 플러그인 위젯만, 잠금에 있고 환경 준비, 알려진 위젯
    expect(widgetBlock({ ...COLOR, widget: undefined }, "config", "#fff", plugin, "sample")).toBe("none");
    expect(widgetBlock(COLOR, "in", "#fff", plugin, "sample")).toBe("not_config");
    expect(widgetBlock(COLOR, "config", "#fff", plugin, "other")).toBe("foreign");
    expect(widgetBlock(COLOR, "config", "#fff", undefined, "sample")).toBe("not_ready");
    expect(widgetBlock(COLOR, "config", "#fff", { ...plugin, env_status: "missing" }, "sample")).toBe("not_ready");
    expect(widgetBlock(COLOR, "config", "#fff", { ...plugin, ui: undefined }, "sample")).toBe("not_ready");
    expect(widgetBlock({ ...COLOR, widget: "sample.other" }, "config", "#fff", plugin, "sample")).toBe("unknown_widget");
  });
});
