// 속성 편집기 순수 규칙 (M2 계획 T10 완료 기준 inspector.test.ts)
import { describe, expect, test } from "vitest";
import { clearNodeValue, replaceNodeObject, setNodeTitle, setNodeValue } from "../graph/commands";
import { deepFreeze } from "../graph/corpus.testutil";
import { indexNodeTypes } from "../graph/mapping";
import { graphNodes, type GraphValue } from "../graph/model";
import {
  editorFor,
  fits,
  formatJson,
  moveItem,
  parseCells,
  parseJson,
  parseJsonObject,
  parseNumber,
  splitUnion,
  valueMode,
  valueModeFor,
} from "./fields";
import { inspectNode } from "./model";

describe("핀 타입 → 입력 모양", () => {
  test("test_editor_kind_per_pin_type", () => {
    const kind = (type: string, extra: { enum?: unknown[] } = {}) => editorFor({ type, ...extra });
    expect(kind("int")).toMatchObject({ kind: "number", integer: true });
    expect(kind("float")).toMatchObject({ kind: "number", integer: false });
    expect(kind("string").kind).toBe("text");
    expect(kind("bool").kind).toBe("bool");
    expect(kind("string", { enum: ["left", "right"] }).kind).toBe("enum");
    expect(kind("point").kind).toBe("point");
    expect(kind("rect").kind).toBe("rect");
    expect(kind("list[string]")).toMatchObject({ kind: "list", element: "string" });
    expect(kind("list[int]")).toMatchObject({ kind: "list", element: "int" });
    expect(kind("dict[str,target]")).toMatchObject({ kind: "dict", element: "target" });
    expect(kind("dict[str,any]")).toMatchObject({ kind: "dict", element: "any" });
    expect(kind("any").kind).toBe("json");
    // 플러그인 타입은 모양을 몰라 JSON으로 고친다
    expect(kind("myplug.Thing").kind).toBe("json");
    // 상수가 없는 타입: target은 대상 고르기, secret은 비밀 키, 나머지는 연결로만
    expect(kind("target")).toMatchObject({ kind: "target", allowTarget: true, allowSetting: false });
    expect(kind("secret")).toMatchObject({ kind: "secret", allowSecret: true, allowSetting: false });
    for (const t of ["match", "image", "window", "process"]) expect(kind(t).kind).toBe("link-only");
    // 유니온: 상수로 쓸 수 있는 첫 항의 모양 + 특수 값 항
    expect(kind("string|secret")).toMatchObject({ kind: "text", allowSecret: true, allowTarget: false, allowSetting: true });
    expect(kind("target|rect")).toMatchObject({ kind: "rect", allowTarget: true });
    expect(kind("match|point")).toMatchObject({ kind: "point", allowTarget: false });
    expect(splitUnion("list[string]|list[point]")).toEqual(["list[string]", "list[point]"]);
    expect(kind("list[string]|list[point]")).toMatchObject({ kind: "list", element: "string" });
    // config는 특수 값을 받지 않는다
    expect(editorFor({ type: "list[string]" }, { specials: false })).toMatchObject({
      kind: "list",
      allowSetting: false,
      allowTarget: false,
      allowSecret: false,
    });
    // 값이 모양에 맞지 않으면 JSON 상자로 보인다 (값을 잃지 않는다)
    expect(fits("number", "5")).toBe(false);
    expect(fits("number", 5)).toBe(true);
    expect(fits("text", { $foo: 1 })).toBe(false);
    expect(fits("dict", { $target: "a" })).toBe(false);
    expect(fits("list", [1])).toBe(true);
  });

  test("test_value_mode_special_values", () => {
    expect(valueMode(undefined)).toBe("unset");
    expect(valueMode(5)).toBe("constant");
    expect(valueMode({ $link: "n_a.match" })).toBe("link");
    expect(valueMode({ $link: "점없음" })).toBe("constant");
    expect(valueMode({ $link: 3 })).toBe("constant");
    expect(valueMode({ $target: "targets/a.target.json" })).toBe("target");
    expect(valueMode({ $setting: "game.title" })).toBe("setting");
    expect(valueMode({ $secret: "accounts.a" })).toBe("secret");
    expect(valueMode([{ $link: "n_a.value" }, 412])).toBe("linked-inside");
    expect(valueMode({ a: { $link: "n_a.value" } })).toBe("linked-inside");
    // `$`와 다른 키가 섞인 객체는 특수 값이 아니다 (검증 오류로 나온다)
    expect(valueMode({ $link: "a.b", x: 1 })).toBe("constant");
  });

  test("test_config_values_not_interpreted_as_specials", () => {
    // 특수 값은 in 안에서만 뜻이 있다 (T10 검수 2): config의 `$link`처럼 생긴 값은 보통 데이터다
    for (const v of [{ $link: "n_a.match" }, { retained: { $link: "n_entry.any" } }, { $target: "t" }, { $secret: "k" }, { $literal: 1 }]) {
      expect(valueModeFor(v, false)).toBe("constant");
      expect(valueModeFor(v, true)).not.toBe("constant");
    }
    expect(valueModeFor(undefined, false)).toBe("unset");
    expect(editorFor({ type: "target" }, { specials: false })).toMatchObject({ allowTarget: false, allowSetting: false });
  });
});

