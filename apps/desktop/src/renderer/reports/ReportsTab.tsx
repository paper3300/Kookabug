// 보고함 탭 (M8 계획 3.17 "보고함 UI(최소)", KB문서 12장). 목록(작업·상태·묶음 수) / 상세(묶음별 항목, 되돌리기·
// 묶음 수락/거절, 질문 답하기, 증거 묶음·보고서 파일 열기). 머리에 보안 경계 문구(3.15)
import { useEffect, useState } from "react";
import { openFileTab } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { SECURITY_BOUNDARY } from "../wizard/boundary";
import {
  answerUnknown,
  canCancel,
  cancelJob,
  decidable,
  decideGroup,
  initReports,
  KIND_TEXT,
  openQuestions,
  reloadReports,
  revertable,
  revertAdoption,
  selectReport,
  STATE_TEXT,
  useReports,
  type Report,
  type ReportItem,
  type Unknown,
} from "./reportsStore";
import css from "./reports.module.css";

function shortTime(iso: string): string {
  const m = /T(\d\d:\d\d)/.exec(iso);
  return m === null ? iso : `${iso.slice(5, 10)} ${m[1]}`;
}

const SUMMARY_LABEL: Record<string, string> = {
  features: "기능",
  claims: "주장 후보",
  guesses: "추측",
  unknowns: "미지수",
  screens: "화면",
  cheat_candidates: "치트 후보",
};

