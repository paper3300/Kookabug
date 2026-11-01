// target 사양 편집·미리보기 요청 고르기 (M2 계획 2.9 "사양 편집"·"미리보기")
import { describe, expect, test } from "vitest";
import { jsonEqual } from "../graph/valueOps";
import { sameStamp, stampOf } from "../store/generations";
import {
  clampThreshold,
  rebaseSpec,
  setAnchor,
  setMultiscale,
  setOffset,
  setRegion,
  setRgb,
  setThreshold,
  specFields,
} from "./spec";
import { previewRequest, previewSummary, saveBlocker, targetDirty, type Frame, type PreviewResult, type TargetDoc } from "./targetStore";

const ORIGINAL = {
  format: "kookabug.target/0",
  image: "start_button.png",
  x_note: "keep",
  click: { anchor: "center", offset: [0, 0] },
  recorded: { client_size: [1024, 640], dpi: 96 },
};

describe("사양 편집", () => {
  test("기본값: 임계값 0.85, 색 확인·배율 켬, 중앙", () => {
    expect(specFields({})).toEqual({ threshold: 0.85, rgb: true, multiscale: true, anchor: "center", offset: [0, 0], region: null });
  });

  test("고친 경로만 바뀌고 모르는 키·다른 칸은 그대로 (같은 객체 공유)", () => {
    const next = setThreshold(ORIGINAL, 0.9);
    expect(next.match).toEqual({ threshold: 0.9 });
    expect(next.x_note).toBe("keep");
    expect(next.click).toBe(ORIGINAL.click);
    expect(next.recorded).toBe(ORIGINAL.recorded);
    expect(ORIGINAL).not.toHaveProperty("match");
  });

  test("임계값은 0.50~0.99, 0.01 단위", () => {
    expect(clampThreshold(0.3)).toBe(0.5);
    expect(clampThreshold(1)).toBe(0.99);
    expect(clampThreshold(0.8549)).toBe(0.85);
    expect(specFields(setThreshold({}, 0.876)).threshold).toBe(0.88);
  });

  test("색 확인·배율: 끄면 rgb false·methods [template], 다시 켜면 처음 값(없었으면 키 없음)", () => {
    expect(setRgb(ORIGINAL, false).match).toEqual({ rgb: false });
    const off = setMultiscale(ORIGINAL, false, ORIGINAL);
    expect(off.match).toEqual({ methods: ["template"] });
    expect(specFields(off).multiscale).toBe(false);
    const on = setMultiscale(off, true, ORIGINAL);
    expect(specFields(on).multiscale).toBe(true);
    expect(jsonEqual(on, ORIGINAL)).toBe(true);
    const withMethods = { ...ORIGINAL, match: { methods: ["template", "template_multiscale"] } };
    expect(setMultiscale(setMultiscale(withMethods, false, withMethods), true, withMethods).match).toEqual(withMethods.match);
    const templateOnly = { ...ORIGINAL, match: { methods: ["template"] } };
    expect(setMultiscale(templateOnly, true, templateOnly).match).toEqual({ methods: ["template_multiscale", "template"] });
  });

  test("클릭 지점·검색 범위", () => {
    const s = setOffset(setAnchor(ORIGINAL, "bottom_right"), [3, -2.5]);
    expect(s.click).toEqual({ anchor: "bottom_right", offset: [3, -2.5] });
    const r = setRegion(ORIGINAL, [0.1, 0.2, 0.3, 0.4]);
    expect(specFields(r).region).toEqual([0.1, 0.2, 0.3, 0.4]);
    // 지우면 비게 된 search도 지운다
    expect(setRegion(r, null)).not.toHaveProperty("search");
  });

  test("rebaseSpec: 보낸 뒤 바꾼 경로만 서버 사양 위에 얹는다", () => {
    const sent = { format: "kookabug.target/0", click: { anchor: "center" }, search: { region: [0, 0, 0.5, 0.5] } };
    const server = { ...sent, image: "a.png", recorded: { client_size: [1024, 640], dpi: 96 }, search: { region: [0, 0, 0.500001, 0.5] } };
    // 바꾼 것이 없으면 서버 사양 그대로
    expect(rebaseSpec(sent, sent, server)).toBe(server);
    // 임계값 추가·anchor 변경·검색 범위 지우기: 서버가 채운 image·recorded는 남는다
    const current = { format: "kookabug.target/0", click: { anchor: "top_left" }, match: { threshold: 0.9 } };
    expect(rebaseSpec(sent, current, server)).toEqual({
      format: "kookabug.target/0",
      image: "a.png",
      recorded: { client_size: [1024, 640], dpi: 96 },
      click: { anchor: "top_left" },
      match: { threshold: 0.9 },
    });
    // 바꾸지 않은 검색 범위는 서버가 맞춘 값
    const onlyThreshold = { ...sent, match: { threshold: 0.8 } };
    expect((rebaseSpec(sent, onlyThreshold, server).search as { region: number[] }).region).toEqual([0, 0, 0.500001, 0.5]);
  });

  test("세대 확인: 적어 둔 칸이 하나라도 바뀌었거나 문서가 없으면 아니다", () => {
    const doc = { instance: 1, edits: 2, reloadSeq: 3 };
    const stamp = stampOf(doc, ["instance", "reloadSeq"]);
    expect(sameStamp({ ...doc, edits: 9 }, stamp)).toBe(true);
    expect(sameStamp({ ...doc, reloadSeq: 4 }, stamp)).toBe(false);
    expect(sameStamp({ ...doc, instance: 2 }, stamp)).toBe(false);
    expect(sameStamp(undefined, stamp)).toBe(false);
  });

  test("__proto__ 키도 보통 키로 두고 프로토타입을 바꾸지 않는다", () => {
    const parsed = JSON.parse('{"format":"kookabug.target/0","image":"a.png","__proto__":{"x":1}}') as Record<string, unknown>;
    const next = setThreshold(parsed, 0.9);
    expect(Object.getPrototypeOf(next)).toBe(Object.prototype);
    expect(Object.hasOwn(next, "__proto__")).toBe(true);
  });
});

