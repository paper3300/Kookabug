// 6단계 프로젝트 정보 원본 (선택, 시안 Wizard6Sources). 입력한 항목을 `project.sources.set`(팀)·`local.settings.set`
// (이 PC 절대 경로)에 쓰고 `sources.check`로 읽기 확인. 읽지 못한 항목은 경고로 남기고 진행한다(Init이 미지수로 기록).
// 칸마다 "+ 추가"로 줄을 더하고 "−"로 지운다 (UX1 U4 — 기획서가 여러 폴더에 있을 수 있다). 줄 ID 규칙은 sources.ts
import { useCallback, useEffect, useState } from "react";
import { client, toRpcError } from "../../rpc/client";
import { Spinner } from "../../app/Spinner";
import { ConflictNotice, isConflict } from "../Conflict";
import {
  DUPLICATE_TEXT,
  duplicateIds,
  initialRows,
  initialValues,
  nextRowId,
  planSources,
  rowTitle,
  SLOTS,
  toSource,
  type SourceDef,
  type SourceSlot,
} from "../sources";
import { StorageBadge } from "../StorageBadge";
import { StepShell } from "../Wizard";
import { setStepWarnings, setSummary } from "../wizardStore";
import css from "../wizard.module.css";

type Check = { id: string; state: string };

const STATE_TEXT: Record<string, string> = {
  ok: "읽음",
  missing: "없음 · 경고",
  unreadable: "읽지 못함 · 경고",
  unchecked_url: "주소 · Agent가 읽어요",
};

/** 화면을 채운 읽기 하나 (wizard.get): 팀 원본 전체·줄 초기값·저장 기준 sha·revision */
interface Loaded {
  sources: SourceDef[];
  initial: Record<string, string>;
  base: string;
  localRevision: string | null;
}

