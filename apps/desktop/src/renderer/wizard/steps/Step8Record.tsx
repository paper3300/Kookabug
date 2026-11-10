// 8단계 기록 정책 (필수, 시안 Setup6Record — 번호만 바뀜): 스크린샷·영상(끔/실패만/항상)·보관 기간. "다음" = 기본값
// 확인. 팀 `kookabug.json` record·retention (`project.setup.set`). 보관 기간 실제 정리는 MVP처럼 없음 (R11)
import { useCallback, useEffect, useState } from "react";
import { client, toRpcError } from "../../rpc/client";
import { ConflictNotice, isConflict } from "../Conflict";
import { StepShell } from "../Wizard";
import { setSummary } from "../wizardStore";
import css from "../wizard.module.css";

type Video = "off" | "failed_only" | "on";
const VIDEO: [Video, string][] = [
  ["off", "끔"],
  ["failed_only", "실패만"],
  ["on", "항상"],
];

export function Step8Record() {
  const [shots, setShots] = useState(true);
  const [video, setVideo] = useState<Video>("failed_only");
  const [passed, setPassed] = useState(14);
  const [failed, setFailed] = useState(60);
  const [record, setRecord] = useState<Record<string, unknown>>({});
  const [retention, setRetention] = useState<Record<string, unknown>>({});
  /** 화면을 채운 같은 읽기의 sha (저장 기준, B7 검수 H5). 못 읽었으면 null — 저장 단추가 꺼진다 */
  const [base, setBase] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBase(null);
    setConflict(false);
    setError(null);
    try {
      const w = await client().call("wizard.get", {});
      const r = w.record as { screenshots?: string; video?: Video };
      const t = w.retention as { passed_days?: number; failed_days?: number };
      setRecord(w.record);
      setRetention(w.retention);
      if (r.screenshots !== undefined) setShots(r.screenshots === "on");
      if (r.video !== undefined) setVideo(r.video);
      if (t.passed_days !== undefined) setPassed(t.passed_days);
      if (t.failed_days !== undefined) setFailed(t.failed_days);
      setBase(w.config_sha256);
    } catch (err) {
      setError(toRpcError(err).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (): Promise<boolean> => {
    if (base === null || conflict) return false;
    try {
      const { sha256 } = await client().call("project.setup.set", {
        base_sha256: base,
        record: { ...record, screenshots: shots ? "on" : "off", video },
        retention: { ...retention, passed_days: passed, failed_days: failed },
      });
      setBase(sha256);
      setSummary(8, `스크린샷 ${shots ? "켬" : "끔"} · 영상 ${VIDEO.find(([v]) => v === video)?.[1]} · ${passed}일 / ${failed}일`);
      return true;
    } catch (err) {
      if (isConflict(err)) setConflict(true);
      else setError(toRpcError(err).message);
      return false;
    }
  };

  return (
    <StepShell
      title="실행 기록을 어떻게 남길까요?"
      lead="실패 원인을 찾으려면 기록이 필요해요. 민감한 화면은 따로 끌 수 있어요."
      primary={{ label: "다음", enabled: base !== null && !conflict && passed >= 0 && failed >= 0, run: save }}
      right={
        <div className={css.card}>
          <div className={css.cardHead}>기록 미리보기</div>
          <div className={css.cardRow}>
            <span className={css.mark}>{shots ? "✓" : "–"}</span>노드 실행 전후와 실패 순간 스크린샷
          </div>
          <div className={css.cardRow}>
            <span className={css.mark}>{video === "off" ? "–" : "✓"}</span>영상: {video === "off" ? "남기지 않음" : video === "on" ? "항상 보관" : "통과하면 지우고 실패면 보관"}
          </div>
          <div className={css.cardRow}>
            <span className={css.mark}>✓</span>보관: 통과 {passed}일 · 실패 {failed}일
          </div>
        </div>
      }
    >
      <div className={css.policy} data-part="record-policy">
        <label className={css.policyRow}>
          <span className={css.policyHead}>
            노드별 스크린샷
            <input type="checkbox" checked={shots} onChange={(e) => setShots(e.target.checked)} />
          </span>
          <span className={css.policyText}>노드 실행 전후와 실패 순간을 남겨요</span>
        </label>
        <div className={css.policyRow}>
          <div className={css.policyHead}>
            영상
            <div className={css.seg} role="group" aria-label="영상">
              {VIDEO.map(([v, label]) => (
                <button key={v} type="button" aria-pressed={video === v} onClick={() => setVideo(v)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <span className={css.policyText}>실행 중엔 계속 찍고, 성공하면 지워요</span>
        </div>
        <div className={css.policyRow}>
          <div className={css.policyHead}>
            보관 기간
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 400 }}>
              통과
              <input className={css.number} type="number" min={0} aria-label="통과 보관 일" value={passed} onChange={(e) => setPassed(Math.floor(Number(e.target.value)))} />
              일 실패
              <input className={css.number} type="number" min={0} aria-label="실패 보관 일" value={failed} onChange={(e) => setFailed(Math.floor(Number(e.target.value)))} />일
            </span>
          </div>
          <span className={css.policyText}>최근 50개와 고정한 실행은 항상 남아요</span>
        </div>
      </div>
      <div className={css.info}>
        비밀번호를 입력하는 노드는 스크린샷을 자동으로 남기지 않아요. 하지만 입력한 값이 다음 화면에 보일 수 있으니, 로그인처럼 화면
        전체가 민감한 구간은 서브그래프에서 <b>기록 끄기</b>를 쓰세요.
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