const FRAME: Frame = {
  frame_id: "f1",
  width: 1024,
  height: 640,
  dpi: 96,
  client_size: [1024, 640],
  image: { cache: "f1.png", width: 1024, height: 640 },
};

function doc(patch: Partial<TargetDoc>): TargetDoc {
  return {
    path: "targets/a.target.json",
    instance: 1,
    status: "ready",
    error: null,
    isNew: false,
    baseRevision: "r",
    savedSpec: ORIGINAL,
    spec: ORIGINAL,
    image: { workspace: "targets/start_button.png", width: 200, height: 64 },
    diagnostics: [],
    frame: FRAME,
    frameSource: "title.png",
    frameExpired: false,
    frameGen: 0,
    frameRequest: 0,
    frameLoading: false,
    edits: 0,
    reloadSeq: 0,
    template: null,
    preview: null,
    previewNote: null,
    previewSeq: 0,
    previewPending: false,
    saving: false,
    conflict: null,
    saveError: null,
    saved: null,
    saves: 0,
    origin: null,
    ...patch,
  };
}

describe("미리보기 요청 (검수 M5)", () => {
  test("새로 고른 영역은 template.crop, 아니면 기존 이미지 + base_path", () => {
    const crop = previewRequest(doc({ template: [412, 380, 200, 64] }));
    expect(crop).toEqual({
      params: { frame_id: "f1", spec: ORIGINAL, template: { crop: { frame_id: "f1", rect: [412, 380, 200, 64] } } },
    });
    const image = previewRequest(doc({}));
    expect(image).toEqual({
      params: { frame_id: "f1", spec: ORIGINAL, template: { image: "start_button.png" }, base_path: "targets/a.target.json" },
    });
  });

  test("보낼 수 없으면 이유", () => {
    expect(previewRequest(doc({ frame: null }))).toEqual({ note: "정지 화면을 고르세요" });
    expect(previewRequest(doc({ isNew: true, spec: { format: "kookabug.target/0" } }))).toEqual({
      note: "정지 화면에서 찾을 영역을 드래그하세요",
    });
  });
});

describe("결과 문구 (검수 M6)", () => {
  const base: PreviewResult = {
    found: true,
    match: { rect: [1, 2, 3, 4], score: 0.9312, scale: 1, method: "template", click: [2, 3] },
    best: null,
    threshold: 0.85,
    expected_scale: 1,
    search: [0, 0, 1024, 640],
    search_rect_px: [0, 0, 1024, 640],
    candidates: [{}, {}, {}, {}],
    elapsed_ms: 3,
    seq: 1,
  };
  test("찾음·못 찾음과 (최고) 점수. 후보 수는 쓰지 않는다", () => {
    expect(previewSummary(base)).toBe("찾음 · 점수 0.93 · 배율 1.00");
    const miss = { ...base, found: false, match: null, best: { score: 0.6149, rect: [0, 0, 3, 4] } };
    expect(previewSummary(miss)).toBe("못 찾음 · 최고 점수 0.61");
    expect(previewSummary(miss)).not.toContain("4");
  });
});

describe("저장 가능·dirty", () => {
  test("새 target은 영역이 있어야 저장, 영역이 있으면 정지 화면도 있어야", () => {
    expect(saveBlocker(doc({ isNew: true }))).toBe("정지 화면에서 영역을 드래그하세요");
    expect(saveBlocker(doc({ isNew: true, template: [0, 0, 5, 5] }))).toBeNull();
    expect(saveBlocker(doc({ template: [0, 0, 5, 5], frame: null }))).toBe("정지 화면을 다시 고르세요");
    expect(saveBlocker(doc({}))).toBeNull();
  });

  test("dirty = 새 파일·새 영역·디스크와 다른 사양", () => {
    expect(targetDirty(doc({}))).toBe(false);
    expect(targetDirty(doc({ isNew: true }))).toBe(true);
    expect(targetDirty(doc({ template: [0, 0, 1, 1] }))).toBe(true);
    expect(targetDirty(doc({ spec: setThreshold(ORIGINAL, 0.9) }))).toBe(true);
    // 고쳤다가 같은 값으로 되돌리면 dirty가 아니다
    expect(targetDirty(doc({ spec: { ...ORIGINAL } }))).toBe(false);
  });
});
