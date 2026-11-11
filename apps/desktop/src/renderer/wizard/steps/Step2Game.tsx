// 2단계 게임 연결 (시안 Setup2Game): 떠 있는 창을 고르거나 실행 파일로 띄워(app.launch) 그 창을 한 번 잡는다
// (target.capture) → 창 제목·해상도는 팀(`project.setup.set`), 실행 파일·인자·작업 폴더는 이 PC(`local.settings.set`).
// 완료 조건 = 창을 한 번 잡음
import type { ResultOf } from "@kookabug/schema";
import { useEffect, useRef, useState } from "react";
import { client, toRpcError } from "../../rpc/client";
import { Spinner } from "../../app/Spinner";
import { ConflictNotice, isConflict } from "../Conflict";
import {
  LAUNCH_POLL_MS,
  LAUNCH_WAIT_MS,
  launchedWindows,
  launchErrorText,
  launchSettings,
  type StoredLaunch,
  storedArgsText,
} from "../launch";
import { StepShell } from "../Wizard";
import { setSummary } from "../wizardStore";
import css from "../wizard.module.css";

type WindowInfo = ResultOf<"windows.list">["windows"][number];
type Frame = ResultOf<"target.capture">;

/** 실행 파일로 띄우기 진행: 띄우는 중 → 창 기다리는 중 → (여러 창이면) 고르기 */
type Launch = { phase: "idle" } | { phase: "launching" } | { phase: "waiting" } | { phase: "pick"; windows: WindowInfo[] };

const usableWindows = (list: readonly WindowInfo[]) => list.filter((w) => w.title.trim() !== "" && !/^Kookabug/.test(w.title));

