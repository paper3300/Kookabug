// target 편집기 좌표 계산 (M2 계획 T12 완료 기준 vitest target/geometry.test.ts)
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import {
  ANCHOR_ORDER,
  anchorPoint,
  clickPoint,
  fitView,
  gestureKind,
  imageToClientRect,
  imageToScreen,
  moveRect,
  normalizedToPixels,
  nudge,
  offsetFromClick,
  pixelAt,
  pixelsToRegion,
  rectFromDrag,
  resizeRect,
  screenToImage,
  zoomAt,
  type Rect,
  type Size,
  type View,
} from "./geometry";

describe("화면 ↔ 이미지 좌표", () => {
  test("test_screen_to_image_pixels_under_zoom", () => {
    // 2배 확대, 이미지 (0,0)이 화면 (10, 20): 화면 (14.9, 25) → 이미지 (2.45, 2.5) → 픽셀 (2, 2)
    const view: View = { zoom: 2, x: 10, y: 20 };
    const p = screenToImage({ x: 14.9, y: 25 }, view);
    expect(p.x).toBeCloseTo(2.45);
    expect(pixelAt(p, [100, 100])).toEqual({ x: 2, y: 2 });
    // 축소(0.5배)에서는 화면 1px이 이미지 2px
    const small: View = { zoom: 0.5, x: 0, y: 0 };
    expect(pixelAt(screenToImage({ x: 100.4, y: 50 }, small), [400, 300])).toEqual({ x: 200, y: 100 });
    // 이미지 밖은 끝 픽셀
    expect(pixelAt(screenToImage({ x: -40, y: 9999 }, view), [100, 50])).toEqual({ x: 0, y: 49 });
    // 왕복
    fc.assert(
      fc.property(
        fc.double({ min: 0.05, max: 32, noNaN: true }),
        fc.double({ min: -2000, max: 2000, noNaN: true }),
        fc.double({ min: -2000, max: 2000, noNaN: true }),
        fc.double({ min: 0, max: 4000, noNaN: true }),
        fc.double({ min: 0, max: 4000, noNaN: true }),
        (zoom, x, y, ix, iy) => {
          const v = { zoom, x, y };
          const back = screenToImage(imageToScreen({ x: ix, y: iy }, v), v);
          return Math.abs(back.x - ix) < 1e-6 && Math.abs(back.y - iy) < 1e-6;
        },
      ),
    );
  });

  test("확대·축소는 포인터 아래 이미지 점을 그대로 둔다", () => {
    const v: View = { zoom: 0.8, x: 30, y: 40 };
    const at = { x: 300, y: 200 };
    const before = screenToImage(at, v);
    const z = zoomAt(v, 2.5, at);
    expect(z.zoom).toBeCloseTo(2);
    const after = screenToImage(at, z);
    expect(after.x).toBeCloseTo(before.x);
    expect(after.y).toBeCloseTo(before.y);
    // 한계
    expect(zoomAt(v, 1000, at).zoom).toBe(32);
    expect(zoomAt(v, 0.0001, at).zoom).toBe(0.05);
  });

  test("맞춤: 판 안에 다 보이고 가운데, 작은 이미지는 키우지 않는다", () => {
    const v = fitView([1024, 640], [920, 517], 16);
    expect(v.zoom).toBeCloseTo(485 / 640);
    expect(v.x + 1024 * v.zoom / 2).toBeCloseTo(460);
    expect(fitView([100, 50], [920, 517]).zoom).toBe(1);
  });
});

describe("조작 모드", () => {
  test("test_drag_shift_drag_click_modes", () => {
    const a = { x: 100, y: 100 };
    expect(gestureKind(a, { x: 101, y: 101 }, false)).toBe("click");
    expect(gestureKind(a, { x: 101, y: 101 }, true)).toBe("click");
    expect(gestureKind(a, { x: 140, y: 120 }, false)).toBe("template");
    expect(gestureKind(a, { x: 140, y: 120 }, true)).toBe("search");
    // 끈 사각형은 끝점이 있는 픽셀까지 담고, 방향과 무관하다
    expect(rectFromDrag({ x: 10.2, y: 5.9 }, { x: 19.7, y: 14.1 }, [100, 100])).toEqual([10, 5, 10, 10]);
    expect(rectFromDrag({ x: 19.7, y: 14.1 }, { x: 10.2, y: 5.9 }, [100, 100])).toEqual([10, 5, 10, 10]);
    // 이미지 밖은 잘린다
    expect(rectFromDrag({ x: -20, y: -3 }, { x: 5.5, y: 200 }, [100, 50])).toEqual([0, 0, 6, 50]);
    // 완전히 밖이면 없음
    expect(rectFromDrag({ x: -20, y: -30 }, { x: -5, y: -10 }, [100, 50])).toBeNull();
    // 결과는 늘 이미지 안이고 너비·높이 1 이상
    fc.assert(
      fc.property(
        fc.double({ min: -500, max: 1500, noNaN: true }),
        fc.double({ min: -500, max: 1500, noNaN: true }),
        fc.double({ min: -500, max: 1500, noNaN: true }),
        fc.double({ min: -500, max: 1500, noNaN: true }),
        (ax, ay, bx, by) => {
          const r = rectFromDrag({ x: ax, y: ay }, { x: bx, y: by }, [1024, 640]);
          return r === null || (r[0] >= 0 && r[1] >= 0 && r[2] >= 1 && r[3] >= 1 && r[0] + r[2] <= 1024 && r[1] + r[3] <= 640);
        },
      ),
    );
  });

  test("핸들로 크기 고치기: 반대쪽 변은 그대로, 너비·높이 1 이상", () => {
    const r: Rect = [10, 10, 20, 20];
    expect(resizeRect(r, "se", { x: 50.2, y: 45.7 }, [100, 100])).toEqual([10, 10, 40, 36]);
    expect(resizeRect(r, "nw", { x: 5, y: 2 }, [100, 100])).toEqual([5, 2, 25, 28]);
    expect(resizeRect(r, "e", { x: 0, y: 99 }, [100, 100])).toEqual([10, 10, 1, 20]);
    expect(resizeRect(r, "n", { x: 0, y: 200 }, [100, 100])).toEqual([10, 29, 20, 1]);
    expect(resizeRect(r, "e", { x: 500, y: 0 }, [100, 100])).toEqual([10, 10, 90, 20]);
  });
});