describe("점·사각형 상수", () => {
  test("test_point_rect_constants_shape", () => {
    expect(parseCells(["512", "412"], "point")).toEqual({ ok: true, value: [512, 412] });
    expect(parseCells(["262", "190", "500", "170"], "rect")).toEqual({ ok: true, value: [262, 190, 500, 170] });
    // 음수 좌표는 받는다 (창 밖은 실행기가 판정). -0은 0
    const neg = parseCells(["-0", "-5"], "point");
    expect(neg).toEqual({ ok: true, value: [0, -5] });
    expect(Object.is((neg as { value: number[] }).value[0], 0)).toBe(true);
    // 정수 픽셀만, 너비·높이 1 이상, 칸 수
    expect(parseCells(["1.5", "2"], "point")).toMatchObject({ ok: false, error: expect.stringContaining("x") });
    expect(parseCells(["0", "0", "0", "10"], "rect")).toMatchObject({ ok: false, error: expect.stringContaining("w") });
    expect(parseCells(["0", "0", "10", "0"], "rect")).toMatchObject({ ok: false, error: expect.stringContaining("h") });
    expect(parseCells(["", "1"], "point").ok).toBe(false);
    expect(parseCells(["1", "2", "3"], "rect").ok).toBe(false);
    expect(parseCells(["9007199254740992", "0"], "point").ok).toBe(false);
    // 핀 값은 배열 상수 그대로 쓴다 (스키마 1장: point = [x, y], rect = [x, y, w, h])
    const value = deepFreeze({
      nodes: { n_a: { type: "core.input.scroll", version: 1, in: { amount: 3 } } },
    }) as GraphValue;
    const out = setNodeValue(value, "n_a", "in", "point", [512, 412]);
    expect(out).toEqual({ nodes: { n_a: { type: "core.input.scroll", version: 1, in: { amount: 3, point: [512, 412] } } } });
    expect(fits("point", [512, 412])).toBe(true);
    expect(fits("point", [512, 412, 1])).toBe(false);
    expect(fits("rect", [0, 0, 1, 1])).toBe(true);
    expect(fits("rect", [0, 0, "1", 1])).toBe(false);
    // 같은 값이면 같은 루트 (실행 취소 기록이 생기지 않음)
    expect(setNodeValue(out, "n_a", "in", "point", [512, 412])).toBe(out);
  });
});

