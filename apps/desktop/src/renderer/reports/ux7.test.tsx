// UX7 보고함: 진행 중 머리(단계·하는 일·기다림 이유·마지막 저장 화면), 목록 줄의 한 줄 결과, 진행 중 작업의 테스트 계정 등록,
// 활동 목록 접기("화면 캡처 ×12"), 실행 배지 "붙여 실행"
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc: () => new Promise(() => {}),
  on: () => () => {},
  app: {},
};

import { badgesOf } from "../runs/runListStore";
import { collapseActivity, lastScreenText, progressText, waitingText, type ActivityEntry } from "./activity";
import { JobHead, ReportProps, ReportsTab } from "./ReportsTab";
import { liveCredentials, mergeRows, rowSubText, useReports, type Row, type Unknown } from "./reportsStore";

function render(node: React.ReactElement): string {
  Object.assign(useReports.getInitialState(), useReports.getState());
  return renderToStaticMarkup(node);
}

const progress = { step: 2, total: 4, title: "경로 걷기", doing: "타이틀 터치 → 로그인 팝업 기다리는 중", at: "2026-11-15T01:00:00Z" };
const credential: Unknown = {
  id: "u-20261115-010000-abcd",
  rev: 1,
  question: "로그인 팝업에서 테스트 계정이 필요해요",
  human_only: true,
  state: "open",
  kind: "credential",
  secret_keys: ["login.id", "login.password"],
};

describe("진행 중 머리 글", () => {
  test("단계·하는 일 한 줄", () => {
    expect(progressText(progress)).toBe("2/4 경로 걷기 — 타이틀 터치 → 로그인 팝업 기다리는 중");
    expect(progressText({ ...progress, doing: null })).toBe("2/4 경로 걷기");
    expect(progressText(null)).toBe("");
  });

  test("기다림 이유: 계정 등록·실행 n초째", () => {
    expect(waitingText({ kind: "credential", since: "2026-11-15T01:00:00Z" })).toBe("테스트 계정 등록을 기다리는 중");
    const now = Date.parse("2026-11-15T01:00:12Z");
    expect(waitingText({ kind: "run", since: "2026-11-15T01:00:00Z" }, now)).toBe("실행 끝나기 기다림 12초째");
    expect(waitingText(null)).toBe("");
  });

  test("머리 그리기: 보호 화면이면 그림 없이 이름만", () => {
    const shot = render(
      <JobHead
        progress={progress}
        waiting={{ kind: "credential", since: "2026-11-15T01:00:00Z" }}
        lastScreen={{ key: "login_popup", title: "로그인 팝업", image: "map_abc.png" }}
      />,
    );
    expect(shot).toContain('data-part="job-progress"');
    expect(shot).toContain("2/4 경로 걷기 — 타이틀 터치");
    expect(shot).toContain('data-kind="credential"');
    expect(shot).toContain("테스트 계정 등록을 기다리는 중");
    expect(shot).toContain("kbimg://cache/map_abc.png");
    expect(shot).toContain("마지막 저장 화면: 로그인 팝업 (login_popup)");
    const hidden = render(<JobHead progress={null} waiting={null} lastScreen={{ key: "pw", title: null, image: null }} />);
    expect(hidden).toContain("마지막 저장 화면: pw");
    expect(hidden).not.toContain("<img");
    expect(render(<JobHead progress={null} waiting={null} lastScreen={null} />)).toBe("");
    expect(lastScreenText(null)).toBe("");
  });
});

describe("목록 줄 한 줄 결과", () => {
  test("끝난 작업은 headline, 진행 중이면 단계, 둘 다 없으면 묶음 수", () => {
    const rows = mergeRows(
      [
        { job: "j2", playbook: "entry", state: "running", started_at: "2026-11-15T02:00:00Z", progress, headline: null },
        { job: "j1", playbook: "entry", state: "done", started_at: "2026-11-15T01:00:00Z", headline: null },
      ],
      [{ job: "j1", playbook: "entry", state: "done", started_at: "2026-11-15T01:00:00Z", groups: 2, undecided: 0, headline: "로그인 팝업까지 — 계정 필요" }],
    );
    expect(rows.map(rowSubText)).toEqual(["2/4 경로 걷기 — 타이틀 터치 → 로그인 팝업 기다리는 중", "로그인 팝업까지 — 계정 필요"]);
    const old: Pick<Row, "state" | "groups" | "headline" | "progress"> = { state: "done", groups: 2, headline: null, progress: null };
    expect(rowSubText(old)).toBe("묶음 2");
    expect(rowSubText({ ...old, state: "running", groups: null })).toBe("보고 전");
  });

  test("보고함 목록에 한 줄 결과가 보인다", () => {
    const row: Row = {
      job: "j1",
      playbook: "entry",
      state: "done",
      startedAt: "2026-11-15T01:00:00Z",
      groups: 2,
      undecided: 0,
      hasReport: true,
      used: null,
      headline: "로그인 팝업까지 — 계정 필요",
      progress: null,
    };
    useReports.setState({ rows: [row], loaded: true });
    const html = render(<ReportsTab />);
    expect(html).toContain('data-part="row-sub"');
    expect(html).toContain("entry");
    expect(html).toContain("로그인 팝업까지 — 계정 필요");
    expect(html).not.toContain("묶음 2");
  });
});

describe("진행 중 작업에서 테스트 계정 등록", () => {
  test("열린 credential 질문만", () => {
    const answered = { ...credential, id: "u-20261115-010000-beef", state: "answered" };
    const text = { ...credential, id: "u-20261115-010000-cafe", kind: "question" as const };
    expect(liveCredentials([credential, answered, text]).map((u) => u.id)).toEqual([credential.id]);
  });

  test("보고가 생기기 전에도 질문 카드의 '테스트 계정 등록'", () => {
    const row: Row = {
      job: "j9",
      playbook: "entry",
      state: "running",
      startedAt: "2026-11-15T03:00:00Z",
      groups: null,
      undecided: 0,
      hasReport: false,
      used: null,
      headline: null,
      progress,
    };
    useReports.setState({ rows: [row], selected: "j9", detail: null, unknowns: [credential] });
    const html = render(<ReportProps />);
    expect(html).toContain('data-part="live-questions"');
    expect(html).toContain('data-part="register-credential"');
    expect(html).toContain("login.id, login.password");
    // 값은 화면에 없다 (키 이름만)
    useReports.setState({ unknowns: [] });
    expect(render(<ReportProps />)).not.toContain('data-part="live-questions"');
  });
});

describe("활동 목록 접기 (MCP 호출 한 번 = 한 줄)", () => {
  const e = (seq: number, tool: string, target = "", result = "ok"): ActivityEntry => ({ seq, at: "2026-11-15T01:00:00.000Z", tool, result, target });

  test("같은 도구가 연달아 나오면 '화면 캡처 ×12' — 대상이 다르면 도구 이름만", () => {
    const shots = Array.from({ length: 12 }, (_, i) => e(i + 1, "kb_screen_capture", i % 2 === 0 ? "@game" : "타이틀"));
    const rows = collapseActivity([...shots, e(13, "kb_explore_step", "@game"), e(14, "kb_explore_step", "@game")]);
    expect(rows.map((r) => [r.text, r.count])).toEqual([
      ["화면 캡처", 12],
      ["탐색 한 걸음: @game", 2],
    ]);
  });
});

describe("실행 배지", () => {
  test("붙여 실행", () => {
    expect(badgesOf({ source: "agent_attach" } as never).map((b) => b.text)).toEqual(["붙여 실행"]);
  });
});
