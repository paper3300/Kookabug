// 에이전트 패널 (시안 Main 오른쪽, M5 계획 3.10): 세션 제목·새 대화, 대화(내 말풍선·답 본문·도구 호출 줄·
// 승인 카드 두 종류), 입력창(@칩·보내기/중지), 바닥 줄 "<에이전트> · ACP · 권한: <프리셋> · MCP 툴셋 N".
// 연결 안 된 상태는 빈 화면(감지 목록·직접 입력·권한 프리셋, 시안 Setup5 압축판 U7)
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { client, toRpcError } from "../rpc/client";
import { useRun } from "../run/runStore";
import { adoptPreview, useDocuments } from "../store/documents";
import { openPreviewTab, openSettingsTab, PREVIEW_PREFIX, useTabs } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { ChevronDownIcon, ChevronRightIcon, LockIcon, StopIcon } from "../theme/icons";
import css from "./agent.module.css";
import {
  addChip,
  answerAcpPermission,
  cancelPrompt,
  connectCandidate,
  connectManual,
  effectivePreset,
  endSession,
  fromEndedSession,
  newConversation,
  presetLabel,
  refreshAgents,
  refreshCandidates,
  refreshPermissions,
  removeChip,
  respondApproval,
  restartSession,
  sendPrompt,
  setDraft,
  setLeaseSource,
  setUserPreset,
  startSession,
  toggleTools,
  toolsRunning,
  toolsSummary,
  useAgent,
  dismissLease,
  type ApprovalCard as ApprovalState,
  type ChatItem,
  type Chip,
} from "./agentStore";
import { runChip, nodeChip } from "./chips";

const PRESETS: [string, string][] = [
  ["graph_author", "그래프 작성 — 읽기 + 편집은 확인 후"],
  ["read_only", "읽기 전용"],
  ["runner", "실행 — 작성 + 실행, 입력은 확인 후"],
  ["full", "전체 (주의)"],
];

const RESULT_TEXT: Record<string, string> = {
  allow_once: "한 번 허용했어요",
  allow_always: "항상 허용했어요 (프로젝트 규칙에 저장)",
  deny: "거부했어요",
  timeout: "120초 안에 답이 없어 거부됐어요",
  cancelled: "요청이 취소됐어요 (에이전트 연결이 끝남)",
};

function ShieldIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M8 1.5l5.5 2v4c0 3.5-2.4 6-5.5 7-3.1-1-5.5-3.5-5.5-7v-4z" />
    </svg>
  );
}

function NewChatIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
      <path d="M7 2H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V9" />
      <path d="M11.5 1.5l3 3L8 11H5V8z" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" />
    </svg>
  );
}

/** 확인 요청 카드 머리 (도구 종류) */
function approvalTitle(tool: string): string {
  if (tool.startsWith("kb_graph_") || tool === "kb_target_create") return "그래프 편집 승인 필요";
  if (tool.startsWith("kb_input_") || tool === "kb_app_launch") return "게임 조작 승인 필요";
  if (tool.startsWith("kb_run_")) return "실행 승인 필요";
  if (tool.startsWith("kb_screen_")) return "화면 지도 편집 승인 필요";
  return "에이전트 작업 승인 필요";
}

async function previewApproval(id: string, title: string): Promise<string | null> {
  try {
    const { value } = await client().call("approval.preview", { id });
    const path = `${PREVIEW_PREFIX}${id}`;
    adoptPreview(path, value);
    openPreviewTab(path, `${title} · 승인 미리보기`);
    return null;
  } catch (err) {
    return toRpcError(err).message;
  }
}

