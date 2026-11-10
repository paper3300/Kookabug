// 속성 창 대상 미리보기: 워크스페이스 그림 주소(구간 인코딩·?v=), 찾기 조건 요약, 그림 없는 대상
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { TargetPreviewView } from "./TargetPreview";

const base = { diagnostics: [], revision: "r1" };

describe("대상 미리보기", () => {
  test("그림은 kbimg://ws/ 주소, 요약은 크기·일치·범위·클릭", () => {
    const html = renderToStaticMarkup(
      <TargetPreviewView
        path="targets/인벤토리/window_title.target.json"
        result={{
          ...base,
          image: { workspace: "targets/인벤토리/window title.png", width: 120, height: 32 },
          spec: { format: "kookabug.target/0", image: "window title.png", click: { anchor: "top_left", offset: [4, -2] }, match: { threshold: 0.9 }, search: { region: [0, 0, 0.5, 0.5] } },
        }}
        version={3}
        onOpen={() => {}}
      />,
    );
    expect(html).toContain(`src="kbimg://ws/targets/${encodeURIComponent("인벤토리")}/window%20title.png?v=3"`);
    expect(html).toContain("120×32 · 일치 90% · 정한 범위에서 찾기 · 클릭 좌상 (4, -2)");
    expect(html).toContain('data-part="open-target"');
  });

  test("그림이 없으면 안내만", () => {
    const html = renderToStaticMarkup(
      <TargetPreviewView path="targets/a.target.json" result={{ ...base, image: null, spec: { format: "kookabug.target/0" } }} version={1} onOpen={() => {}} />,
    );
    expect(html).not.toContain("<img");
    expect(html).toContain("저장된 그림이 없어요");
    expect(html).toContain("화면 전체에서 찾기 · 클릭 중앙");
  });
});
