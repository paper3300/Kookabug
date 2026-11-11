// 보고함 탭 (M8 계획 3.17 "보고함 UI(최소)", KB문서 12장). 목록(작업·상태·묶음 수) / 상세(묶음별 항목, 되돌리기·
// 묶음 수락/거절, 질문 답하기, 증거 묶음·보고서 파일 열기). 머리에 보안 경계 문구(3.15)
import { useEffect, useState } from "react";
import { Spinner } from "../app/Spinner";
import { client, toRpcError } from "../rpc/client";
import { openFileTab } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { SECURITY_BOUNDARY } from "../wizard/boundary";
import {
  answerAll,
  canCancel,
  cancelJob,
  decidable,
  decideGroup,
  filledCount,
  followupBlock,
  followupPlaybook,
  initReports,
  isSettingGroup,
  KIND_TEXT,
  openQuestions,
  reloadReports,
  revertable,
  revertAdoption,
  selectReport,
  NOT_LOCAL_TEXT,
  setDraft,
  SETTING_LABEL,
  settingAcceptable,
  settingCurrentText,
  settingValueText,
  startFollowup,
  STATE_TEXT,
  useReports,
  type Report,
  type ReportItem,
  type SettingProposal,
  type Unknown,
} from "./reportsStore";
import {
  ACTIVITY_POLL_MS,
  activityHead,
  activityLive,
  activityTime,
  collapseActivity,
  mergeActivity,
  type ActivityEntry,
  type ActivityUsed,
} from "./activity";
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
        {item.setting !== undefined && <Setting setting={item.setting} />}
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

/** 설정 바꾸기 제안 (UX2 C): 키 · 현재 값 → 제안 값 · 이유. 값은 글로만 그린다 */
function Setting({ setting }: { setting: SettingProposal }) {
  const local = setting.local ?? null;
  return (
    <span className={css.setting} data-part="setting-change" data-key={setting.key} data-local={local !== null}>
      <span className={css.settingKey}>{SETTING_LABEL[setting.key] ?? setting.key}</span>
      {local !== null ? (
        <span className={css.settingValues}>
          <span className={css.mono} data-part="setting-current">
            {settingCurrentText(setting.key, local.current, local.current_hidden)}
          </span>
          <span aria-hidden="true">→</span>
          <span className={css.mono} data-part="setting-proposed">
            {settingValueText(setting.key, local.value)}
          </span>
        </span>
      ) : (
        <span className={css.muted} data-part="setting-not-local">
          {NOT_LOCAL_TEXT}
        </span>
      )}
      <span className={css.muted}>이유: {local?.reason ?? setting.reason}</span>
    </span>
  );
}

function Question({ u }: { u: Unknown }) {
  const text = useReports((s) => s.drafts[u.id] ?? "");
  const error = useReports((s) => s.answerErrors[u.id]);
  const sending = useReports((s) => s.sending);
  return (
    <li className={css.question} data-unknown={u.id}>
      <span className={css.kind} data-kind="question">
        사람만 답할 수 있음
      </span>
      <span className={css.itemBody}>
        <span>{u.question}</span>
        <textarea
          className={css.input}
          aria-label={`답: ${u.question}`}
          rows={1}
          value={text}
          disabled={sending}
          onChange={(e) => setDraft(u.id, e.target.value)}
        />
        {error !== undefined && (
          <span className={css.error} role="alert" data-part="answer-error">
            {error}
          </span>
        )}
      </span>
    </li>
  );
}

function Questions({ job, questions }: { job: string; questions: Unknown[] }) {
  const sending = useReports((s) => s.sending);
  const filled = useReports((s) => filledCount(questions, s.drafts));
  return (
    <section className={css.group} data-part="questions">
      <div className={css.groupHead}>
        <span className={css.groupTitle}>질문 · 답하지 않아도 작업은 계속돼요</span>
      </div>
      <ul className={css.items}>
        {questions.map((u) => (
          <Question key={u.id} u={u} />
        ))}
      </ul>
      <div className={`${css.answerRow} ${css.sendRow}`}>
        <button type="button" className={css.button} data-part="send-answers" disabled={sending || filled === 0} onClick={() => void answerAll(job, questions)}>
          답 보내기{filled > 0 ? ` (${filled})` : ""}
        </button>
        <Spinner active={sending} size="sm" label="보내는 중…" />
        <span className={css.muted}>글을 넣은 질문만 보내요. 빈 칸은 건너뛰어요</span>
      </div>
    </section>
  );
}

