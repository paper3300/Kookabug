// 1단계 프로젝트 만들기 (시안 Setup1Project + KB문서 13장: 폴더 구조에 knowledge/·wiki/). "만들기" = 주 프로세스가
// `kookabug workspace new`를 띄우고 그 폴더를 연다 → daemon이 붙으면 wizard.json에 진행을 남기기 시작한다
import { useState } from "react";
import { useWorkspace } from "../../store/workspace";
import { StepShell } from "../Wizard";
import { markPersisted, setSummary } from "../wizardStore";
import css from "../wizard.module.css";

const TREE: [string, string][] = [
  ["tests\\", "테스트"],
  ["subgraphs\\", "재사용 구간"],
  ["targets\\", "찾기 대상·이미지"],
  ["screens\\", "화면 지도"],
  ["knowledge\\", "주장·사건·증거"],
  ["wiki\\", "위키·보고서"],
  ["runs\\", "실행 기록 · Git 제외"],
  [".kookabug\\", "개인 설정 · Git 제외"],
  ["kookabug.json", "팀 공용 설정"],
  ["AGENTS.md", "에이전트 안내"],
];

/** 렌더러 안의 앱 오류 "Error invoking remote method 'kb:app': Error: code: 메시지" → 메시지 */
export function appErrorText(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  return message.replace(/^Error invoking remote method '[^']*': (\w*Error: )?/, "").replace(/^[a-z_]+: /, "");
}

/** 열린 루트가 그 폴더이고 daemon이 붙을 때까지 (최대 60초) */
export function waitConnected(folder: string, timeoutMs = 60_000): Promise<boolean> {
  const same = (a: string | null) => a !== null && a.replace(/[\\/]+$/, "").toLowerCase() === folder.replace(/[\\/]+$/, "").toLowerCase();
  const ok = () => {
    const s = useWorkspace.getState();
    return same(s.root) && s.daemon.status === "connected";
  };
  if (ok()) return Promise.resolve(true);
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      stop();
      resolve(false);
    }, timeoutMs);
    const stop = useWorkspace.subscribe(() => {
      if (!ok()) return;
      clearTimeout(timer);
      stop();
      resolve(true);
    });
  });
}

export function Step1Project() {
  const [name, setName] = useState("my-game");
  const [parent, setParent] = useState("");
  const [git, setGit] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 만들었지만 daemon에 아직 못 붙은 폴더: 다시 누르면 만들지 않고 붙기만 기다린다 (같은 폴더를 또 만들면 거부된다)
  const [created, setCreated] = useState<{ root: string; name: string } | null>(null);

  const create = async (): Promise<boolean> => {
    setError(null);
    try {
      let target = created;
      if (target === null) {
        const opened = await window.kookabug.app.workspaceCreate({ parent, name, git });
        if (!opened.ok) {
          setError("만든 폴더를 열지 못했어요");
          return false;
        }
        target = { root: opened.root, name: opened.name };
        setCreated(target);
      }
      if (!(await waitConnected(target.root))) {
        setError("프로젝트는 만들었지만 daemon에 붙지 못했어요. 다시 누르면 붙기를 기다려요");
        return false;
      }
      markPersisted();
      setSummary(1, `${target.name}${git ? " · Git" : ""}`);
      return true;
    } catch (err) {
      setError(appErrorText(err));
      return false;
    }
  };

  return (
    <StepShell
      title="프로젝트를 만들어요"
      lead="게임 하나에 프로젝트 하나예요. 테스트, 찾기 대상, 실행 기록, 지식과 위키가 이 폴더에 모여요."
      primary={{ label: "만들기", enabled: name.trim() !== "" && parent !== "", run: create }}
      right={
        <div className={css.card}>
          <div className={css.cardHead}>만들어질 폴더</div>
          <div className={css.tree}>
            <div className={css.treeRow}>
              <span>{name || "프로젝트"}\</span>
            </div>
            {TREE.map(([p, label], i) => (
              <div key={p} className={css.treeRow}>
                <span>
                  {i === TREE.length - 1 ? "└─ " : "├─ "}
                  {p}
                </span>
                <small>{label}</small>
              </div>
            ))}
          </div>
        </div>
      }
    >
      <label className={css.field}>
        <span className={css.fieldLabel}>프로젝트 이름</span>
        <input className={css.input} value={name} aria-label="프로젝트 이름" onChange={(e) => setName(e.target.value)} />
      </label>
      <div className={css.field}>
        <span className={css.fieldLabel}>위치</span>
        <div className={css.inputRow}>
          <input className={`${css.input} ${css.mono}`} value={parent} readOnly aria-label="위치" placeholder="폴더를 고르세요" />
          <button
            type="button"
            className={css.small}
            onClick={() => {
              void window.kookabug.app.pickFolder().then((picked) => {
                if (picked !== null) setParent(picked);
              });
            }}
          >
            찾아보기
          </button>
        </div>
      </div>
      <label className={css.check}>
        <input type="checkbox" checked={git} onChange={(e) => setGit(e.target.checked)} />
        <span>
          Git 저장소로 만들기
          <small>실행 기록과 개인 설정은 자동으로 Git에서 빠져요</small>
        </span>
      </label>
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