describe("클릭 지점", () => {
  test("test_anchor_offset_from_click_point", () => {
    const rect: Rect = [412, 380, 200, 64];
    // 9분할 지점은 상자 안 픽셀 (오른쪽·아래 끝 = x + w - 1), Python click_point와 같다
    expect(anchorPoint(rect, "top_left")).toEqual({ x: 412, y: 380 });
    expect(anchorPoint(rect, "bottom_right")).toEqual({ x: 611, y: 443 });
    expect(anchorPoint(rect, "center")).toEqual({ x: 511.5, y: 411.5 });
    expect(clickPoint(rect, "center", [0, 0])).toEqual({ x: 512, y: 412 });
    // 클릭한 픽셀을 고른 anchor 기준 오프셋으로: 다시 계산하면 그 픽셀이다 (상자 밖이어도)
    const click = { x: 700, y: 300 };
    for (const anchor of ANCHOR_ORDER) {
      const off = offsetFromClick(click, rect, anchor);
      expect(clickPoint(rect, anchor, off)).toEqual(click);
    }
    expect(offsetFromClick({ x: 412, y: 380 }, rect, "top_left")).toEqual([0, 0]);
    expect(offsetFromClick({ x: 420, y: 390 }, rect, "bottom_right")).toEqual([-191, -53]);
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 900 }),
        fc.integer({ min: 0, max: 900 }),
        fc.integer({ min: 1, max: 300 }),
        fc.integer({ min: 1, max: 300 }),
        fc.integer({ min: 0, max: 1500 }),
        fc.integer({ min: 0, max: 1500 }),
        fc.constantFrom(...ANCHOR_ORDER),
        (x, y, w, h, cx, cy, anchor) => {
          const r: Rect = [x, y, w, h];
          const p = clickPoint(r, anchor, offsetFromClick({ x: cx, y: cy }, r, anchor));
          return p.x === cx && p.y === cy;
        },
      ),
    );
  });
});

describe("키보드", () => {
  test("test_keyboard_nudge", () => {
    const size: Size = [100, 80];
    const r: Rect = [10, 10, 20, 20];
    expect(nudge(r, "ArrowRight", false, size)).toEqual([11, 10, 20, 20]);
    expect(nudge(r, "ArrowLeft", false, size)).toEqual([9, 10, 20, 20]);
    expect(nudge(r, "ArrowDown", true, size)).toEqual([10, 20, 20, 20]);
    expect(nudge(r, "ArrowUp", true, size)).toEqual([10, 0, 20, 20]);
    // 이미지 밖으로 나가지 않는다 (크기는 그대로)
    expect(nudge([75, 55, 20, 20], "ArrowRight", true, size)).toEqual([80, 55, 20, 20]);
    expect(nudge([75, 55, 20, 20], "ArrowDown", true, size)).toEqual([75, 60, 20, 20]);
    expect(nudge(r, "a", false, size)).toBeNull();
    expect(moveRect([0, 0, 120, 10], 5, 0, size)).toEqual([0, 0, 120, 10]);
  });
});

describe("정규화 검색 범위", () => {
  test("normalizedToPixels는 Python과 같은 식 (네 변을 0.5 올림)", () => {
    expect(normalizedToPixels([0.5, 0.5, 0.25, 0.25], [1024, 640])).toEqual([512, 320, 256, 160]);
    // 0.5는 늘 위로 (Python round는 짝수 쪽이라 쓰지 않는다)
    expect(normalizedToPixels([0.5 / 3, 0, 1 / 3, 1], [3, 2])).toEqual([1, 0, 1, 2]);
    // 클라이언트 밖은 자른다
    expect(normalizedToPixels([0.9, 0.9, 0.5, 0.5], [100, 100])).toEqual([90, 90, 10, 10]);
  });

  test("픽셀 / 크기 → 다시 픽셀이 같은 사각형", () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 4000 }), fc.integer({ min: 1, max: 4000 }), fc.nat(), fc.nat(), fc.nat(), fc.nat(), (cw, ch, a, b, c, d) => {
        const x = a % cw;
        const y = b % ch;
        const w = 1 + (c % (cw - x));
        const h = 1 + (d % (ch - y));
        const rect: Rect = [x, y, w, h];
        const back = normalizedToPixels(pixelsToRegion(rect, [cw, ch]), [cw, ch]);
        return back.every((v, i) => v === rect[i]);
      }),
    );
  });

  test("정지 화면 크기와 클라이언트 크기가 같으면 그대로", () => {
    expect(imageToClientRect([1, 2, 3, 4], [100, 100], [100, 100])).toEqual([1, 2, 3, 4]);
    expect(imageToClientRect([10, 20, 30, 40], [200, 100], [100, 50])).toEqual([5, 10, 15, 20]);
  });
});