describe("$literal", () => {
  test("test_literal_not_interpreted", () => {
    const literal = { $literal: { $link: "n_a.match", $target: "x" } };
    // 안의 `$link`를 연결로 보지 않는다
    expect(valueMode(literal)).toBe("literal");
    expect(valueMode({ $literal: [{ $link: "n_a.match" }] })).toBe("literal");
    expect(formatJson(literal.$literal)).toBe('{"$link":"n_a.match","$target":"x"}');
    const value = deepFreeze({
      nodes: {
        n_a: { type: "core.image.wait", version: 1 },
        n_b: { type: "core.log.message", version: 1, in: { text: "안녕", level: "info", extra: literal } },
      },
    }) as GraphValue;
    // 옆 핀을 고쳐도 $literal 값은 같은 객체 그대로다
    const out = setNodeValue(value, "n_b", "in", "text", "바뀜");
    const node = graphNodes(out).find((n) => n.id === "n_b")!;
    expect(node.in.extra).toBe(value.nodes && (value.nodes as Record<string, { in: Record<string, unknown> }>).n_b.in.extra);
    expect(node.in).toEqual({ text: "바뀜", level: "info", extra: literal });
  });
});

describe("모르는 노드 JSON 편집", () => {
  const big = 1e20;
  const graph = () =>
    deepFreeze({
      format: "kookabug.graph/0",
      kind: "test",
      nodes: {
        n_known: { type: "core.log.message", version: 1, in: { text: "a" } },
        n_plug: {
          type: "notinstalled.widget.poke",
          version: 3,
          title: "모르는 노드",
          in: { a: 1, b: { $link: "n_known.value" }, c: big, d: [1, { k: "v" }] },
          config: { mode: "fast", nested: { x: [1, 2] } },
          next: { weird_exit: "n_known" },
          x_unknown: { keep: true },
        },
      },
      x_top: 1,
    }) as GraphValue;

  test("test_unknown_node_json_edit_changes_only_that_key", () => {
    const value = graph();
    const node = (v: GraphValue) => (v.nodes as Record<string, Record<string, unknown>>).n_plug;
    const before = node(value);
    const beforeIn = before.in as Record<string, unknown>;
    // 상자에 보인 글자에서 a만 고쳤다
    const parsed = parseJsonObject(formatJson(beforeIn, 2).replace('"a": 1', '"a": 2'));
    expect(parsed.ok).toBe(true);
    const out = replaceNodeObject(value, "n_plug", "in", (parsed as { value: Record<string, unknown> }).value);
    const after = node(out);
    const afterIn = after.in as Record<string, unknown>;
    expect(afterIn.a).toBe(2);
    // 다른 키는 같은 객체·같은 수 그대로 (1e20은 실수로 남는다: 상자 글자는 지수 표기)
    expect(afterIn.b).toBe(beforeIn.b);
    expect(afterIn.c).toBe(big);
    expect(afterIn.d).toBe(beforeIn.d);
    expect(Object.keys(afterIn)).toEqual(["a", "b", "c", "d"]);
    // 노드의 config·next·version·모르는 키와 다른 노드·최상위는 그대로
    for (const k of ["type", "version", "title", "config", "next", "x_unknown"]) expect(after[k]).toBe(before[k]);
    expect((out.nodes as Record<string, unknown>).n_known).toBe((value.nodes as Record<string, unknown>).n_known);
    expect(out.x_top).toBe(1);
    // 바꾼 게 없으면 같은 루트
    const same = parseJsonObject(formatJson(beforeIn, 2));
    expect(replaceNodeObject(value, "n_plug", "in", (same as { value: Record<string, unknown> }).value)).toBe(value);
    // 키를 지우면 그 키만, 새 키는 끝에
    const removed = replaceNodeObject(value, "n_plug", "config", { mode: "fast", added: true });
    expect(node(removed).config).toEqual({ mode: "fast", added: true });
    expect(Object.keys(node(removed).config as object)).toEqual(["mode", "added"]);
    expect(node(removed).in).toBe(beforeIn);
    // 다 지우면 그 객체를 지운다 (T9: 비게 된 in은 지운다)
    expect(Object.hasOwn(node(replaceNodeObject(value, "n_plug", "config", {})), "config")).toBe(false);
    // 객체가 아니면 받지 않는다
    expect(parseJsonObject("[1, 2]").ok).toBe(false);
    expect(parseJsonObject("{ 이상함").ok).toBe(false);
    // `__proto__` 키도 보통 키로 쓴다
    const proto = parseJsonObject('{"__proto__": {"x": 1}, "a": 1}');
    expect(proto.ok).toBe(true);
    const withProto = replaceNodeObject(value, "n_plug", "in", (proto as { value: Record<string, unknown> }).value);
    const protoIn = node(withProto).in as Record<string, unknown>;
    expect(Object.hasOwn(protoIn, "__proto__")).toBe(true);
    expect(Object.getPrototypeOf(protoIn)).toBe(Object.prototype);
  });
});

