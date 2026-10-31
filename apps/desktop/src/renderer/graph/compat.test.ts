// 연결 끌기 중 핀 호환 (M2 계획 2.11, T9). 타입 규칙은 코어 validate/types.assignable과 같다
import { expect, test } from "vitest";
import { assignable, compatible, parsePinType, type PinEnd } from "./compat";

const out = (type: string | null, node = "a"): PinEnd => ({ node, handle: "o:x", side: "source", kind: "data", type });
const inp = (type: string | null, node = "b"): PinEnd => ({ node, handle: "i:y", side: "target", kind: "data", type });
const ok = (src: string, dst: string) => assignable(parsePinType(src), parsePinType(dst));

test("타입 규칙 (코어 assignable)", () => {
  expect(ok("int", "int")).toBe(true);
  expect(ok("int", "float")).toBe(true);
  expect(ok("float", "int")).toBe(false);
  expect(ok("match", "any")).toBe(true);
  expect(ok("any", "window")).toBe(true);
  expect(ok("string", "string|secret")).toBe(true);
  expect(ok("string|secret", "string")).toBe(false);
  expect(ok("secret", "string")).toBe(false);
  expect(ok("list[int]", "list[float]")).toBe(true);
  expect(ok("list[float]", "list[int]")).toBe(false);
  expect(ok("dict[str,target]", "dict[str, target]")).toBe(true);
  expect(ok("list[int]", "int")).toBe(false);
  expect(ok("image", "window")).toBe(false);
});

test("핀 끝: 같은 노드·같은 쪽·흐름과 데이터는 잇지 않는다. 어느 쪽에서 끌어도 같다", () => {
  expect(compatible(out("int"), inp("float"))).toBe(true);
  expect(compatible(inp("float"), out("int"))).toBe(true);
  expect(compatible(out("float"), inp("int"))).toBe(false);
  expect(compatible(out("int", "a"), inp("int", "a"))).toBe(false);
  expect(compatible(out("int"), out("int", "b"))).toBe(false);
  // 타입을 모르는 핀(모양 밖)은 막지 않는다 (최종 판정은 daemon 검증)
  expect(compatible(out(null), inp("window"))).toBe(true);
  const exit: PinEnd = { node: "a", handle: "x:done", side: "source", kind: "exec", type: null };
  const execIn: PinEnd = { node: "b", handle: "in", side: "target", kind: "exec", type: null };
  expect(compatible(exit, execIn)).toBe(true);
  expect(compatible(exit, inp("any"))).toBe(false);
  expect(compatible(out("any"), execIn)).toBe(false);
});