/** Kookabug 확인 요청 카드 (approval.requested): 한 번 허용 / 항상 허용(control 없음) / 캔버스에서 보기 / 거부 */
export function ApprovalCardView({ card, external }: { card: ApprovalState; external?: boolean }) {
  const r = card.request;
  const [previewError, setPreviewError] = useState<string | null>(null);
  const session = useAgent((s) => s.session);
  const open = card.state === "open";
  // 세션이 끝난 요청: daemon이 cancelled로 닫기 전이라도 단추를 막는다
  const stale = open && fromEndedSession(r, session);
  const busy = card.busy || stale;
  const name = r.arg.split("/").pop() ?? r.arg;
  return (
    <div
      className={css.card}
      data-part="approval-card"
      data-id={r.id}
      data-state={card.state}
      data-stale={stale}
      data-external={external === true}
    >
      <div className={css.cardHead}>
        <ShieldIcon />
        <span>{approvalTitle(r.tool)}</span>
        <span className={css.cardTool} title={r.tool}>
          {r.tool}
        </span>
      </div>
      <div className={css.cardBody} data-part="approval-summary">
        {external === true && <div>{r.agent.name || r.agent.id} (외부 에이전트)</div>}
        {r.summary.length === 0 && r.arg !== "" && <div>{r.arg}</div>}
        {r.summary.map((line, i) => (
          <div key={i} className={line.startsWith("+") ? css.add : line.startsWith("-") ? css.remove : undefined}>
            {line}
          </div>
        ))}
      </div>
      {open && r.always_rule !== null && (
        <div className={css.cardNote} data-part="always-rule">
          항상 허용하면 프로젝트 규칙 <code>{r.always_rule}</code>을(를) 저장해요
        </div>
      )}
      {open ? (
        <div className={css.cardButtons}>
          <button type="button" className={css.primary} disabled={busy} onClick={() => void respondApproval(r.id, "allow_once")}>
            한 번 허용
          </button>
          {r.always_rule !== null && (
            <button type="button" className={css.secondary} disabled={busy} onClick={() => void respondApproval(r.id, "allow_always")}>
              항상 허용
            </button>
          )}
          {r.previewable && (
            <button
              type="button"
              className={css.secondary}
              disabled={stale}
              onClick={() => void previewApproval(r.id, name).then(setPreviewError)}
            >
              캔버스에서 보기
            </button>
          )}
          <button type="button" className={css.danger} disabled={busy} onClick={() => void respondApproval(r.id, "deny")}>
            거부
          </button>
        </div>
      ) : (
        <div className={css.cardResult} data-part="approval-result">
          {RESULT_TEXT[card.state] ?? card.state}
        </div>
      )}
      {stale && <div className={css.cardResult}>에이전트 세션이 끝나 이 요청은 취소돼요</div>}
      {(card.error ?? previewError) !== null && <div className={css.cardError}>{card.error ?? previewError}</div>}
    </div>
  );
}

/** 에이전트 자기 도구의 권한 요청 카드: 에이전트가 준 선택지 그대로 (자동 허용 없음) */
function AcpPermissionCard({ item }: { item: Extract<ChatItem, { kind: "acp_permission" }> }) {
  const chosen = item.options.find((o) => o.id === item.chosen);
  return (
    <div className={css.card} data-part="acp-permission" data-state={item.state}>
      <div className={css.cardHead}>
        <ShieldIcon />
        <span>에이전트 도구 권한 요청</span>
      </div>
      <div className={css.cardBody}>{item.title}</div>
      {item.state === "open" ? (
        <div className={css.cardButtons}>
          {item.options.map((o) => (
            <button
              key={o.id}
              type="button"
              data-kind={o.kind}
              className={o.kind.startsWith("reject") ? css.danger : o.kind === "allow_once" ? css.primary : css.secondary}
              onClick={() => void answerAcpPermission(item.id, o.id)}
            >
              {o.name}
            </button>
          ))}
          <button type="button" className={css.danger} onClick={() => void answerAcpPermission(item.id, null)}>
            닫기
          </button>
        </div>
      ) : (
        <div className={css.cardResult} data-part="acp-permission-result">
          {item.state === "selected" ? `골랐어요: ${chosen?.name ?? item.chosen}` : "취소됐어요"}
        </div>
      )}
    </div>
  );
}

function ToolsLine({ item }: { item: Extract<ChatItem, { kind: "tools" }> }) {
  const open = item.open ?? toolsRunning(item);
  return (
    <div className={css.tools} data-part="tool-line" data-open={open}>
      <button type="button" className={css.toolsButton} aria-expanded={open} onClick={() => toggleTools(item.key)}>
        {toolsSummary(item)}
        {item.hidden > 0 ? ` · 생각 ${item.hidden}` : ""}
        {open ? <ChevronDownIcon width={12} height={12} /> : <ChevronRightIcon width={12} height={12} />}
      </button>
      {open &&
        item.tools.map((t) => (
          <div key={t.id} className={css.toolRow} data-part="tool-row" data-status={t.status}>
            {t.title}
            <span>{t.status === "completed" ? "✓" : t.status === "failed" ? "✕" : "…"}</span>
          </div>
        ))}
    </div>
  );
}

