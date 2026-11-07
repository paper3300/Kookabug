// 화면 지도 컴포넌트 렌더 (M7 B5): 카드(썸네일 없음 이유·후보 점선·선택·편집기 캐시 URL만), 사이드바(목록·선택
// 상세·확인 전 — 판정 조건 없는 후보는 옮기기 꺼짐)
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { MAP, S } from "./map.testutil";
import { noShotText, ScreenCard } from "./ScreenCard";
import { ScreenSidebarView } from "./ScreenSidebar";

describe("렌더", () => {
  test("카드: 썸네일 없음 이유, 후보 점선·선택 표시, 썸네일은 편집기 캐시 URL만", () => {
    const [, , up, loading] = MAP.screens;
    const html = renderToStaticMarkup(<ScreenCard card={loading!} x={10} y={20} selected start="lobby" onPointerDown={() => {}} />);
    expect(html).toContain('data-state="explored"');
    expect(html).toContain('data-selected="true"');
    expect(html).toContain(noShotText(loading!));
    expect(noShotText(loading!)).toBe("보호로 스크린샷 없음");
    const withThumb = renderToStaticMarkup(
      <ScreenCard card={{ ...up!, thumb: "map_abc.png" }} x={0} y={0} selected={false} start={null} onPointerDown={() => {}} />,
    );
    expect(withThumb).toContain('src="kbimg://cache/map_abc.png"');
  });

  test("사이드바: 화면 목록·선택 상세·확인 전 (판정 조건 없는 후보는 옮기기 꺼짐)", () => {
    const html = renderToStaticMarkup(<ScreenSidebarView map={MAP} selected={`x:${S}/loading`} />);
    expect(html).toContain("화면 · 2");
    expect(html).toContain('data-part="map-detect-missing"');
    expect(html).toContain("보호로 스크린샷 없음");
    const loadingRow = html.slice(html.indexOf(`data-node="x:${S}/loading"`, html.indexOf("map-candidate")));
    expect(loadingRow.slice(0, loadingRow.indexOf("</div>"))).toMatch(/data-part="map-promote" disabled=""/);
    expect(html).toContain("가방(탐색) → bag");
  });

  test("UI 요소 칩은 종류 글자 (이름 앞 글자 아님)", () => {
    const [, , up] = MAP.screens;
    const element = { name: "Server 1", kind: "list", rect: [0, 0, 0.1, 0.1] as [number, number, number, number] };
    const withElement = { ...up!, elements: [element] };
    const map = { ...MAP, screens: MAP.screens.map((c) => (c.node === up!.node ? withElement : c)) };
    const html = renderToStaticMarkup(<ScreenSidebarView map={map} selected={up!.node} />);
    expect(html).toMatch(/data-kind="list">목록<\/span><span>Server 1<\/span>/);
    expect(html).not.toContain(">Se<");
  });
});
