// 7단계 자동화 정책 (필수, 시안 Wizard7Automation): 자동 수리(기본 켬, 범위 tests/)·금지 동작(제품 기본값 없음)·
// 작업 예산(60분·30회)·치트 사용. "다음" = 기본값 확인(바꾸지 않아도 확정). 팀 `kookabug.json`에 쓴다
// (`project.automation.set` → `cheats.categories.set`, 둘 다 사람 전용·sha 대조)
import { useCallback, useEffect, useState } from "react";
import { client, toRpcError } from "../../rpc/client";
import { CHEAT_FOOTNOTE, SECURITY_BOUNDARY } from "../boundary";
import { ConflictNotice, isConflict } from "../Conflict";
import { StepShell } from "../Wizard";
import { setStepWarnings, setSummary } from "../wizardStore";
import css from "../wizard.module.css";

type Forbidden = { kind: "text"; value: string } | { kind: "target"; path: string } | { kind: "screen"; id: string };

interface Policy {
  repair: boolean;
  scope: string[];
  forbidden: Forbidden[];
  minutes: number;
  runs: number;
  cheats: boolean;
  categories: unknown[];
  /** 그대로 남길 자동 수리 키 (profiles·max_adoptions) */
  repairRest: Record<string, unknown>;
}

/** 정책 → kookabug.json automation 블록 */
export function automationBlock(p: Policy): Record<string, unknown> {
  return {
    format: "kookabug.automation/0",
    auto_repair: { ...p.repairRest, enabled: p.repair, scope: p.scope },
    forbidden: p.forbidden,
    budget: { minutes: p.minutes, runs: p.runs },
  };
}

function forbiddenText(f: Forbidden): string {
  return f.kind === "text" ? f.value : f.kind === "target" ? f.path : `화면 ${f.id}`;
}