function Chat() {
  const items = useAgent((s) => s.items);
  const approvals = useAgent((s) => s.approvals);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    void end.current?.scrollIntoView({ block: "end" });
  }, [items]);
  return (
    <div className={css.chat} data-part="agent-chat">
      {items.map((item): ReactNode => {
        switch (item.kind) {
          case "user":
            return (
              <div key={item.key} className={css.user} data-part="chat-user">
                {item.chips.length > 0 && (
                  <div className={css.userChips}>
                    {item.chips.map((c) => (
                      <span key={c} className={`${css.chip} ${css.chipStatic}`}>
                        {c}
                      </span>
                    ))}
                  </div>
                )}
                {item.text}
              </div>
            );
          case "agent":
            return (
              <div key={item.key} className={css.answer} data-part="chat-agent">
                {item.text}
              </div>
            );
          case "tools":
            return <ToolsLine key={item.key} item={item} />;
          case "acp_permission":
            return <AcpPermissionCard key={item.key} item={item} />;
          case "approval": {
            const card = approvals.get(item.id);
            return card === undefined ? null : <ApprovalCardView key={item.key} card={card} />;
          }
          case "error":
            return (
              <div key={item.key} className={css.error} data-part="chat-error" role="alert">
                {item.text}
                {item.restart && (
                  <button type="button" className={css.secondary} onClick={() => void restartSession()}>
                    다시 시작
                  </button>
                )}
              </div>
            );
        }
      })}
      <div ref={end} />
    </div>
  );
}

function External() {
  const ids = useAgent((s) => s.external);
  const approvals = useAgent((s) => s.approvals);
  if (ids.length === 0) return null;
  return (
    <div className={css.external} data-part="external-approvals">
      <span className={css.externalLabel}>외부 에이전트</span>
      {ids.map((id) => {
        const card = approvals.get(id);
        return card === undefined ? null : <ApprovalCardView key={id} card={card} external />;
      })}
    </div>
  );
}

function LeaseBanner() {
  const blocked = useAgent((s) => s.leaseBlocked);
  if (blocked === null) return null;
  return (
    <div className={css.lease} role="status" data-part="lease-blocked">
      <div className={css.leaseTitle}>
        <LockIcon width={14} height={14} />
        에이전트의 게임 조작을 막았어요
      </div>
      <div>
        이 PC의 입력은 지금 <b>{blocked.owner ?? "다른 작업"}</b>이(가) 쓰고 있어요. 입력은 한 번에 하나만 보낼 수 있어요. 그
        작업이 끝나면 에이전트가 게임을 조작할 수 있어요.
      </div>
      <div>
        <button type="button" className={css.footerLink} onClick={dismissLease}>
          닫기
        </button>
      </div>
    </div>
  );
}

/** 지금 에디터 맥락에서 @칩 하나 (RUN 탭 → @run, 그래프의 고른 노드 → @node) */
function useContextChip(): (() => Chip) | null {
  const tab = useTabs((s) => s.tabs.find((t) => t.path === s.active));
  const graph = tab?.kind === "graph" && tab.preview !== true && tab.snapshot !== true ? tab.path : null;
  const node = useDocuments((s) => (graph === null ? null : (s.docs.get(graph)?.view.selected ?? null)));
  if (tab?.kind === "run" && tab.runId !== undefined) {
    const runId = tab.runId;
    return () => runChip(runId);
  }
  if (graph !== null && node !== null) return () => nodeChip(graph, node);
  return null;
}