/** "이어서 진행" (UX2 D): Init·이어 하기 보고에서 새 followup 작업. 무인 작업 중이면 끄고 이유, 남은 질문 수 */
function Followup({ report, remaining }: { report: Report; remaining: number }) {
  const rows = useReports((s) => s.rows);
  const key = `followup:${report.job}`;
  const pending = useReports((s) => s.pending.has(key));
  const blocked = followupBlock(rows);
  return (
    <div className={css.followup} data-part="followup-row">
      <button type="button" className={css.button} data-part="followup" disabled={blocked !== null || pending} onClick={() => void startFollowup(report.job)}>
        이어서 진행
      </button>
      <Spinner active={pending} size="sm" label="시작하는 중…" />
      <span className={css.muted} data-part="followup-remaining">
        {remaining > 0 ? `답하지 않은 질문 ${remaining}개 (그대로 진행해도 돼요)` : "남은 질문 없음"}
      </span>
      {blocked !== null && (
        <span className={css.muted} data-part="followup-blocked">
          {blocked}
        </span>
      )}
      <Message k={key} />
    </div>
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
      {followupPlaybook(report) && <Followup report={report} remaining={questions.length} />}
      {report.groups.length === 0 && <p className={css.muted}>항목이 없어요.</p>}
      {report.groups.map((g) => {
        const key = `decide:${report.job}:${g.key}`;
        const setting = isSettingGroup(g);
        return (
          <section key={g.key} className={css.group} data-group={g.key} data-decided={g.decision !== null}>
            <div className={css.groupHead}>
              <span className={css.groupTitle}>{g.title}</span>
              {g.decision !== null && (
                <span className={css.muted}>{g.decision.decision === "accept" ? "수락함" : "거절함"}</span>
              )}
              {decidable(g) && (
                <span className={css.groupActions}>
                  {/* 다른 PC에서 만든 설정 제안은 값을 몰라 수락할 수 없다 — 거절만 */}
                  {(!setting || settingAcceptable(g.items.find((i) => i.kind === "setting_change")?.setting)) && (
                    <button
                      type="button"
                      className={css.button}
                      data-part="accept"
                      disabled={pending.has(key)}
                      onClick={() => void decideGroup(report.job, g.key, "accept", setting)}
                    >
                      {setting ? "수락" : "묶음 수락"}
                    </button>
                  )}
                  <button
                    type="button"
                    className={css.button}
                    data-part="reject"
                    disabled={pending.has(key)}
                    onClick={() => void decideGroup(report.job, g.key, "reject", setting)}
                  >
                    거절
                  </button>
                  <Spinner active={pending.has(key)} size="sm" label="반영 중…" />
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
      {questions.length > 0 && <Questions job={report.job} questions={questions} />}
      {/* 다 보내면 질문 묶음이 사라지므로 결과 글은 묶음 밖에 */}
      <Message k={`answers:${report.job}`} />
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

/**
 * 작업 활동 (UX1 U3): Kookabug가 아는 단계(Agent가 부른 kb_* 도구)·머리(쓴 시간·실행 수·도구 호출 수)·접힌 Agent 출력 꼬리.
 * 진행 중일 때만 1.5초마다 `jobs.activity`를 이어 읽는다. Agent 출력은 글로만 그린다(HTML 아님)
 */
export function Activity({ job, state }: { job: string; state: string }) {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [tail, setTail] = useState<string[]>([]);
  const [used, setUsed] = useState<ActivityUsed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const live = activityLive(state);

  useEffect(() => {
    let alive = true;
    let after = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setEntries([]);
    setTail([]);
    setUsed(null);
    setLoaded(false);
    setError(null);
    const tick = async () => {
      try {
        const r = await client().call("jobs.activity", { job, after });
        if (!alive) return;
        const got = r.entries as ActivityEntry[];
        if (got.length > 0) after = got[got.length - 1].seq;
        setEntries((prev) => mergeActivity(prev, got));
        setTail(r.log_tail);
        setUsed((r.used as ActivityUsed | null) ?? null);
        setError(null);
      } catch (err) {
        if (alive) setError(toRpcError(err).message);
      }
      if (!alive) return;
      setLoaded(true);
      if (live) timer = setTimeout(() => void tick(), ACTIVITY_POLL_MS);
    };
    void tick();
    return () => {
      alive = false;
      if (timer !== null) clearTimeout(timer);
    };
  }, [job, live]);

  // 끝난 작업은 남은 활동이 있을 때만 (옛 작업·연결 시험은 활동 파일이 없다)
  if (!live && (!loaded || error !== null || (entries.length === 0 && tail.length === 0))) return null;
  return (
    <section className={css.group} data-part="job-activity" data-live={live}>
      <div className={css.groupHead}>
        <span className={css.groupTitle}>{live ? "지금 하는 일" : "한 일"}</span>
        {live && <Spinner size="sm" label="진행 중" delay={0} />}
        <span className={css.muted} data-part="activity-head">
          {activityHead(used)}
        </span>
      </div>
      {error !== null && <p className={css.muted}>활동을 읽지 못했어요: {error}</p>}
      {loaded && entries.length === 0 && error === null && (
        <p className={css.muted}>{live ? "Agent가 아직 Kookabug 도구를 부르지 않았어요." : "남은 활동이 없어요."}</p>
      )}
      {entries.length > 0 && (
        <ol className={css.activity} data-part="activity-list">
          {collapseActivity(entries)
            .reverse()
            .map((e) => (
              <li key={e.seq} data-tool={e.tool} data-result={e.result} className={css.activityRow}>
                <span className={css.mono}>{activityTime(e.at)}</span>
                <span data-fail={e.result !== "ok"}>
                  {e.text}
                  {e.count > 1 && <span className={css.muted}> ×{e.count}</span>}
                </span>
              </li>
            ))}
        </ol>
      )}
      <details className={css.tail} data-part="agent-log-tail">
        <summary>Agent 출력 (마지막 {tail.length}줄 · 비밀값은 가림)</summary>
        <pre className={css.tailText}>{tail.join("\n")}</pre>
      </details>
    </section>
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
  const selectedRow = rows.find((r) => r.job === selected);

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
          {selectedRow !== undefined && activityLive(selectedRow.state) && <Activity job={selectedRow.job} state={selectedRow.state} />}
          {detail !== null ? (
            <Detail report={detail} />
          ) : (
            <p className={css.muted}>
              {selectedRow?.hasReport === false ? "작업이 끝나면 보고가 생겨요." : selected === null ? "보고를 고르세요." : ""}
            </p>
          )}
          {selectedRow !== undefined && !activityLive(selectedRow.state) && selectedRow.playbook !== "probe" && (
            <Activity job={selectedRow.job} state={selectedRow.state} />
          )}
        </div>
      </div>
    </div>
  );
}