function Switch({ on, label, onChange }: { on: boolean; label: string; onChange: (on: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} className={css.switch} onClick={() => onChange(!on)} />;
}

export function Step7Automation() {
  const [p, setP] = useState<Policy | null>(null);
  /** 화면을 채울 때 읽은 kookabug.json sha (저장 기준 — 저장 직전에 새로 읽지 않는다, B7 검수 H5) */
  const [base, setBase] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setP(null);
    setBase(null);
    setConflict(false);
    setError(null);
    try {
      // sha를 먼저 읽는다: 그 뒤에 바뀐 값이 화면에 들어오면 저장이 충돌로 끝난다(안전한 쪽). 거꾸로면 오래된 값으로 덮어쓴다
      const { config_sha256: sha } = await client().call("wizard.get", {});
      const [info, raw] = await Promise.all([
        client().call("project.qa_info", {}),
        client().call("workspace.read", { path: "kookabug.json" }),
      ]);
      // 치트 블록이 아직 없으면(사람이 정한 적 없음) U2 기본값 "켬"을 보인다 — 실효값(qa_info)은 꺼짐이다
      const decided = "cheats" in (JSON.parse(raw.text) as Record<string, unknown>);
      const a = info.automation as {
        auto_repair?: { enabled?: boolean; scope?: string[] } & Record<string, unknown>;
        forbidden?: Forbidden[];
        budget?: { minutes?: number; runs?: number };
      };
      const c = info.cheats as { enabled?: boolean; categories?: unknown[] };
      const { enabled, scope, ...rest } = a.auto_repair ?? {};
      setP({
        repair: enabled ?? true,
        scope: scope ?? ["tests/"],
        forbidden: a.forbidden ?? [],
        minutes: a.budget?.minutes ?? 60,
        runs: a.budget?.runs ?? 30,
        // U2 기본값: 치트 사용 켬 (분류가 없으면 무인 사용은 어차피 0)
        cheats: decided ? c.enabled === true : true,
        categories: c.categories ?? [],
        repairRest: rest,
      });
      setBase(sha);
    } catch (err) {
      setError(toRpcError(err).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const update = (patch: Partial<Policy>) => setP((cur) => (cur === null ? cur : { ...cur, ...patch }));

  const addForbidden = () => {
    const v = draft.trim();
    if (p === null || v === "" || p.forbidden.some((f) => f.kind === "text" && f.value === v)) return;
    update({ forbidden: [...p.forbidden, { kind: "text", value: v }] });
    setDraft("");
  };

  const save = async (): Promise<boolean> => {
    if (p === null || base === null || conflict) return false;
    setError(null);
    try {
      const { sha256 } = await client().call("project.automation.set", { base_sha256: base, value: automationBlock(p) });
      setBase(sha256); // 이 저장이 만든 sha (치트 저장이 실패해도 다시 누를 때 기준)
      const cheats = await client().call("cheats.categories.set", {
        base_sha256: sha256,
        categories: p.categories as never,
        enabled: p.cheats,
      });
      setBase(cheats.sha256);
      const empty = p.forbidden.length === 0;
      setStepWarnings(7, empty ? ["forbidden_empty"] : []);
      setSummary(
        7,
        `자동 수리 ${p.repair ? "켬" : "끔"} · 금지 동작 ${empty ? "없음" : `${p.forbidden.length}개`} · ${p.minutes}분/${p.runs}회 · 치트 ${p.cheats ? "허용" : "끔"}`,
        empty,
      );
      return true;
    } catch (err) {
      if (isConflict(err)) setConflict(true);
      else setError(toRpcError(err).message);
      return false;
    }
  };

  const valid = p !== null && base !== null && !conflict && p.minutes >= 1 && p.runs >= 1;
  return (
    <StepShell
      title="Agent가 어디까지 혼자 해도 될까요?"
      lead="사람이 하나하나 확인하지 않아도 진행해요. 한 일은 작업마다 보고함에 남아요."
      primary={{ label: "다음", enabled: valid, run: save }}
      right={
        <>
          <div className={css.caption}>이런 보고가 작업마다 보고함에 쌓여요</div>
          <div className={css.card}>
            <div className={css.cardHead}>
              <span>
                <span className={css.tag}>자동 수리</span> 상점 구매 버튼 위치가 바뀜
              </span>
              <small>되돌리기</small>
            </div>
            <div className={css.cardRow}>
              <span className={css.mark}>✓</span>검증 노드는 그대로 · 원래 기대대로 통과
            </div>
            <div className={css.cardRow}>
              <span className={css.mark}>✓</span>버튼이 없는 화면에서는 실패하는지 확인
            </div>
            <div className={css.cardRow}>
              <span className={css.mark}>✓</span>같은 대상을 쓰는 테스트 다시 통과
            </div>
          </div>
          <div className={css.card}>
            <div className={css.cardHead}>
              <span>
                <span className={css.tag} data-tone="warn">
                  고치지 않음
                </span>{" "}
                체력 물약 가격 100 → 120
              </span>
            </div>
            <div className={css.cardRow}>기대 결과가 달라서 자동 수리 대상이 아니에요. 판단할 정보가 없으면 사람에게 물어요.</div>
          </div>
          <div className={css.caption}>{SECURITY_BOUNDARY}</div>
        </>
      }
    >
      {p === null ? (
        <div className={css.list}>
          <div className={css.row}>{error ?? "정책을 읽는 중…"}</div>
        </div>
      ) : (
        <div className={css.policy} data-part="automation-policy">
          <div className={css.policyRow}>
            <div className={css.policyHead}>
              자동 수리
              <Switch on={p.repair} label="자동 수리" onChange={(repair) => update({ repair })} />
            </div>
            <div className={css.policyText}>
              버튼 위치·모양만 바뀌어 실패하면 고치고 바로 반영해요. 기대 결과와 검증 노드는 절대 바꾸지 않아요.
            </div>
            <div className={css.policyText}>
              범위 <span className={css.mono}>{p.scope.join(" ")}</span> 전체
            </div>
          </div>
          <div className={css.policyRow}>
            <div className={css.policyHead}>금지 동작</div>
            <div className={css.policyText}>적은 글자·화면·대상이 보이면 Agent가 누를 수 없어요. 도구가 막아요.</div>
            <div className={css.inputRow}>
              <input
                className={css.input}
                aria-label="금지 문구"
                placeholder="예: 결제, 구매 확정, 캐릭터 삭제, 계정 탈퇴"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addForbidden();
                }}
              />
              <button type="button" className={css.small} onClick={addForbidden}>
                + 추가
              </button>
            </div>
            {p.forbidden.length === 0 ? (
              <div className={`${css.policyText} ${css.warnText}`} data-part="forbidden-empty">
                비어 있어요. 게임마다 달라서 기본값을 두지 않아요.
              </div>
            ) : (
              <div className={css.chipList} data-part="forbidden-list">
                {p.forbidden.map((f, i) => (
                  <button
                    key={`${f.kind}:${forbiddenText(f)}`}
                    type="button"
                    title="지우기"
                    onClick={() => update({ forbidden: p.forbidden.filter((_, j) => j !== i) })}
                  >
                    {forbiddenText(f)} ×
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className={css.policyRow}>
            <div className={css.policyHead}>
              작업 하나의 예산
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 400 }}>
                <input
                  className={css.number}
                  type="number"
                  min={1}
                  aria-label="예산 분"
                  value={p.minutes}
                  onChange={(e) => update({ minutes: Math.floor(Number(e.target.value)) })}
                />
                분
                <input
                  className={css.number}
                  type="number"
                  min={1}
                  aria-label="예산 실행 수"
                  value={p.runs}
                  onChange={(e) => update({ runs: Math.floor(Number(e.target.value)) })}
                />
                회 실행
              </span>
            </div>
            <div className={css.policyText}>넘으면 멈추고 그때까지 한 일을 보고해요. 예약은 지금 CLI(kookabug agent-job schedule)로 등록해요.</div>
          </div>
          <div className={css.policyRow}>
            <div className={css.policyHead}>
              치트 사용
              <Switch on={p.cheats} label="치트 사용" onChange={(cheats) => update({ cheats })} />
            </div>
            <div className={css.policyText}>채택한 치트만 써요. 분류·무인 허용은 프로젝트 설정에서 정해요.*</div>
            <div className={css.policyText} style={{ fontSize: 11 }}>
              * {CHEAT_FOOTNOTE}
            </div>
          </div>
        </div>
      )}
      {conflict && <ConflictNotice onReload={() => void load()} />}
      {error !== null && p !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