function Composer() {
  const draft = useAgent((s) => s.draft);
  const chips = useAgent((s) => s.chips);
  const session = useAgent((s) => s.session);
  const contextChip = useContextChip();
  const busy = session?.status === "busy";
  const ready = session !== null && session.status !== "ended" && session.status !== "error";
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void sendPrompt();
    }
  };
  return (
    <div className={css.inputBox}>
      <textarea
        aria-label="에이전트에게 메시지"
        placeholder="무엇이든 요청하세요. @로 실행·노드 첨부"
        className={css.textarea}
        value={draft}
        disabled={!ready}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
      />
      <div className={css.inputRow}>
        <button
          type="button"
          aria-label="첨부"
          title={contextChip === null ? "실행 탭이나 노드를 고르면 첨부할 수 있어요" : `${contextChip().label} 첨부`}
          className={css.iconButton}
          disabled={contextChip === null}
          onClick={() => {
            if (contextChip !== null) addChip(contextChip());
          }}
        >
          +
        </button>
        <div className={css.chips}>
          {chips.map((c) => (
            <span key={c.label} className={css.chip} data-part="chip">
              {c.label}
              <button type="button" aria-label={`${c.label} 빼기`} className={css.chipRemove} onClick={() => removeChip(c.label)}>
                ×
              </button>
            </span>
          ))}
        </div>
        {busy ? (
          <button type="button" aria-label="중지" className={css.send} onClick={() => void cancelPrompt()}>
            <StopIcon width={10} height={10} />
          </button>
        ) : (
          <button
            type="button"
            aria-label="보내기"
            className={css.send}
            disabled={!ready || (draft.trim() === "" && chips.length === 0)}
            onClick={() => void sendPrompt()}
          >
            <SendIcon />
          </button>
        )}
      </div>
    </div>
  );
}

function Footer() {
  const session = useAgent((s) => s.session);
  const permissions = useAgent((s) => s.permissions);
  const connections = useAgent((s) => s.connections);
  const mine = session === null ? undefined : connections.find((c) => c.id === `panel:${session.id}`);
  return (
    <div className={css.footer} data-part="agent-footer">
      <span className={css.online}>
        <span className={css.dot} data-status={session?.status ?? "ended"} />
        {session?.name ?? "연결 안 됨"} · ACP
      </span>
      <button type="button" className={css.footerLink} data-part="footer-preset" onClick={openSettingsTab}>
        권한: {presetLabel(effectivePreset(permissions))}
      </button>
      <span className={css.footerRight} data-part="footer-toolsets">
        MCP 툴셋 {mine?.toolsets.length ?? 0}
      </span>
    </div>
  );
}