/** Init 요약 (KB문서 9장: 기능·주장 후보·추측·미지수·화면 수) */
function summaryText(summary: Record<string, unknown>): string {
  return Object.entries(summary)
    .map(([k, v]) => `${SUMMARY_LABEL[k] ?? k} ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

function Message({ k }: { k: string }) {
  const text = useReports((s) => s.messages[k]);
  if (text === undefined || text === "") return null;
  return (
    <span className={css.message} role="status" data-part="action-message">
      {text}
    </span>
  );
}

function Item({ item }: { item: ReportItem }) {
  const reverted = useReports((s) => s.reverted);
  const pending = useReports((s) => s.pending);
  const key = `revert:${item.adoption ?? ""}`;
  return (
    <li className={css.item} data-kind={item.kind}>
      <span className={css.kind} data-kind={item.kind}>
        {KIND_TEXT[item.kind] ?? item.kind}
      </span>
      <span className={css.itemBody}>
        {item.case !== undefined && <span className={css.mono}>{item.case}</span>}
        {item.checks !== undefined && <span className={css.muted}>확인: {item.checks.join(" · ")}</span>}
        {item.detail !== undefined && <span>{item.detail}</span>}
        {item.claims !== undefined && item.claims.length > 0 && (
          <span className={css.muted}>관련 주장: {item.claims.map((c) => `${c.id} r${c.rev}`).join(", ")}</span>
        )}
        {item.cheat !== undefined && <span>치트 후보 {item.cheat}</span>}
        {item.summary !== undefined && <span className={css.muted}>{summaryText(item.summary)}</span>}
        {item.evidence !== undefined && (
          <button
            type="button"
            className={css.link}
            data-part="open-evidence"
            onClick={() => openFileTab(`knowledge/evidence/${item.evidence}/manifest.json`)}
          >
            증거 묶음 {item.evidence} 열기
          </button>
        )}
        {item.adoption !== undefined && reverted.has(item.adoption) && <span className={css.muted}>되돌림</span>}
        <Message k={key} />
      </span>
      {revertable(item, reverted) && (
        <button
          type="button"
          className={css.button}
          data-part="revert"
          disabled={pending.has(key)}
          onClick={() => void revertAdoption(item.adoption!)}
        >
          되돌리기
        </button>
      )}
    </li>
  );
}

function Question({ u }: { u: Unknown }) {
  const [text, setText] = useState("");
  const pending = useReports((s) => s.pending.has(`answer:${u.id}`));
  return (
    <li className={css.question} data-unknown={u.id}>
      <span className={css.kind} data-kind="question">
        사람만 답할 수 있음
      </span>
      <span className={css.itemBody}>
        <span>{u.question}</span>
        <span className={css.answerRow}>
          <input className={css.input} aria-label={`답: ${u.question}`} value={text} onChange={(e) => setText(e.target.value)} />
          <button
            type="button"
            className={css.button}
            disabled={pending || text.trim() === ""}
            onClick={() => void answerUnknown(u, text.trim()).then(() => setText(""))}
          >
            답하기
          </button>
        </span>
        <Message k={`answer:${u.id}`} />
      </span>
    </li>
  );
}

function Detail({ report }: { report: Report }) {
  const unknowns = useReports((s) => s.unknowns);
  const pending = useReports((s) => s.pending);
  const questions = openQuestions(report, unknowns);
  return (
    <div className={css.detail} data-part="report-detail" data-job={report.job}>
      <div className={css.detailHead}>
        <span className={css.title}>
          {report.playbook} · {STATE_TEXT[report.state] ?? report.state}
        </span>
        <span className={css.muted}>
          {report.job}
          {report.budget?.runs !== undefined && ` · 실행 ${report.budget.runs[0]}/${report.budget.runs[1]}`}
          {report.budget?.minutes !== undefined && ` · ${report.budget.minutes[0]}/${report.budget.minutes[1]}분`}
        </span>
        {report.rendered !== undefined && (
          <button type="button" className={css.link} data-part="open-rendered" onClick={() => openFileTab(report.rendered!)}>
            보고서 열기
          </button>
        )}
      </div>
      {report.groups.length === 0 && <p className={css.muted}>항목이 없어요.</p>}
      {report.groups.map((g) => {
        const key = `decide:${report.job}:${g.key}`;
        return (
          <section key={g.key} className={css.group} data-group={g.key} data-decided={g.decision !== null}>
            <div className={css.groupHead}>
              <span className={css.groupTitle}>{g.title}</span>
              {g.decision !== null && (
                <span className={css.muted}>{g.decision.decision === "accept" ? "수락함" : "거절함"}</span>
              )}
              {decidable(g) && (
                <span className={css.groupActions}>
                  <button
                    type="button"
                    className={css.button}
                    data-part="accept"
                    disabled={pending.has(key)}
                    onClick={() => void decideGroup(report.job, g.key, "accept")}
                  >
                    묶음 수락
                  </button>
                  <button
                    type="button"
                    className={css.button}
                    data-part="reject"
                    disabled={pending.has(key)}
                    onClick={() => void decideGroup(report.job, g.key, "reject")}
                  >
                    거절
                  </button>
                </span>
              )}
            </div>
            <Message k={key} />
            <ul className={css.items}>
              {g.items.map((item, i) => (
                <Item key={i} item={item} />
              ))}
            </ul>
          </section>
        );
      })}
      {questions.length > 0 && (
        <section className={css.group} data-part="questions">
          <div className={css.groupHead}>
            <span className={css.groupTitle}>질문 · 답하지 않아도 작업은 계속돼요</span>
          </div>
          <ul className={css.items}>
            {questions.map((u) => (
              <Question key={u.id} u={u} />
            ))}
          </ul>
        </section>
      )}
      {typeof report.notes === "string" && report.notes.trim() !== "" && (
        <section className={css.group}>
          <div className={css.groupHead}>
            <span className={css.groupTitle}>Agent 요약</span>
          </div>
          <p className={css.notes}>{report.notes}</p>
        </section>
      )}
    </div>
  );
}

export function ReportsTab() {
  const rows = useReports((s) => s.rows);
  const loaded = useReports((s) => s.loaded);
  const selected = useReports((s) => s.selected);
  const detail = useReports((s) => s.detail);
  const pending = useReports((s) => s.pending);
  const error = useReports((s) => s.error);
  const lastCli = useReports((s) => s.lastCli);
  const connected = useWorkspace((s) => s.daemon.status === "connected");

  useEffect(() => {
    initReports();
    if (connected) void reloadReports();
  }, [connected]);

  return (
    <div className={css.tab} data-part="reports-tab">
      <header className={css.head}>
        <span className={css.headTitle}>보고함</span>
        <span className={css.boundary} data-part="security-boundary">
          {SECURITY_BOUNDARY}
        </span>
        <button type="button" className={css.button} onClick={() => void reloadReports()}>
          새로 읽기
        </button>
      </header>
      {lastCli !== null && lastCli.exit_code !== 0 && (lastCli.error_code !== undefined || lastCli.code !== undefined) && (
        <div className={css.alert} role="alert" data-part="cli-error">
          작업을 시작·마치지 못했어요 ({String(lastCli.error_code ?? lastCli.code)})
        </div>
      )}
      {error !== null && (
        <div className={css.alert} role="alert">
          {error}
        </div>
      )}
      <div className={css.split}>
        <ul className={css.list} aria-label="작업 목록" data-part="report-list">
          {loaded && rows.length === 0 && <li className={css.empty}>아직 작업이 없어요</li>}
          {rows.map((r) => {
            const key = `cancel:${r.job}`;
            return (
              <li key={r.job} className={css.row} data-job={r.job} data-state={r.state} aria-selected={r.job === selected}>
                <button type="button" className={css.rowMain} onClick={() => void selectReport(r.job)}>
                  <span className={css.rowTitle}>
                    {r.playbook}
                    <span className={css.state} data-state={r.state}>
                      {STATE_TEXT[r.state] ?? r.state}
                    </span>
                    {r.undecided > 0 && <span className={css.badge}>결정 {r.undecided}</span>}
                  </span>
                  <span className={css.muted}>
                    {shortTime(r.startedAt)} · {r.groups === null ? "보고 전" : `묶음 ${r.groups}`}
                  </span>
                </button>
                {(canCancel(r) || r.state === "ending") && (
                  <button
                    type="button"
                    className={css.button}
                    data-part="cancel"
                    disabled={!canCancel(r) || pending.has(key)}
                    onClick={() => void cancelJob(r.job)}
                  >
                    {r.state === "ending" || pending.has(key) ? "끝내는 중…" : "취소"}
                  </button>
                )}
                <Message k={key} />
              </li>
            );
          })}
        </ul>
        <div className={css.pane}>
          {detail !== null ? (
            <Detail report={detail} />
          ) : (
            <p className={css.muted}>
              {selected !== null && rows.find((r) => r.job === selected)?.hasReport === false ? "작업이 끝나면 보고가 생겨요." : "보고를 고르세요."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
