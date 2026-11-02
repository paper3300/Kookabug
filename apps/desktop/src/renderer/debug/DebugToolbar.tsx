// 디버그 툴바 (시안 Main "실행 제어", M3 계획 2.9). 캔버스 위 가운데에 떠 있고 실행이 있을 때만 보인다.
// 끌기 손잡이(⋮⋮)로 가로로 옮기고 자리는 앱 설정에 기억한다.
// 단추: 일시정지 F6(멈춘 동안은 같은 자리에 "계속 F5"), 다음 노드 F10, 서브그래프로 들어가기 F11, 서브그래프에서
// 나오기 Shift+F11(U3), 다시 시작 Ctrl+Shift+F5, 정지 Shift+F5. 단추 이름(aria-label)은 시안 그대로다
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { create } from "zustand";
import {
  ContinueIcon,
  PauseIcon,
  RestartIcon,
  StepIntoIcon,
  StepOutIcon,
  StepOverIcon,
  StopIcon,
} from "../theme/icons";
import { pauseRun, restartRun, resumeRun, stopRun, useDebugAvailability } from "./commands";
import css from "./debug.module.css";
import { clampX } from "./position";

/** 가로 자리 (가운데 기준 px). 앱 설정에서 한 번 읽는다 */
const usePosition = create<{ x: number; loaded: boolean }>(() => ({ x: 0, loaded: false }));

async function loadPosition(): Promise<void> {
  if (usePosition.getState().loaded) return;
  try {
    const x = await window.kookabug.app.debugToolbarGet();
    usePosition.setState({ x, loaded: true });
  } catch {
    usePosition.setState({ loaded: true });
  }
}

interface Measure {
  area: number;
  width: number;
}

export function DebugToolbar() {
  const a = useDebugAvailability();
  const x = usePosition((s) => s.x);
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ startX: number; from: number } | null>(null);
  // 영역·툴바 폭 (검수 T9-1: 창만 줄여도 다시 그리게 관측한다)
  const [measure, setMeasure] = useState<Measure | null>(null);

  useEffect(() => {
    void loadPosition();
  }, []);

  // 그리기 전에 한 번 재고(첫 표시도 보정한 자리로), 영역·툴바 크기가 바뀔 때마다 다시 잰다
  useLayoutEffect(() => {
    const el = box.current;
    const area = el?.parentElement;
    if (!a.visible || el === null || area === null || area === undefined) {
      setMeasure(null);
      return;
    }
    const update = () =>
      setMeasure((m) =>
        m !== null && m.area === area.clientWidth && m.width === el.offsetWidth
          ? m
          : { area: area.clientWidth, width: el.offsetWidth },
      );
    update();
    const observer = new ResizeObserver(update);
    observer.observe(area);
    observer.observe(el);
    return () => observer.disconnect();
  }, [a.visible]);

  // 화면 자리 = 기억한 자리를 지금 영역 안으로 들인 값 (기억한 값은 그대로)
  const shown = measure === null ? null : clampX(x, measure.area, measure.width);
  const shownRef = useRef(shown);
  shownRef.current = shown;

  const onPointerDown = useCallback((e: ReactPointerEvent<HTMLSpanElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    // 보정된 자리에서 끌기 시작한다 (기억한 자리로 튀지 않게)
    drag.current = { startX: e.clientX, from: shownRef.current ?? usePosition.getState().x };
  }, []);
  const onPointerMove = useCallback((e: ReactPointerEvent<HTMLSpanElement>) => {
    const d = drag.current;
    const el = box.current;
    if (d === null || el === null) return;
    const area = el.parentElement?.clientWidth ?? 0;
    usePosition.setState({ x: clampX(d.from + e.clientX - d.startX, area, el.offsetWidth) });
  }, []);
  const onPointerUp = useCallback((e: ReactPointerEvent<HTMLSpanElement>) => {
    if (drag.current === null) return;
    drag.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
    void window.kookabug.app.debugToolbarSet(usePosition.getState().x).catch(() => {});
  }, []);

  if (!a.visible) return null;
  const state = a.paused ? "paused" : a.pausing ? "pausing" : a.canRestart ? "running" : "restarting";
  return (
    <div
      ref={box}
      role="toolbar"
      aria-label="실행 제어"
      className={css.toolbar}
      data-part="debug-toolbar"
      data-state={state}
      data-x={x}
      data-shown-x={shown ?? ""}
      style={{ left: `calc(50% + ${shown ?? 0}px)`, visibility: shown === null ? "hidden" : undefined }}
    >
      <span
        className={css.handle}
        aria-hidden="true"
        data-part="debug-toolbar-handle"
        title="끌어서 옮기기"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        ⋮⋮
      </span>
      {a.paused ? (
        <button type="button" aria-label="계속 F5" title="계속 (F5)" className={css.button} onClick={() => resumeRun("continue")}>
          <ContinueIcon />
        </button>
      ) : (
        <button
          type="button"
          aria-label="일시정지 F6"
          title={a.pausing ? "멈추는 중… (다음 노드 경계나 대기 중에 멈춰요)" : "일시정지 (F6)"}
          aria-pressed={a.pausing}
          className={css.button}
          disabled={!a.canPause}
          onClick={pauseRun}
        >
          <PauseIcon />
        </button>
      )}
      <button
        type="button"
        aria-label="다음 노드 F10"
        title="다음 노드 (F10)"
        className={css.button}
        disabled={!a.canStep}
        onClick={() => resumeRun("step_over")}
      >
        <StepOverIcon />
      </button>
      <button
        type="button"
        aria-label="서브그래프로 들어가기 F11"
        title="서브그래프로 들어가기 (F11)"
        className={css.button}
        disabled={!a.canStep}
        onClick={() => resumeRun("step_into")}
      >
        <StepIntoIcon />
      </button>
      <button
        type="button"
        aria-label="서브그래프에서 나오기"
        title="서브그래프에서 나오기 (Shift+F11)"
        className={css.button}
        disabled={!a.canStep}
        onClick={() => resumeRun("step_out")}
      >
        <StepOutIcon />
      </button>
      <button
        type="button"
        aria-label="다시 시작"
        title="다시 시작 (Ctrl+Shift+F5)"
        className={`${css.button} ${css.restart}`}
        disabled={!a.canRestart}
        onClick={restartRun}
      >
        <RestartIcon />
      </button>
      <button
        type="button"
        aria-label="정지"
        title="정지 (Shift+F5)"
        className={`${css.button} ${css.stop}`}
        disabled={!a.canStop}
        onClick={stopRun}
      >
        <StopIcon />
      </button>
    </div>
  );
}
