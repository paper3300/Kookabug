// 2단계 게임 연결 (시안 Setup2Game): 떠 있는 창을 고르고 한 번 잡는다(target.capture) → 창 제목·해상도는 팀
// (`project.setup.set`), 실행 파일 경로는 이 PC(`local.settings.set`). 완료 조건 = 창을 한 번 잡음
import type { ResultOf } from "@kookabug/schema";
import { useEffect, useState } from "react";
import { client, toRpcError } from "../../rpc/client";
import { ConflictNotice, isConflict } from "../Conflict";
import { StepShell } from "../Wizard";
import { setSummary } from "../wizardStore";
import css from "../wizard.module.css";

type WindowInfo = ResultOf<"windows.list">["windows"][number];
type Frame = ResultOf<"target.capture">;

export function Step2Game() {
  const [tab, setTab] = useState<"window" | "launch">("window");
  const [windows, setWindows] = useState<WindowInfo[] | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [exe, setExe] = useState("");
  const [args, setArgs] = useState("");
  const [error, setError] = useState<string | null>(null);
  /** 화면을 연 때 읽은 kookabug.json sha·local.json revision (저장 기준, B7 검수 H5) */
  const [base, setBase] = useState<{ config: string; local: string | null } | null>(null);
  const [conflict, setConflict] = useState(false);

  const loadBase = async () => {
    setConflict(false);
    setBase(null);
    try {
      const w = await client().call("wizard.get", {});
      setBase({ config: w.config_sha256, local: w.local_revision });
    } catch (err) {
      setError(toRpcError(err).message);
    }
  };
  useEffect(() => {
    void loadBase();
  }, []);

  const load = async () => {
    try {
      const list = (await client().call("windows.list", {})).windows;
      setWindows(list.filter((w) => w.title.trim() !== "" && !/^Kookabug/.test(w.title)));
    } catch (err) {
      setError(toRpcError(err).message);
      setWindows([]);
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const pick = async (w: WindowInfo) => {
    setPicked(w.handle);
    setFrame(null);
    setError(null);
    try {
      setFrame(await client().call("target.capture", { window: w.handle }));
    } catch (err) {
      setError(`창을 잡지 못했어요: ${toRpcError(err).message}`);
    }
  };

  const chosen = windows?.find((w) => w.handle === picked) ?? null;

  const save = async (): Promise<boolean> => {
    if (chosen === null || frame === null || base === null || conflict) return false;
    try {
      const { sha256 } = await client().call("project.setup.set", {
        base_sha256: base.config,
        settings: { "game.title": chosen.title, "game.client_size": chosen.client_size },
      });
      setBase({ ...base, config: sha256 });
      if (exe.trim() !== "") {
        const { revision } = await client().call("local.settings.set", {
          base_revision: base.local,
          settings: {
            "game.executable": exe.trim(),
            "game.args": args.trim() === "" ? null : args.trim().split(/\s+/),
          },
        });
        setBase({ config: sha256, local: revision });
      }
      const [w, h] = chosen.client_size;
      setSummary(2, `${chosen.title} · ${w}×${h} · DPI ${Math.round((chosen.dpi / 96) * 100)}%`);
      return true;
    } catch (err) {
      if (isConflict(err)) setConflict(true);
      else setError(toRpcError(err).message);
      return false;
    }
  };

  const image = frame !== null && "cache" in frame.image ? `kbimg://cache/${frame.image.cache}` : null;

  return (
    <StepShell
      title="테스트할 게임을 연결해요"
      lead="이미 떠 있는 게임 창을 고르거나, 실행 파일을 지정해 띄워요."
      primary={{ label: "연결", enabled: frame !== null && base !== null && !conflict, run: save }}
      right={
        <>
          <div className={css.caption}>{frame !== null ? "● 캡처함" : "창을 고르면 한 번 잡아 보여 줘요"}</div>
          {image !== null ? (
            <img className={css.preview} src={image} alt="게임 창 캡처" data-part="game-preview" />
          ) : (
            <div className={css.preview} />
          )}
          {chosen !== null && frame !== null && (
            <div className={css.chips}>
              <span>
                {chosen.client_size[0]}×{chosen.client_size[1]}
              </span>
              <span>DPI {Math.round((chosen.dpi / 96) * 100)}%</span>
              <span>{chosen.process}</span>
            </div>
          )}
        </>
      }
    >
      <div className={css.seg} role="group" aria-label="게임 연결 방식">
        <button type="button" aria-pressed={tab === "window"} onClick={() => setTab("window")}>
          떠 있는 창 고르기
        </button>
        <button type="button" aria-pressed={tab === "launch"} onClick={() => setTab("launch")}>
          실행 파일로 띄우기
        </button>
      </div>
      {tab === "window" ? (
        <div className={css.list} role="radiogroup" aria-label="게임 창" data-part="window-list">
          {windows === null && <div className={css.row}>창 목록을 읽는 중…</div>}
          {windows !== null && windows.length === 0 && (
            <div className={css.row}>
              떠 있는 창이 없어요.{" "}
              <button type="button" className={css.linkButton} onClick={() => void load()}>
                다시 찾기
              </button>
            </div>
          )}
          {windows?.slice(0, 6).map((w) => (
            <label key={w.handle} className={css.row} data-selected={w.handle === picked}>
              <span className={css.rowText}>
                <span className={css.rowTitle}>{w.title}</span>
                <span className={`${css.rowSub} ${css.mono}`}>
                  {w.process} · {w.client_size[0]}×{w.client_size[1]}
                </span>
              </span>
              <input type="radio" name="window" checked={w.handle === picked} onChange={() => void pick(w)} />
            </label>
          ))}
        </div>
      ) : (
        <>
          <label className={css.field}>
            <span className={css.fieldLabel}>실행 파일</span>
            <input className={`${css.input} ${css.mono}`} value={exe} onChange={(e) => setExe(e.target.value)} placeholder="C:\Games\MyGame\Game.exe" />
          </label>
          <label className={css.field}>
            <span className={css.fieldLabel}>인자 (선택)</span>
            <input className={`${css.input} ${css.mono}`} value={args} onChange={(e) => setArgs(e.target.value)} />
          </label>
          <span className={css.hint}>
            경로는 사람마다 달라서 이 PC에만 저장돼요. 게임을 띄운 뒤 "떠 있는 창 고르기"에서 창을 한 번 잡아요.
          </span>
        </>
      )}
      {conflict && <ConflictNotice onReload={() => void loadBase()} />}
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
