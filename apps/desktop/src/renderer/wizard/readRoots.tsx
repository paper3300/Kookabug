// 6단계 "Agent가 읽어도 되는 폴더" 묶음 (UX3). 원본(기획 근거)과 따로, 실행 bat·서버 목록처럼 실행·환경 확인용 파일을 Agent가
// kb_source_list·kb_source_read로 읽는 폴더다. 이 PC 값이라 `.kookabug/local.json` settings `agent.read_roots`에 사람 전용
// `local.settings.set`으로 저장한다(허용하지 않는 폴더는 daemon이 policy_path로 거부 — 이유를 그대로 보인다). 게임 실행 파일
// 폴더는 자동 포함(계산 값)이라 고칠 수 없는 줄로 보인다
import { toRpcError } from "../rpc/client";
import { StorageBadge } from "./StorageBadge";
import css from "./wizard.module.css";

export const READ_ROOTS_KEY = "agent.read_roots";
export const READ_ROOTS_TITLE = "Agent가 읽어도 되는 폴더";
export const READ_ROOTS_NOTE = "여기 넣은 폴더 아래 파일은 Agent(외부 AI 서비스)에게 보일 수 있어요. 비밀값은 가리지만 민감한 폴더는 넣지 마세요.";

/** wizard.get read_roots.auto 한 줄 */
export interface AutoRoot {
  id: string;
  path: string;
  title: string;
  state: "ok" | "missing" | "refused";
  reason: string | null;
  message: string | null;
}

/** 화면 줄 초기값: 저장된 목록, 없으면 빈 줄 하나 */
export function initialRootRows(paths: readonly string[]): string[] {
  return paths.length > 0 ? [...paths] : [""];
}

/** 저장할 목록 (빈 줄 빼고 앞뒤 공백 정리) */
export function rootsToSave(rows: readonly string[]): string[] {
  return rows.map((r) => r.trim()).filter((r) => r !== "");
}

/** 저장된 목록과 다른가 */
export function rootsChanged(saved: readonly string[], rows: readonly string[]): boolean {
  const next = rootsToSave(rows);
  return next.length !== saved.length || next.some((p, i) => p !== saved[i]);
}

/** 저장 거부 글: 허용하지 않는 폴더(policy_path)면 몇째 줄인지 + daemon 이유 글 그대로, 그 밖은 메시지 */
export function rootErrorText(err: unknown, rows: readonly string[]): string {
  const e = toRpcError(err);
  if (e.kind !== "policy_path") return e.message;
  const data = (e.data ?? {}) as { index?: unknown };
  // index는 보낸 목록(빈 줄 뺀 것) 기준이다 → 화면 줄 번호로 바꾼다
  const filled = rows.map((r, i) => ({ r: r.trim(), i })).filter((x) => x.r !== "");
  const at = typeof data.index === "number" ? filled[data.index]?.i : undefined;
  return at === undefined ? `저장하지 않았어요: ${e.message}` : `${at + 1}번째 폴더를 저장하지 않았어요: ${e.message}`;
}

/** 자동 포함 줄의 상태 글 */
export function autoRootNote(root: AutoRoot): string | null {
  if (root.state === "refused") return `자동 포함에서 뺐어요 — ${root.message ?? root.reason ?? ""}`;
  if (root.state === "missing") return "폴더가 없어요";
  return null;
}

export interface ReadRootsGroupProps {
  rows: readonly string[];
  auto: readonly AutoRoot[];
  error: string | null;
  disabled: boolean;
  onChange: (index: number, value: string) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
  onPick: (index: number) => void;
}

export function ReadRootsGroup({ rows, auto, error, disabled, onChange, onAdd, onRemove, onPick }: ReadRootsGroupProps) {
  return (
    // 원본 칸 목록이 스크롤을 맡고 이 묶음은 줄어들지 않는다 (저장 거부 글이 가려지지 않게)
    <div className={css.list} style={{ flexShrink: 0 }} data-part="read-roots">
      <div className={css.row} style={{ alignItems: "flex-start" }}>
        <span className={css.avatar} aria-hidden="true" style={{ borderRadius: 6 }}>
          ⌂
        </span>
        <span className={css.rowText}>
          <span className={css.rowTitle}>
            {READ_ROOTS_TITLE}
            <span className={css.spacer} />
            <button type="button" className={css.linkButton} data-part="read-root-add" title="폴더 줄을 더해요" disabled={disabled} onClick={onAdd}>
              + 추가
            </button>
          </span>
          <small className={css.caption} data-part="read-roots-note">
            {READ_ROOTS_NOTE}
          </small>
          {auto.map((a) => {
            const note = autoRootNote(a);
            return (
              <span key={a.id} className={css.sourceLine} data-part="read-root-auto" data-root={a.id} data-state={a.state}>
                <input className={`${css.input} ${css.mono}`} style={{ height: 26, fontSize: 12 }} aria-label={a.title} value={a.path} readOnly />
                <span className={css.tag} data-tone="muted">
                  {a.title}
                </span>
                {note !== null && (
                  <span className={css.tag} data-tone="warn" data-part="read-root-auto-warn">
                    {note}
                  </span>
                )}
              </span>
            );
          })}
          {rows.map((value, i) => (
            <span key={i} className={css.sourceLine} data-part="read-root" data-index={i}>
              <input
                className={`${css.input} ${css.mono}`}
                style={{ height: 26, fontSize: 12 }}
                aria-label={`읽어도 되는 폴더 ${i + 1}`}
                placeholder="폴더 절대 경로"
                value={value}
                disabled={disabled}
                onChange={(e) => onChange(i, e.target.value)}
              />
              {value.trim() !== "" && <StorageBadge storage="pc" />}
              <button type="button" className={css.small} data-part="read-root-pick" disabled={disabled} onClick={() => onPick(i)}>
                찾아보기
              </button>
              <button
                type="button"
                className={css.iconButton}
                data-part="read-root-remove"
                title={rows.length > 1 ? "이 줄 지우기" : "비우기"}
                disabled={disabled || (rows.length <= 1 && value === "")}
                onClick={() => onRemove(i)}
              >
                −
              </button>
            </span>
          ))}
          {error !== null && (
            <span role="alert" className={css.error} style={{ margin: 0 }} data-part="read-roots-error">
              {error}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}
