// 창 닫기 확인 (T9 검수 1차: 창 X·끝내기가 저장 확인을 건너뜀)
import { expect, test } from "vitest";
import { CloseGuard } from "./close-guard";

function setup() {
  const log: string[] = [];
  const guard = new CloseGuard({ ask: () => log.push("ask"), close: () => log.push("close") });
  return { guard, log };
}

test("test_close_asks_renderer_then_closes_on_yes", () => {
  const { guard, log } = setup();
  // 렌더러가 붙이기 전에는 막지 않는다
  expect(guard.onClose()).toBe(false);
  guard.arm(true);
  expect(guard.onClose()).toBe(true);
  // 묻는 동안 다시 닫으면 한 번만 묻는다
  expect(guard.onClose()).toBe(true);
  expect(log).toEqual(["ask"]);
  // 취소: 닫지 않고 다음 닫기에 다시 묻는다
  guard.answer(false);
  expect(guard.onClose()).toBe(true);
  expect(log).toEqual(["ask", "ask"]);
  guard.answer(true);
  expect(log).toEqual(["ask", "ask", "close"]);
  // 확인한 뒤의 close 이벤트는 지나간다
  expect(guard.onClose()).toBe(false);
});

test("test_renderer_gone_does_not_block_close", () => {
  const { guard, log } = setup();
  guard.arm(true);
  expect(guard.onClose()).toBe(true);
  guard.rendererGone();
  expect(guard.onClose()).toBe(false);
  // 묻지 않은 답은 무시한다
  guard.answer(true);
  expect(log).toEqual(["ask"]);
});