describe("값 검사", () => {
  test("test_int_out_of_safe_range_rejected_inline", () => {
    const int = { integer: true };
    expect(parseNumber("9007199254740991", int)).toEqual({ ok: true, value: 9007199254740991 });
    expect(parseNumber("-9007199254740991", int)).toEqual({ ok: true, value: -9007199254740991 });
    expect(parseNumber("9007199254740992", int)).toMatchObject({ ok: false, error: expect.stringContaining("정수 범위") });
    expect(parseNumber("-9007199254740992", int).ok).toBe(false);
    expect(parseNumber("99999999999999999999", int).ok).toBe(false);
    // 정수 핀은 정수 글자만 (소수·지수·빈칸·글자 거부)
    for (const t of ["1.5", "1e3", "", " ", "abc", "NaN", "Infinity", "0x10"]) expect(parseNumber(t, int).ok).toBe(false);
    // min/max
    expect(parseNumber("-1", { integer: true, minimum: 0 })).toMatchObject({ ok: false, error: "0 이상이어야 해요" });
    expect(parseNumber("2", { integer: false, minimum: 0, maximum: 1 })).toMatchObject({ ok: false, error: "1 이하여야 해요" });
    expect(parseNumber("0.5", { integer: false, minimum: 0, maximum: 1 })).toEqual({ ok: true, value: 0.5 });
    // 실수: 유한한 수만
    expect(parseNumber("1e400", { integer: false })).toMatchObject({ ok: false, error: "유한한 수를 넣으세요" });
    expect(parseNumber("NaN", { integer: false }).ok).toBe(false);
    expect(parseNumber("1e20", { integer: false })).toEqual({ ok: true, value: 1e20 });
    // JSON 상자: 정수 범위 밖 정수 토큰과 유한하지 않은 수는 거부, 지수 표기 실수와 문자열 안은 받는다
    expect(parseJson("9007199254740993").ok).toBe(false);
    expect(parseJson('{"a": [1, -9007199254740993]}').ok).toBe(false);
    expect(parseJson("1e400").ok).toBe(false);
    expect(parseJson("1e20")).toEqual({ ok: true, value: 1e20 });
    expect(parseJson("9007199254740992.0")).toEqual({ ok: true, value: 9007199254740992 });
    expect(parseJson('"9007199254740993"')).toEqual({ ok: true, value: "9007199254740993" });
    expect(parseJson('{"k\\"9007199254740993": 1}').ok).toBe(true);
    // 큰 실수는 지수 표기로 보여 다시 읽어도 실수다
    expect(formatJson(1e20)).toBe("1e+20");
    expect(formatJson(9007199254740992)).toBe("9.007199254740992e+15");
    expect(parseJson(formatJson({ a: 1.2345678901234567e19 })).ok).toBe(true);
  });
});