/** 연결 안 된 화면: 설정한 에이전트·감지한 에이전트·직접 입력·권한 프리셋 */
function Connect() {
  const agents = useAgent((s) => s.agents);
  const candidates = useAgent((s) => s.candidates);
  const starting = useAgent((s) => s.starting);
  const startError = useAgent((s) => s.startError);
  const problem = useAgent((s) => s.agentsProblem);
  const permissions = useAgent((s) => s.permissions);
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const [name, setName] = useState("");
  const [line, setLine] = useState("");
  useEffect(() => {
    if (!connected) return;
    void refreshAgents();
    void refreshCandidates();
    void refreshPermissions();
  }, [connected]);
  const configured = new Set(agents.map((a) => a.id));
  const detected = (candidates ?? []).filter((c) => !configured.has(c.id));
  const busy = starting !== null;
  const userPreset = (permissions?.layers?.find((l) => l.layer === "user")?.permissions as { preset?: string } | null)?.preset;
  return (
    <div className={css.empty} data-part="agent-connect">
      <h2 className={css.emptyTitle}>에이전트 연결</h2>
      <p className={css.emptyText}>
        에이전트 CLI를 ACP로 붙이면 여기서 그래프를 만들고 실행 실패를 분석해요. 에이전트는 Kookabug MCP 도구를 권한에 따라
        쓰고, 확인이 필요한 일은 이 패널에서 물어봐요.
      </p>
      {problem !== null && <div className={css.startError}>사용자 설정을 읽지 못했어요: {problem}</div>}
      {agents.length > 0 && (
        <>
          <span className={css.sectionLabel}>설정한 에이전트</span>
          <div className={css.agentList}>
            {agents.map((a) => (
              <div key={a.id} className={css.agentRow} data-part="agent-row" data-id={a.id}>
                <span className={css.agentName}>
                  <b>{a.name}</b>
                  <small title={[a.command, ...(a.args ?? [])].join(" ")}>{[a.command, ...(a.args ?? [])].join(" ")}</small>
                </span>
                <button type="button" className={css.primary} disabled={busy} onClick={() => void startSession(a.id)}>
                  {starting === a.id ? "연결 중…" : "연결"}
                </button>
              </div>
            ))}
          </div>
        </>
      )}
      <span className={css.sectionLabel}>감지한 에이전트</span>
      <div className={css.agentList}>
        {candidates === null && <div className={css.agentRow}>찾는 중…</div>}
        {candidates !== null && detected.length === 0 && <div className={css.agentRow}>더 찾은 에이전트가 없어요</div>}
        {detected.map((c) => (
          <div key={c.id} className={css.agentRow} data-part="candidate-row" data-id={c.id} data-installed={c.installed}>
            <span className={css.agentName}>
              <b>{c.name}</b>
              <small>{[c.command, ...c.args].join(" ")}</small>
            </span>
            {c.installed ? (
              <button type="button" className={css.secondary} disabled={busy} onClick={() => void connectCandidate(c)}>
                ACP로 연결
              </button>
            ) : (
              <span className={css.notInstalled}>설치 안 됨</span>
            )}
          </div>
        ))}
      </div>
      <span className={css.sectionLabel}>직접 입력</span>
      <label className={css.field}>
        이름
        <input className={css.input} aria-label="에이전트 이름" value={name} placeholder="내 에이전트" onChange={(e) => setName(e.target.value)} />
      </label>
      <label className={css.field}>
        명령줄 (ACP로 말하는 에이전트)
        <input
          className={`${css.input} ${css.mono}`}
          aria-label="에이전트 명령줄"
          value={line}
          placeholder="my-agent --acp"
          onChange={(e) => setLine(e.target.value)}
        />
      </label>
      <div>
        <button type="button" className={css.secondary} disabled={busy || line.trim() === ""} onClick={() => void connectManual(name, line)}>
          추가하고 연결
        </button>
      </div>
      <label className={css.field}>
        에이전트 권한 (사용자 기본값)
        <select
          className={css.select}
          aria-label="권한 프리셋"
          value={userPreset ?? effectivePreset(permissions)}
          onChange={(e) => void setUserPreset(e.target.value)}
        >
          {PRESETS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {startError !== null && (
        <div className={css.startError} role="alert" data-part="agent-start-error">
          {startError}
        </div>
      )}
    </div>
  );
}

function sessionTitle(items: readonly ChatItem[], fallback: string): string {
  const first = items.find((i) => i.kind === "user");
  if (first?.kind !== "user") return fallback;
  const text = first.text || first.chips.join(" ");
  return text.length > 28 ? `${text.slice(0, 28)}…` : text;
}

// 띠에 쓸 지금 임대권 소유자 (실행 화면 저장소가 받은 lease.changed)
setLeaseSource(() => {
  const owner = useRun.getState().lease;
  if (owner === null) return null;
  if (owner.kind === "recorder") return "녹화";
  return typeof owner.run_id === "string" ? `실행 #${owner.run_id.slice(0, 4)}` : "다른 작업";
});

/** 오른쪽 패널 "에이전트" 탭 */
export function AgentPanel() {
  const session = useAgent((s) => s.session);
  const items = useAgent((s) => s.items);
  return (
    <div className={css.panel} data-part="agent-panel" data-session={session?.id ?? ""} data-status={session?.status ?? "none"}>
      <div className={css.head}>
        <span className={css.headTitle}>{session === null ? "에이전트" : sessionTitle(items, session.name)}</span>
        {session !== null && (
          <>
            <button type="button" aria-label="새 대화" title="새 대화" className={css.iconButton} onClick={() => void newConversation()}>
              <NewChatIcon />
            </button>
            <button
              type="button"
              aria-label="에이전트 연결 끊기"
              title="에이전트 연결 끊기"
              className={css.iconButton}
              onClick={() => void endSession()}
            >
              ×
            </button>
          </>
        )}
      </div>
      <External />
      <LeaseBanner />
      {session === null ? (
        <Connect />
      ) : (
        <>
          <Chat />
          <div className={css.composer}>
            <Composer />
            <Footer />
          </div>
        </>
      )}
    </div>
  );
}