export function Step6Sources() {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  /** 칸 ID → 줄 ID들 */
  const [rows, setRows] = useState<Record<string, string[]>>({});
  /** 팀 원본·이 화면의 줄 ID (새 무작위 ID가 이와 같으면 다시 뽑는다) */
  const [used, setUsed] = useState<Set<string>>(new Set());
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [checking, setChecking] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoaded(null);
    setChecks(null);
    setConflict(false);
    setError(null);
    try {
      // 팀 원본·이 PC 경로·sha·revision을 같은 읽기로 (사람 전용 wizard.get — 경로만, 비밀값 없음)
      const w = await client().call("wizard.get", {});
      const sources = w.sources as SourceDef[];
      const initial = initialValues(sources, w.local_sources);
      const firstRows = initialRows(sources);
      setValues(initial);
      setRows(firstRows);
      setUsed(new Set([...sources.map((s) => s.id), ...Object.values(firstRows).flat()]));
      setLoaded({ sources, initial, base: w.config_sha256, localRevision: w.local_revision });
    } catch (err) {
      // 못 읽으면 빈 설정으로 저장하지 않는다 (확인 단추가 꺼진다)
      setError(`원본 설정을 읽지 못했어요: ${toRpcError(err).message}`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const edit = (id: string, value: string) => {
    setValues((v) => ({ ...v, [id]: value }));
    setChecks(null);
  };

  const addRow = (slot: SourceSlot) => {
    const id = nextRowId(slot, used);
    setUsed((u) => new Set(u).add(id));
    setRows((r) => ({ ...r, [slot.id]: [...(r[slot.id] ?? [slot.id]), id] }));
    setValues((v) => ({ ...v, [id]: "" }));
    setChecks(null);
  };

  /** 줄 지우기 = 그 줄을 비운다(저장 계획이 지운다). 칸의 마지막 줄은 남기고 비우기만 한다 */
  const removeRow = (slot: SourceSlot, id: string) => {
    setRows((r) => {
      const list = r[slot.id] ?? [slot.id];
      return list.length <= 1 ? r : { ...r, [slot.id]: list.filter((x) => x !== id) };
    });
    setValues((v) => ({ ...v, [id]: "" }));
    setChecks(null);
  };

  // 같은 ID 원본이 여럿인 줄은 읽기 전용 + 안내 (그 항목들은 저장하지 않고 그대로 둔다)
  const duplicates = loaded === null ? new Set<string>() : duplicateIds(loaded.sources);
  const lines = SLOTS.flatMap((slot) =>
    (rows[slot.id] ?? [slot.id]).map((id) => ({ slot, id, parsed: toSource(slot, values[id] ?? "", id) })),
  );
  const filled = lines.filter((e) => e.parsed !== null);

  const check = async (): Promise<boolean> => {
    if (checks !== null) {
      const bad = checks.filter((c) => c.state === "missing" || c.state === "unreadable");
      setSummary(6, filled.length === 0 ? "입력 안 함" : `${filled.length}개 등록${bad.length > 0 ? ` · 경고 ${bad.length}` : ""}`, bad.length > 0);
      return true;
    }
    if (loaded === null || conflict) return false;
    setError(null);
    setChecking(true);
    try {
      const plan = planSources(loaded.sources, loaded.initial, values);
      let { base, localRevision } = loaded;
      if (plan.changed) {
        // 팀 먼저 (충돌이면 아무것도 쓰지 않았다), 그다음 이 PC. 둘 다 화면을 채울 때 읽은 기준으로
        base = (await client().call("project.sources.set", { base_sha256: base, value: plan.defs as never })).sha256;
        if (Object.keys(plan.local).length > 0) {
          localRevision = (await client().call("local.settings.set", { base_revision: localRevision, sources: plan.local })).revision;
        }
        // 다음 저장의 기준: 지금 줄 값 (지운 줄은 빈 값 = 원본 없음)
        const nextInitial: Record<string, string> = {};
        for (const [id, v] of Object.entries(values)) if (v.trim() !== "") nextInitial[id] = v;
        setLoaded({ sources: plan.defs, initial: nextInitial, base, localRevision });
      }
      const r = await client().call("sources.check", {});
      const result = (r.sources as Check[]).filter((c) => filled.some((e) => e.id === c.id));
      setChecks(result);
      const bad = result.filter((c) => c.state === "missing" || c.state === "unreadable");
      setStepWarnings(6, bad.map((c) => `source_${c.state}:${c.id}`));
      return false; // 결과를 보여 주고 한 번 더 누르면 다음
    } catch (err) {
      if (isConflict(err)) setConflict(true);
      else setError(toRpcError(err).message);
      return false;
    } finally {
      setChecking(false);
    }
  };

  const bad = checks?.filter((c) => c.state === "missing" || c.state === "unreadable") ?? [];
  return (
    <StepShell
      title="게임 정보는 어디에 있나요?"
      lead="Init 때 읽고 기대 결과의 근거로 써요. 원본은 읽기만 하고 바꾸지 않아요. 칸마다 여러 곳을 넣을 수 있어요."
      primary={{ label: checks === null ? "확인" : "다음", enabled: loaded !== null && !conflict, run: check, busyLabel: "확인 중…" }}
      note={bad.length > 0 ? `읽지 못한 ${bad.length}개는 경고로 남기고, Init이 미지수로 기록해요` : undefined}
      right={
        <>
          <div className={css.caption}>원본이 없어도 Init은 돌아요. 대신 게임 화면만 보고 추측한 주장이 많아져요.</div>
          <div className={css.card}>
            <div className={css.cardHead}>Init이 이걸로 만드는 것</div>
            <div className={css.tree}>
              <div>wiki/</div>
              {[
                ["overview.md", "기획 문서"],
                ["roadmap.md", "패치 노트 · 기획 문서"],
                ["glossary.md", "문자열 테이블"],
                ["features/<기능>.md", "데이터 · 코드"],
              ].map(([f, from]) => (
                <div key={f} className={css.treeRow} style={{ paddingLeft: 16 }}>
                  <span>{f}</span>
                  <small>{from}</small>
                </div>
              ))}
              <div>knowledge/features/</div>
              <div className={css.treeRow} style={{ paddingLeft: 16 }}>
                <span>&lt;기능&gt;.json</span>
                <small>주장 후보 · 추측</small>
              </div>
            </div>
          </div>
        </>
      }
    >
      {loaded === null && error === null && <Spinner label="원본 설정을 읽는 중…" />}
      <div className={`${css.list} ${css.sourceList}`} data-part="source-list">
        {SLOTS.map((slot) => {
          const ids = rows[slot.id] ?? [slot.id];
          return (
            <div key={slot.id} className={css.row} data-slot={slot.id} style={{ alignItems: "flex-start" }}>
              <span className={css.avatar} aria-hidden="true" style={{ borderRadius: 6 }}>
                {slot.icon}
              </span>
              <span className={css.rowText}>
                <span className={css.rowTitle}>
                  {slot.title}
                  <span className={css.spacer} />
                  <button
                    type="button"
                    className={css.linkButton}
                    data-part="source-add"
                    title="이 칸에 원본 줄을 더해요"
                    disabled={loaded === null}
                    onClick={() => addRow(slot)}
                  >
                    + 추가
                  </button>
                </span>
                {ids.map((id) => {
                  const parsed = toSource(slot, values[id] ?? "", id);
                  const state = checks?.find((c) => c.id === id)?.state;
                  return (
                    <span key={id} className={css.sourceLine} data-source={id} data-state={state ?? ""}>
                      <input
                        className={`${css.input} ${css.mono}`}
                        style={{ height: 26, fontSize: 12 }}
                        aria-label={rowTitle(slot, id)}
                        placeholder="폴더 · 파일 · URL"
                        value={values[id] ?? ""}
                        readOnly={duplicates.has(id)}
                        onChange={(e) => edit(id, e.target.value)}
                      />
                      {parsed !== null && <StorageBadge storage={parsed.localPath !== null ? "pc" : "team"} />}
                      {state !== undefined && (
                        <span className={css.tag} data-tone={state === "ok" ? undefined : state === "unchecked_url" ? "muted" : "warn"}>
                          {STATE_TEXT[state] ?? state}
                        </span>
                      )}
                      <button
                        type="button"
                        className={css.iconButton}
                        data-part="source-remove"
                        title={ids.length > 1 ? "이 줄 지우기" : "비우기"}
                        disabled={duplicates.has(id) || (ids.length <= 1 && (values[id] ?? "") === "")}
                        onClick={() => removeRow(slot, id)}
                      >
                        −
                      </button>
                      {duplicates.has(id) && (
                        <span role="note" className={css.error} style={{ margin: 0, fontSize: 11 }} data-part="source-duplicate">
                          {DUPLICATE_TEXT}
                        </span>
                      )}
                    </span>
                  );
                })}
              </span>
            </div>
          );
        })}
      </div>
      {checking && <Spinner label="원본을 확인하는 중…" />}
      <div className={css.info}>
        원본은 프로젝트에 복사하지 않아요. <b>위치와 해시만</b> 남겨 두고, 바뀌면 관련 테스트를 먼저 다시 확인해요. 사람마다 경로가
        다른 폴더(절대 경로)는 <b>이 PC</b>에만 저장해요.
      </div>
      {conflict && <ConflictNotice onReload={() => void load()} />}
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