describe("편집 명령과 항목", () => {
  test("test_title_and_clear_commands", () => {
    const value = deepFreeze({
      nodes: { n_a: { type: "core.flow.delay", version: 1, title: "기다림", in: { ms: 100 } } },
      layout: { nodes: { n_a: { x: 0, y: 0 } } },
    }) as GraphValue;
    const titled = setNodeTitle(value, "n_a", "새 제목");
    expect(titled).toEqual({
      nodes: { n_a: { type: "core.flow.delay", version: 1, title: "새 제목", in: { ms: 100 } } },
      layout: { nodes: { n_a: { x: 0, y: 0 } } },
    });
    expect((titled.layout as object) === value.layout).toBe(true);
    expect(Object.hasOwn((setNodeTitle(value, "n_a", "") as { nodes: { n_a: object } }).nodes.n_a, "title")).toBe(false);
    // 마지막 핀을 지우면 비게 된 in도 지운다
    expect(clearNodeValue(value, "n_a", "in", "ms")).toEqual({
      nodes: { n_a: { type: "core.flow.delay", version: 1, title: "기다림" } },
      layout: { nodes: { n_a: { x: 0, y: 0 } } },
    });
    expect(setNodeValue(value, "없음", "in", "ms", 1)).toBe(value);
    expect(moveItem(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveItem(["a", "b"], 0, 5)).toEqual(["a", "b"]);
  });

  test("test_inspect_node_fields_from_shape_and_decl", () => {
    const types = indexNodeTypes([
      {
        plugin: { id: "core", version: "0.1.0" },
        nodes: [
          {
            type: "core.image.wait_any",
            version: 1,
            title: "여럿 중 대기",
            inputs: {
              targets: { type: "dict[str,target]" },
              timeout_ms: { type: "int", default: 10000, minimum: 0 },
            },
            config: { exits: { type: "list[string]" } },
            exits: { from_config: "exits", kind: "ok", outputs: ["match"], extra: [{ kind: "fail", name: "timeout", outputs: [] }] },
          },
        ],
      },
    ]);
    const value = {
      nodes: {
        n_w: { type: "core.image.wait_any", version: 1, in: { timeout_ms: 5, typo: 1 }, config: { exits: ["a", "b"], x: 1 } },
        n_u: { type: "plug.thing", version: 1, in: { q: 1 } },
      },
    } as GraphValue;
    const [w, u] = graphNodes(value);
    const diag = { severity: "error" as const, code: "c", message: "m", file: null, node: "n_w" };
    const view = inspectNode(w, {}, types, [
      { ...diag, pointer: "/nodes/n_w/in/timeout_ms" },
      { ...diag, pointer: "/nodes/n_w/config/exits/0" },
      { ...diag, pointer: "/nodes/n_w/next/c" },
      { ...diag, pointer: "/nodes/n_other/in/x", node: "n_other" },
    ], "tests/a.graph.json");
    expect(view.unknown).toBe(false);
    expect(view.defaultTitle).toBe("여럿 중 대기");
    // 응답 전 정적 모양 + 선언의 기본값·min
    expect(view.inputs.map((p) => p.name)).toEqual(["targets", "timeout_ms"]);
    expect(view.inputs[1]).toMatchObject({ type: "int", default: 10000, minimum: 0, required: false });
    expect(view.inputs[0]).toMatchObject({ type: "dict[str,target]", required: true });
    expect(view.extraInputs).toEqual(["typo"]);
    expect(view.config).toEqual([{ name: "exits", type: "list[string]", required: true }]);
    expect(view.extraConfig).toEqual(["x"]);
    expect(view.diagnostics.in.get("timeout_ms")).toHaveLength(1);
    expect(view.diagnostics.config.get("exits")).toHaveLength(1);
    expect(view.diagnostics.node).toHaveLength(1);
    // daemon 모양이 오면 그 핀 목록과 값 검사 항목이 이긴다
    const shaped = inspectNode(
      w,
      {
        n_w: {
          inputs: [{ name: "timeout_ms", type: "int", nullable: false, optional: false, required: false, default: 1, maximum: 9 }],
          outputs: [],
          exits: [],
          unknown: false,
        },
      },
      types,
      [],
      "tests/a.graph.json",
    );
    expect(shaped.inputs).toEqual([{ name: "timeout_ms", type: "int", required: false, default: 1, minimum: 0, maximum: 9 }]);
    // 레지스트리에 없는 노드는 JSON 상자로 고친다
    expect(inspectNode(u, {}, types, [], "tests/a.graph.json")).toMatchObject({ unknown: true, inputs: [], config: [] });
  });
});