export function Step2Game() {
  const [tab, setTab] = useState<"window" | "launch">("window");
  const [windows, setWindows] = useState<WindowInfo[] | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [exe, setExe] = useState("");
  const [args, setArgs] = useState("");
  const [launch, setLaunch] = useState<Launch>({ phase: "idle" });
  const [error, setError] = useState<string | null>(null);
  /** 화면을 연 때 읽은 kookabug.json sha·local.json revision (저장 기준, B7 검수 H5) */
  const [base, setBase] = useState<{ config: string; local: string | null } | null>(null);
  const [conflict, setConflict] = useState(false);
  /** 창 기다리기를 멈출 표지 (취소·단계를 떠남) */
  const waitToken = useRef(0);
  /** 마지막으로 읽거나 저장한 이 PC 실행 설정 (칸을 고치지 않았으면 다시 쓰지 않는다, UX1 검수 H2) */
  const stored = useRef<StoredLaunch>({ executable: null, args: null });

  const loadBase = async () => {
    setConflict(false);
    setBase(null);
    try {
      const w = await client().call("wizard.get", {});
      setBase({ config: w.config_sha256, local: w.local_revision });
      // 이 PC에 저장한 실행 설정이 있으면 칸을 채운다 (빈 칸만). 칸을 고치지 않으면 이 값을 그대로 둔다
      stored.current = { executable: w.game.executable ?? null, args: w.game.args ?? null };
      if (w.game.executable !== null) setExe((v) => (v === "" ? (w.game.executable ?? "") : v));
      if (w.game.args !== null) setArgs((v) => (v === "" ? storedArgsText(stored.current) : v));
    } catch (err) {
      setError(toRpcError(err).message);
    }
  };
  useEffect(() => {
    void loadBase();
    return () => {
      waitToken.current += 1; // 단계를 떠나면 기다리기를 멈춘다
    };
  }, []);

  const load = async () => {
    setWindows(null);
    try {
      const list = (await client().call("windows.list", {})).windows;
      setWindows(usableWindows(list));
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
    setCapturing(true);
    try {
      setFrame(await client().call("target.capture", { window: w.handle }));
    } catch (err) {
      setError(`창을 잡지 못했어요: ${toRpcError(err).message}`);
    } finally {
      setCapturing(false);
    }
  };

  const chosen = windows?.find((w) => w.handle === picked) ?? null;

  /** 이 PC 실행 설정 저장 (고친 칸의 키만, 작업 폴더는 실행 파일을 고쳤을 때만). 저장한 revision. 칸을 고치지 않았으면 쓰지 않는다 */
  const saveLocal = async (local: string | null): Promise<string | null> => {
    const settings = launchSettings(stored.current, exe, args);
    if (settings === null) return local;
    const { revision } = await client().call("local.settings.set", { base_revision: local, settings });
    stored.current = {
      executable: settings["game.executable"] ?? stored.current.executable,
      args: "game.args" in settings ? (settings["game.args"] ?? null) : stored.current.args,
    };
    return revision;
  };

  /** "띄우기": 실행 설정을 저장하고 app.launch → 그 프로세스의 창이 뜰 때까지 windows.list (상한 120초) → 한 번 잡기 */
  const startLaunch = async () => {
    if (base === null || conflict) return;
    setError(null);
    if (exe.trim() === "") {
      setError(launchErrorText("exe_missing", ""));
      return;
    }
    const token = ++waitToken.current;
    setLaunch({ phase: "launching" });
    setPicked(null);
    setFrame(null);
    try {
      const revision = await saveLocal(base.local);
      setBase({ ...base, local: revision });
      const before = new Set((await client().call("windows.list", {})).windows.map((w) => w.handle));
      const { pid } = await client().call("app.launch", {});
      if (waitToken.current !== token) return;
      setLaunch({ phase: "waiting" });
      const deadline = Date.now() + LAUNCH_WAIT_MS;
      while (waitToken.current === token) {
        const list = (await client().call("windows.list", {})).windows;
        if (waitToken.current !== token) return;
        const found = launchedWindows(list, pid, exe, before);
        if (found.length > 0) {
          setWindows(usableWindows(list));
          if (found.length === 1) {
            setLaunch({ phase: "idle" });
            await pick(found[0]);
          } else {
            setLaunch({ phase: "pick", windows: found });
          }
          return;
        }
        if (Date.now() >= deadline) {
          setLaunch({ phase: "idle" });
          setError(launchErrorText("timeout", ""));
          return;
        }
        await new Promise((r) => setTimeout(r, LAUNCH_POLL_MS));
      }
    } catch (err) {
      if (waitToken.current !== token) return;
      setLaunch({ phase: "idle" });
      if (isConflict(err)) {
        setConflict(true);
        return;
      }
      const e = toRpcError(err);
      setError(launchErrorText(e.kind ?? undefined, e.message));
    }
  };

  const cancelLaunch = () => {
    waitToken.current += 1;
    setLaunch({ phase: "idle" });
    setError("창 기다리기를 멈췄어요. 게임은 그대로 떠 있을 수 있어요");
  };

  const save = async (): Promise<boolean> => {
    if (chosen === null || frame === null || base === null || conflict) return false;
    try {
      const { sha256 } = await client().call("project.setup.set", {
        base_sha256: base.config,
        settings: { "game.title": chosen.title, "game.client_size": chosen.client_size },
      });
      setBase({ ...base, config: sha256 });
      if (exe.trim() !== "") {
        const revision = await saveLocal(base.local);
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
  const launching = launch.phase === "launching" || launch.phase === "waiting";

  const windowRow = (w: WindowInfo, group: string) => (
    <label key={w.handle} className={css.row} data-selected={w.handle === picked} data-handle={w.handle}>
      <span className={css.rowText}>
        <span className={css.rowTitle}>{w.title}</span>
        <span className={`${css.rowSub} ${css.mono}`}>
          {w.process} · {w.client_size[0]}×{w.client_size[1]}
        </span>
      </span>
      <input type="radio" name={group} checked={w.handle === picked} disabled={capturing} onChange={() => void pick(w)} />
    </label>
  );

  return (
    <StepShell
      title="테스트할 게임을 연결해요"
      lead="이미 떠 있는 게임 창을 고르거나, 실행 파일을 지정해 띄워요."
      primary={{ label: "연결", enabled: frame !== null && base !== null && !conflict && !launching, run: save }}
      right={
        <>
          <div className={css.caption}>
            {frame !== null ? "● 캡처함" : capturing ? <Spinner label="창을 잡는 중…" /> : "창을 고르면 한 번 잡아 보여 줘요"}
          </div>
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
        <button
          type="button"
          aria-pressed={tab === "window"}
          data-part="tab-window"
          onClick={() => {
            setTab("window");
            void load();
          }}
        >
          떠 있는 창 고르기
        </button>
        <button type="button" aria-pressed={tab === "launch"} data-part="tab-launch" onClick={() => setTab("launch")}>
          실행 파일로 띄우기
        </button>
      </div>
      {tab === "window" ? (
        <>
          <div className={`${css.list} ${css.windowList}`} role="radiogroup" aria-label="게임 창" data-part="window-list">
            {windows === null && (
              <div className={css.row}>
                <Spinner label="창 목록을 읽는 중…" delay={0} />
              </div>
            )}
            {windows !== null && windows.length === 0 && (
              <div className={css.row}>
                떠 있는 창이 없어요.{" "}
                <button type="button" className={css.linkButton} onClick={() => void load()}>
                  다시 찾기
                </button>
              </div>
            )}
            {windows?.map((w) => windowRow(w, "window"))}
          </div>
          {windows !== null && windows.length > 0 && (
            <span className={css.hint}>
              게임이 안 보이면{" "}
              <button type="button" className={css.linkButton} onClick={() => void load()} data-part="window-reload">
                다시 찾기
              </button>
            </span>
          )}
        </>
      ) : (
        <>
          <label className={css.field}>
            <span className={css.fieldLabel}>실행 파일</span>
            <input
              className={`${css.input} ${css.mono}`}
              aria-label="실행 파일"
              value={exe}
              disabled={launching}
              onChange={(e) => setExe(e.target.value)}
              placeholder="C:\Games\MyGame\Game.exe"
            />
          </label>
          <label className={css.field}>
            <span className={css.fieldLabel}>인자 (선택)</span>
            <input
              className={`${css.input} ${css.mono}`}
              aria-label="인자"
              value={args}
              disabled={launching}
              onChange={(e) => setArgs(e.target.value)}
              placeholder='-windowed -config "C:\My Game\user.ini"'
            />
          </label>
          <div className={css.inputRow} data-part="launch-row">
            {launching ? (
              <>
                <Spinner label={launch.phase === "launching" ? "게임을 띄우는 중…" : "게임 창을 기다리는 중…"} delay={0} />
                <button type="button" className={css.small} data-part="launch-cancel" onClick={cancelLaunch}>
                  취소
                </button>
              </>
            ) : (
              <button
                type="button"
                className={css.small}
                data-part="launch"
                disabled={base === null || conflict || exe.trim() === ""}
                onClick={() => void startLaunch()}
              >
                띄우기
              </button>
            )}
          </div>
          {launch.phase === "pick" && (
            <>
              <span className={css.hint}>창이 여러 개 떴어요. 게임 창을 골라 주세요.</span>
              <div className={`${css.list} ${css.windowList}`} role="radiogroup" aria-label="띄운 게임 창" data-part="launched-list">
                {launch.windows.map((w) => windowRow(w, "launched"))}
              </div>
            </>
          )}
          <span className={css.hint}>
            경로는 사람마다 달라서 이 PC에만 저장돼요. 작업 폴더는 실행 파일 폴더예요. 공백이 든 인자는 큰따옴표로 묶어 주세요.
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
