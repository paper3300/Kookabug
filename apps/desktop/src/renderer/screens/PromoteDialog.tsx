// 승격 대화 상자 (M7 계획 3.7·3.14): 새 화면으로 옮기기(ID·제목·설명·폴더) 또는 확정 화면에 합치기(체크 2개).
// 입력이 바뀔 때마다 `screens.check`(승격과 같은 mode·id·folder·replace_*)로 할 수 있는지·경고를 보이고,
// [옮기기]는 그 확인의 revision 그대로 `screens.promote`를 부른다 — 그 사이 파일이 바뀌면 revision_conflict.
// 사람(ui) 연결 RPC만 쓴다. 실패 "옮기지 못했어요. 기존 파일은 그대로예요.", 마무리가 남으면
// "옮겼어요 — 정리는 다음에 마저 해요"
import type { ResultOf } from "@kookabug/schema";
import { useEffect, useState } from "react";
import { client, toRpcError } from "../rpc/client";
import { loadMap, recoveryText, select, setNotice, type PromoteTarget } from "./mapStore";
import { promoteParams, promotedText, type PromoteForm } from "./promote";
import css from "./map.module.css";

type Check = ResultOf<"screens.check">;

export function PromoteDialog({ target, onClose }: { target: PromoteTarget; onClose(): void }) {
  const [form, setForm] = useState<PromoteForm>({
    id: target.key,
    title: target.title ?? "",
    description: "",
    folder: "",
    replaceShot: false,
    replaceDetect: false,
  });
  const [check, setCheck] = useState<Check | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const params = promoteParams(target, form);
  const key = JSON.stringify(params);

  useEffect(() => {
    let alive = true;
    setCheck(null);
    const timer = setTimeout(() => {
      client()
        .call("screens.check", params)
        .then((r) => {
          if (!alive) return;
          setCheck(r);
          setCheckError(null);
        })
        .catch((err: unknown) => {
          if (!alive) return;
          const e = toRpcError(err);
          setCheckError(e.kind === "recovery_pending" ? recoveryText(e.message) : e.message);
        });
    }, 200);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // params는 key로 비교한다 (렌더마다 새 객체)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const submit = async () => {
    if (check === null || !check.ok) return;
    setBusy(true);
    setFailed(null);
    try {
      const r = await client().call("screens.promote", {
        ...params,
        base_revisions: check.revisions,
        ...(target.mode === "new" && form.title.trim() !== "" ? { title: form.title.trim() } : {}),
        ...(target.mode === "new" && form.description.trim() !== "" ? { description: form.description.trim() } : {}),
      });
      setNotice(promotedText(r.cleanup_pending));
      onClose();
      await loadMap();
      select(r.id);
    } catch (err) {
      const e = toRpcError(err);
      setFailed(
        `옮기지 못했어요. 기존 파일은 그대로예요.${e.kind === "recovery_pending" ? ` ${recoveryText(e.message)}` : ` (${e.message})`}`,
      );
      setBusy(false);
    }
  };

  const problems = check?.problems ?? [];
  const warnings = check?.warnings ?? [];
  return (
    <div className={css.backdrop} data-part="promote-backdrop" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-label={target.mode === "merge" ? "확정 화면에 합치기" : "확정 화면으로 옮기기"} className={css.dialog} data-part="promote-dialog" data-mode={target.mode}>
        <div className={css.dialogTitle}>
          {target.mode === "merge"
            ? `${target.title ?? target.key} → ${target.of ?? "?"}에 합치기`
            : `${target.title ?? target.key} 확정 화면으로 옮기기`}
        </div>
        {target.mode === "new" ? (
          <>
            <label className={css.field}>
              <span className={css.fieldLabel}>화면 ID</span>
              <input className={css.input} aria-label="화면 ID" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} />
            </label>
            <label className={css.field}>
              <span className={css.fieldLabel}>제목</span>
              <input className={css.input} aria-label="제목" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </label>
            <label className={css.field}>
              <span className={css.fieldLabel}>설명 (비우면 후보 설명 그대로)</span>
              <input
                className={css.input}
                aria-label="설명"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </label>
            <label className={css.field}>
              <span className={css.fieldLabel}>폴더 (screens/ 아래, 비우면 바로 아래)</span>
              <input className={css.input} aria-label="폴더" value={form.folder} onChange={(e) => setForm({ ...form, folder: e.target.value })} />
            </label>
          </>
        ) : (
          <>
            <div className={css.result}>이동·UI 요소는 더하고 같은 것은 건너뛰어요. 아래를 고르면 그것도 바꿔요.</div>
            <label className={css.check}>
              <input
                type="checkbox"
                aria-label="대표 스크린샷 바꾸기"
                checked={form.replaceShot}
                onChange={(e) => setForm({ ...form, replaceShot: e.target.checked })}
              />
              대표 스크린샷 바꾸기
            </label>
            <label className={css.check}>
              <input
                type="checkbox"
                aria-label="판정 조건 바꾸기"
                checked={form.replaceDetect}
                onChange={(e) => setForm({ ...form, replaceDetect: e.target.checked })}
              />
              판정 조건 바꾸기
            </label>
          </>
        )}
        <div className={css.result} data-part="promote-check" data-ok={check?.ok ?? ""}>
          {check === null && checkError === null && <span className={css.muted}>확인하는 중…</span>}
          {checkError !== null && <span className={css.problem}>{checkError}</span>}
          {check?.ok === true && check.path !== undefined && <span>→ {check.path}</span>}
          {check?.shot === "matched" && <span className={css.muted}>판정 조건이 대표 스크린샷에서 맞아요</span>}
          {problems.map((p, i) => (
            <span key={`p${i}`} className={css.problem} data-part="promote-problem">
              {check?.code === "recovery_pending" ? recoveryText(p) : p}
            </span>
          ))}
          {warnings.map((w, i) => (
            <span key={`w${i}`} className={css.warning} data-part="promote-warning">
              {w}
            </span>
          ))}
          {failed !== null && (
            <span className={css.problem} data-part="promote-failed">
              {failed}
            </span>
          )}
        </div>
        <div className={css.dialogButtons}>
          <button type="button" className={css.secondary} onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className={css.primary}
            data-part="promote-submit"
            disabled={busy || check === null || !check.ok}
            onClick={() => void submit()}
          >
            {target.mode === "merge" ? "합치기" : "옮기기"}
          </button>
        </div>
      </div>
    </div>
  );
}
