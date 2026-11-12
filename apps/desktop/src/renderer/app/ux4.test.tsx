// UX4 화면 사용성: 활동 막대 보고함, 오른쪽 끌기 화면 이동, 화면 지도 선택 → 속성 탭, 노드 "실행 전" 옵션
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";
import { focusMark } from "../graph/mapping";
import { graphFocus, nodeFocus, setGraphFocus, setNodeFocus } from "../graph/commands";
import { inboxCount, openReportsTab, REPORTS_TAB_PATH } from "../reports/reportsStore";
import { MAP } from "../screens/map.testutil";
import { select, useMap } from "../screens/mapStore";
import { ScreenPropsView, ScreenSidebarView } from "../screens/ScreenSidebar";
import { useTabs } from "../store/tabs";
import { useUi } from "../store/ui";
import { createRightDragPan } from "./rightDragPan";
import { ActivityBar, ReportsActivityView } from "./Sidebar";

(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc: () => new Promise(() => {}),
  on: () => () => {},
  app: {},
};

describe("활동 막대 보고함", () => {
  test("보고함 단추: 상태 막대와 같은 수(inboxCount)의 배지, 활성이면 눌린 상태, 누르면 보고함 탭", () => {
    const rows = [{ undecided: 2, state: "done" }, { undecided: 0, state: "running" }, { undecided: 0, state: "done" }] as never;
    expect(inboxCount(rows)).toBe(2);
    const html = renderToStaticMarkup(<ReportsActivityView count={inboxCount(rows)} active={false} />);
    expect(html).toContain('data-part="activity-reports"');
    expect(html).toMatch(/data-part="activity-reports-badge"[^>]*>2</);
    expect(html).toContain('aria-label="보고함, 2건"');
    expect(renderToStaticMarkup(<ReportsActivityView count={0} active />)).toMatch(/aria-label="보고함" aria-pressed="true"/);
    expect(renderToStaticMarkup(<ReportsActivityView count={0} active={false} />)).not.toContain("activity-reports-badge");
    // 활동 막대에 붙어 있다
    expect(renderToStaticMarkup(<ActivityBar />)).toContain('data-part="activity-reports"');
    renderToStaticMarkup(<ReportsActivityView count={0} active={false} />);
    openReportsTab();
    expect(useTabs.getState().active).toBe(REPORTS_TAB_PATH);
  });
});

describe("오른쪽 단추 끌기 화면 이동", () => {
  test("4px 넘게 움직이면 화면을 옮기고 그 뒤 메뉴를 막는다", () => {
    const pan = vi.fn();
    const end = vi.fn();
    const d = createRightDragPan(pan, end);
    expect(d.down({ button: 2, clientX: 100, clientY: 100 })).toBe(true);
    d.move({ clientX: 102, clientY: 101 }); // 문턱 아래
    expect(pan).not.toHaveBeenCalled();
    d.move({ clientX: 110, clientY: 104 });
    d.move({ clientX: 120, clientY: 104 });
    expect(pan.mock.calls).toEqual([
      [10, 4],
      [10, 0],
    ]);
    d.up();
    expect(end).toHaveBeenCalledTimes(1);
    expect(d.contextMenu()).toBe(true);
    expect(d.contextMenu()).toBe(false); // 한 번만
  });

  test("짧은 오른쪽 클릭은 지금처럼 메뉴, 왼쪽 단추는 건드리지 않는다", () => {
    const pan = vi.fn();
    const d = createRightDragPan(pan);
    expect(d.down({ button: 0, clientX: 0, clientY: 0 })).toBe(false);
    d.move({ clientX: 50, clientY: 50 });
    expect(pan).not.toHaveBeenCalled();
    d.down({ button: 2, clientX: 0, clientY: 0 });
    d.move({ clientX: 2, clientY: 2 });
    d.up();
    expect(d.contextMenu()).toBe(false);
    expect(pan).not.toHaveBeenCalled();
  });
});

describe("화면 지도 선택 → 속성 탭", () => {
  test("사이드바에는 목록만, 고른 카드 정보는 속성 탭에", () => {
    const [, bag] = MAP.screens;
    const side = renderToStaticMarkup(<ScreenSidebarView map={MAP} selected={bag!.node} />);
    expect(side).toContain('data-part="map-row"');
    expect(side).not.toContain('data-part="map-selected"');
    const props = renderToStaticMarkup(<ScreenPropsView map={MAP} selected={bag!.node} />);
    expect(props).toContain('data-part="map-selected"');
    expect(props).toContain("가방");
    expect(props).toContain('data-part="map-ask-flow"');
    expect(renderToStaticMarkup(<ScreenPropsView map={MAP} selected={null} />)).toContain("map-props-empty");
  });

  test("카드를 고르면 접힌 속성 창을 펴고 속성 탭으로", () => {
    useUi.setState({ inspectorOpen: false, rightTab: "agent" });
    useMap.setState({ map: MAP });
    select("bag");
    expect(useMap.getState().selected).toBe("bag");
    expect(useUi.getState()).toMatchObject({ inspectorOpen: true, rightTab: "props" });
    useUi.setState({ inspectorOpen: false });
    select(null);
    expect(useUi.getState().inspectorOpen).toBe(false);
  });
});

describe("노드 실행 전: 입력 전 게임 창 앞으로", () => {
  const graph = { nodes: { n_key: { type: "core.input.key", version: 1 } } };
  test("기본 켜짐, 노드 값 저장·지우기 (config는 건드리지 않는다)", () => {
    expect(graphFocus(graph)).toBe(true);
    expect(nodeFocus(graph, "n_key")).toBeNull();
    const off = setNodeFocus(graph, "n_key", false);
    expect(off).toEqual({ nodes: { n_key: { type: "core.input.key", version: 1, focus_before_input: false } } });
    expect(nodeFocus(off, "n_key")).toBe(false);
    expect(setNodeFocus(off, "n_key", null)).toEqual(graph);
    const graphOff = setGraphFocus(graph, false);
    expect(graphOff).toMatchObject({ focus_before_input: false });
    expect(graphFocus(graphOff)).toBe(false);
    expect(setGraphFocus(graphOff, true)).toEqual(graph);
  });

  test("노드 머리 표시는 기본값과 다를 때만, 입력 효과 노드만", () => {
    const input = ["input"];
    expect(focusMark(graph, { focus_before_input: true }, input)).toBeUndefined();
    expect(focusMark(graph, { focus_before_input: false }, input)).toBe("off");
    expect(focusMark(graph, {}, input)).toBeUndefined();
    expect(focusMark({ ...graph, focus_before_input: false }, { focus_before_input: true }, input)).toBe("on");
    expect(focusMark({ ...graph, focus_before_input: false }, { focus_before_input: false }, input)).toBeUndefined();
    expect(focusMark(graph, { focus_before_input: false }, ["capture"])).toBeUndefined();
  });
});
