// 화면 지도 상태의 순수 계산 (M7 B5): 출처 색·범례·요약·카드 글자·확인 전 묶음·최단 경로·에이전트 요청 문장·
// 탐색기 경로 → 노드·상태 바 글자 (카드·사이드바 렌더는 screens.test.tsx)
import { describe, expect, test } from "vitest";
import {
  activeSession,
  agentRequest,
  cardMeta,
  cardSource,
  confirmedCards,
  edgeSource,
  elapsedText,
  inputToolText,
  legend,
  mapSummary,
  nodeOfPath,
  pendingGroups,
  recoveryText,
  shortestPath,
} from "./mapStore";
import { card, MAP, S } from "./map.testutil";
import { promoteParams, promotedText } from "./promote";
import { recordOverrideText } from "../runs/runListStore";

describe("기록 뷰어 머리 줄 (B2a 넘김)", () => {
  test("에이전트 제어 실행 기록 강제", () => {
    expect(recordOverrideText({ record_override: { by: "agent_control", screenshots: "off" } })).toBe(
      "에이전트 제어 실행 · 이미지 기록 없음 · 비밀값 가림",
    );
    expect(recordOverrideText({ graph: "tests/a.graph.json" })).toBeNull();
    expect(recordOverrideText(null)).toBeNull();
  });
});

describe("출처·범례·요약", () => {
  test("카드·간선 출처", () => {
    expect(MAP.screens.map(cardSource)).toEqual(["manual", "explored", "explored", "explored"]);
    expect(MAP.edges.map(edgeSource)).toEqual(["manual", "explored", "run", "explored"]);
  });

  test("범례는 있는 출처만, 순서 고정", () => {
    expect(legend(MAP)).toEqual(["explored", "run", "manual"]);
    expect(legend({ screens: [card({ node: "a" })], edges: [] })).toEqual(["manual"]);
    expect(legend(null)).toEqual([]);
  });

  test("상태 바 요약: 화면 N · 이동(가 본) M · 미탐색 K", () => {
    expect(mapSummary(MAP)).toEqual({ screens: 4, moves: 3, untried: 1 });
    expect(mapSummary(null)).toEqual({ screens: 0, moves: 0, untried: 0 });
  });
});

describe("카드·사이드바 묶음", () => {
  test("카드 글자: 시작 화면·새로 발견·판정 조건 없음·탐색 추가", () => {
    const [lobby, bag, up, loading] = MAP.screens;
    expect(cardMeta(lobby!, "lobby")).toBe("시작 화면 · 이동 2");
    expect(cardMeta(bag!, "lobby")).toBe("이동 0 · 탐색 추가 1");
    expect(cardMeta(up!, "lobby")).toBe("새로 발견 · 이동 3 · 요소 1");
    expect(cardMeta(loading!, "lobby")).toBe("판정 조건 없음 · 이동 0");
  });

  test("확정 화면 목록은 제목 순, 확인 전은 세션별 후보 + 합치기 후보", () => {
    expect(confirmedCards(MAP).map((c) => c.node)).toEqual(["bag", "lobby"]);
    const [g] = pendingGroups(MAP);
    expect(g!.title).toBe("상점 탐색");
    expect(g!.status).toBe("active");
    expect(g!.cards.map((c) => c.key)).toEqual(["upgrade", "loading"]);
    expect(g!.merges.map((m) => m.of)).toEqual(["bag"]);
    expect(pendingGroups(null)).toEqual([]);
  });

  test("탐색기 경로 → 노드 (후보 파일, 합치기 후보는 합칠 화면)", () => {
    expect(nodeOfPath(MAP, "screens/lobby.screen.json")).toBe("lobby");
    expect(nodeOfPath(MAP, `screens/_explored/${S}/upgrade.screen.json`)).toBe(`x:${S}/upgrade`);
    expect(nodeOfPath(MAP, `screens/_explored/${S}/bag2.screen.json`)).toBe("bag");
    expect(nodeOfPath(MAP, "screens/none.screen.json")).toBeNull();
  });
});

describe("경로·요청 문장", () => {
  test("가 본 이동만 따라 최단 경로", () => {
    expect(shortestPath(MAP.edges, "lobby", `x:${S}/upgrade`)).toEqual(["lobby", "bag", `x:${S}/upgrade`]);
    expect(shortestPath(MAP.edges, "lobby", "lobby")).toEqual(["lobby"]);
    expect(shortestPath(MAP.edges, `x:${S}/upgrade`, "lobby")).toBeNull();
  });

  test("플로 만들기·테스트 작성 요청: @screen 칩 + 기본 문장(경로 포함)", () => {
    const flow = agentRequest(MAP, `x:${S}/upgrade`, "flow");
    expect(flow.chip).toBe("@screen upgrade");
    expect(flow.text).toBe("로비에서 장비 강화까지 가는 서브그래프(플로)를 만들어 줘. 경로: 로비 → 가방 → 장비 강화.");
    expect(agentRequest(MAP, "lobby", "test").chip).toBe("@screen lobby");
    expect(agentRequest({ ...MAP, start: null }, "bag", "flow").text).toContain("이어진 경로가 없으니");
  });
});

describe("상태 바·안내 글자", () => {
  test("탐색 세션·경과", () => {
    expect(activeSession(MAP.sessions)?.id).toBe(S);
    expect(activeSession([])).toBeNull();
    expect(elapsedText("2026-11-07T10:30:00Z", Date.parse("2026-11-07T10:33:12Z"))).toBe("3:12");
    expect(elapsedText("깨진 시각", 0)).toBe("0:00");
  });

  test("입력 도구", () => {
    expect(inputToolText("ask", false)).toBe("입력 도구: 확인 후 실행");
    expect(inputToolText("allow", false)).toBe("입력 도구: 바로 실행");
    expect(inputToolText("ask", true)).toBe("입력 도구: 이 탐색 동안 허용됨");
    expect(inputToolText(null, false)).toBeNull();
  });

  test("남은 승격 정리 안내·승격 결과", () => {
    expect(recoveryText("x")).toContain("kookabug screen recover --show");
    expect(promotedText(true)).toBe("옮겼어요 — 정리는 다음에 마저 해요");
    expect(promotedText(false)).toBe("옮겼어요");
  });

  test("확인·승격 params는 같은 값 (revision이 맞게)", () => {
    const form = { id: " shop ", title: "상점", description: "", folder: "", replaceShot: true, replaceDetect: false };
    expect(promoteParams({ mode: "new", node: "x", session: S, key: "upgrade", title: null, of: null }, form)).toEqual({
      session: S,
      key: "upgrade",
      mode: "new",
      id: "shop",
    });
    expect(promoteParams({ mode: "merge", node: "x", session: S, key: "bag2", title: null, of: "bag" }, form)).toEqual({
      session: S,
      key: "bag2",
      mode: "merge",
      id: "bag",
      replace_shot: true,
      replace_detect: false,
    });
  });
});
