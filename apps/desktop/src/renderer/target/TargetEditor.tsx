// TARGET 탭 (M2 계획 2.9, T12): 시안 Recorder 오른쪽 영역. 안내 줄(정지 화면 출처·조작 안내·창에서 캡처·
// 이미지에서·저장) → 띠(충돌·실패·저장 결과) → 정지 화면 판 → 매칭 미리보기·클릭 지점 패널.
// 시안의 "여러 개면 좌상단부터"는 target 형식에 없어 그리지 않는다 (U7). "후보 N개" 대신 찾음/못 찾음과
// (최고) 점수를 보인다 (검수 M6)
import { useEffect, useRef, useState } from "react";
import type { daemonRpc } from "@kookabug/schema";
import shell from "../app/shell.module.css";
import { client, toRpcError } from "../rpc/client";
import { ask } from "../store/dialog";
import { useWorkspace } from "../store/workspace";
import { FrameView, useTargetDoc } from "./FrameView";
import { ANCHOR_ORDER, type Anchor } from "./geometry";
import {
  clampThreshold,
  formatOffset,
  setAnchor,
  setMultiscale,
  setOffset,
  setRgb,
  setThreshold,
  specFields,
  THRESHOLD_MAX,
  THRESHOLD_MIN,
} from "./spec";
import css from "./target.module.css";
import {
  captureWindow,
  dismissSaved,
  dismissTargetConflict,
  dismissTargetError,
  editSpec,
  loadImageFrame,
  previewSummary,
  reloadTarget,
  saveBlocker,
  saveTarget,
  targetDirty,
  type FrameOutcome,
  type TargetDoc,
} from "./targetStore";

const ANCHOR_LABELS: Record<Anchor, string> = {
  top_left: "좌상",
  top: "상",
  top_right: "우상",
  left: "좌",
  center: "중앙",
  right: "우",
  bottom_left: "좌하",
  bottom: "하",
  bottom_right: "우하",
};

type WindowInfo = daemonRpc.WindowInfo;

/**
 * 정지 화면 요청 결과를 고르기 창에 보인다: 썼으면 닫고, 실패면 이유를 보이고, 더 새 요청이 있어 버려졌으면
 * 아무것도 하지 않는다 (그 새 요청의 결과가 창을 닫거나 이유를 보인다)
 */
function showOutcome(outcome: FrameOutcome, close: () => void, note: (text: string) => void): void {
  if (outcome.kind === "ok") close();
  else if (outcome.kind === "error") note(outcome.message);
}

function WindowPicker({ path, onClose }: { path: string; onClose(): void }) {
  const [windows, setWindows] = useState<WindowInfo[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    client()
      .call("windows.list", {})
      .then((r) => live && setWindows(r.windows.filter((w) => w.title.trim() !== "")))
      .catch((err: unknown) => live && setNote(`창 목록을 읽지 못했어요: ${toRpcError(err).message}`));
    return () => {
      live = false;
    };
  }, []);
  const pick = async (w: WindowInfo) => {
    setNote("캡처하는 중…");
    showOutcome(await captureWindow(path, w.handle, w.title), onClose, setNote);
  };
  return (
    <div className={css.picker} role="dialog" aria-label="창 고르기" data-part="window-picker">
      {windows === null && note === null && <div className={css.pickerNote}>창 목록을 읽는 중…</div>}
      {windows?.length === 0 && <div className={css.pickerNote}>보이는 창이 없어요</div>}
      {windows?.map((w) => (
        <button key={w.handle} type="button" className={css.pickerItem} data-handle={w.handle} onClick={() => void pick(w)}>
          <span>{w.title}</span>
          <span className={css.pickerSub}>
            {w.process} · {w.client_size[0]}×{w.client_size[1]} · DPI {Math.round((w.dpi / 96) * 100)}%
          </span>
        </button>
      ))}
      {note !== null && <div className={css.pickerNote}>{note}</div>}
    </div>
  );
}

function ImagePicker({ path, onClose }: { path: string; onClose(): void }) {
  const entries = useWorkspace((s) => s.entries);
  const images = entries.filter((e) => e.type === "file" && e.path.toLowerCase().endsWith(".png")).map((e) => e.path);
  const [text, setText] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const open = async (image: string) => {
    setNote(`여는 중… (${image})`);
    showOutcome(await loadImageFrame(path, image), onClose, setNote);
  };
  return (
    <div className={css.picker} role="dialog" aria-label="이미지 고르기" data-part="image-picker">
      {images.length === 0 && <div className={css.pickerNote}>워크스페이스에 PNG가 없어요</div>}
      {images.map((p) => (
        <button key={p} type="button" className={css.pickerItem} data-path={p} onClick={() => void open(p)}>
          <span>{p}</span>
        </button>
      ))}
      <form
        className={css.pickerRow}
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim() !== "") void open(text.trim());
        }}
      >
        <input
          className={css.input}
          aria-label="PNG 경로"
          placeholder="워크스페이스 기준 경로 (예: runs/…/step.png)"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className={css.button}>
          열기
        </button>
      </form>
      {note !== null && <div className={css.pickerNote}>{note}</div>}
    </div>
  );
}

/** 바깥을 누르면 닫히는 고르기 창 */
function usePopover(): [string | null, (v: string | null) => void, React.RefObject<HTMLDivElement | null>] {
  const [open, setOpen] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open === null) return;
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return [open, setOpen, ref];
}

function Toolbar({ doc }: { doc: TargetDoc }) {
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const [open, setOpen, ref] = usePopover();
  const blocked = saveBlocker(doc);
  const dirty = targetDirty(doc);
  const source = doc.frame === null ? (doc.frameExpired ? "정지 화면 없음 (만료)" : "정지 화면 없음") : `정지 화면 · ${doc.frameSource ?? ""}`;
  return (
    <div className={css.toolbar} data-part="target-toolbar">
      <span className={css.source} title={doc.frameSource ?? undefined} data-part="frame-source">
        {source}
      </span>
      <span className={css.hint}>드래그 = 템플릿 영역 · Shift+드래그 = 검색 범위 · 클릭 = 클릭 지점</span>
      <div className={css.spacer} />
      <div className={css.pickerWrap} ref={ref}>
        <span style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className={css.button}
            disabled={!connected}
            aria-expanded={open === "window"}
            onClick={() => setOpen(open === "window" ? null : "window")}
          >
            창에서 캡처
          </button>
          <button
            type="button"
            className={css.button}
            disabled={!connected}
            aria-expanded={open === "image"}
            onClick={() => setOpen(open === "image" ? null : "image")}
          >
            이미지에서
          </button>
        </span>
        {open === "window" && <WindowPicker path={doc.path} onClose={() => setOpen(null)} />}
        {open === "image" && <ImagePicker path={doc.path} onClose={() => setOpen(null)} />}
      </div>
      <button
        type="button"
        className={`${css.button} ${css.primary}`}
        data-part="target-save"
        disabled={!connected || doc.saving || blocked !== null || (!dirty && doc.conflict === null)}
        title={blocked ?? (doc.isNew ? "PNG와 *.target.json을 만들어요" : "Ctrl+S")}
        onClick={() => void saveTarget(doc.path)}
      >
        {doc.saving ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}

function Banners({ doc }: { doc: TargetDoc }) {
  const banners: React.ReactNode[] = [];
  if (doc.conflict !== null) {
    banners.push(
      <div key="conflict" role="alert" aria-label="저장 충돌" data-part="target-conflict" className={`${shell.banner} ${shell.bannerWarn}`}>
        <span className={shell.bannerText}>
          {doc.conflict === "" ? "디스크에서 이 대상 파일이 지워졌어요." : "디스크의 이 대상이 밖에서 바뀌었어요."} 저장하지 않았고 기존 대상
          파일은 그대로예요.
        </span>
        {doc.conflict !== "" && (
          <button type="button" className={shell.bannerButton} onClick={() => void reloadFromDisk(doc)}>
            디스크 버전 다시 열기
          </button>
        )}
        <button type="button" className={shell.bannerButton} onClick={() => void saveTarget(doc.path, { force: true })}>
          내 편집으로 덮어쓰기
        </button>
        <button type="button" className={shell.bannerButton} onClick={() => dismissTargetConflict(doc.path)}>
          닫기
        </button>
      </div>,
    );
  }
  if (doc.saveError !== null) {
    banners.push(
      <div key="error" role="alert" aria-label="저장 실패" data-part="target-save-error" className={`${shell.banner} ${shell.bannerError}`}>
        <span className={shell.bannerText}>{doc.saveError}</span>
        <button type="button" className={shell.bannerButton} onClick={() => dismissTargetError(doc.path)}>
          닫기
        </button>
      </div>,
    );
  }
  if (doc.saved !== null) {
    const p = doc.saved.preview;
    banners.push(
      <div
        key="saved"
        role="status"
        aria-label="저장 결과"
        data-part="target-saved"
        data-found={p === null ? "" : String(p.found)}
        className={`${shell.banner} ${shell.bannerInfo}`}
      >
        <span className={shell.bannerText}>
          저장했어요 ({doc.saved.wroteImage}){p !== null ? ` · 바로 매칭: ${previewSummary(p)}` : ""}
          {doc.saved.warnings.map((w) => (
            <span key={w} className={shell.bannerDetail}>
              {w}
            </span>
          ))}
        </span>
        <button type="button" className={shell.bannerButton} onClick={() => dismissSaved(doc.path)}>
          닫기
        </button>
      </div>,
    );
  }
  if (doc.status === "error" && doc.error !== null) {
    banners.push(
      <div key="open" role="alert" data-part="target-open-error" className={`${shell.banner} ${shell.bannerError}`}>
        <span className={shell.bannerText}>{doc.error}</span>
      </div>,
    );
  }
  const problem = doc.diagnostics.find((d) => d.severity === "error");
  if (problem !== undefined && doc.status === "ready") {
    banners.push(
      <div key="diag" role="status" data-part="target-diagnostic" className={`${shell.banner} ${shell.bannerWarn}`}>
        <span className={shell.bannerText}>
          {problem.pointer ? `${problem.pointer}: ` : ""}
          {problem.message}
        </span>
      </div>,
    );
  }
  return <>{banners}</>;
}

async function reloadFromDisk(doc: TargetDoc): Promise<void> {
  if (targetDirty(doc)) {
    const r = await ask({
      title: "편집을 버리고 디스크 버전을 다시 열까요?",
      message: "고른 영역과 바꾼 설정이 사라져요.",
      buttons: [
        { label: "다시 열기", value: "reload", primary: true },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
    });
    if (r.value !== "reload") return;
  }
  await reloadTarget(doc.path);
}

function PreviewPanel({ doc }: { doc: TargetDoc }) {
  const f = specFields(doc.spec);
  const p = doc.preview;
  let status: React.ReactNode;
  if (p !== null) {
    status = (
      <span className={p.found ? css.found : css.missing} data-part="preview-result" data-found={String(p.found)} data-seq={p.seq}>
        {previewSummary(p)}
      </span>
    );
  } else {
    status = (
      <span className={css.note} data-part="preview-result" data-found="">
        {doc.previewPending ? "찾는 중…" : (doc.previewNote ?? "")}
      </span>
    );
  }
  return (
    <div className={`${css.panel} ${css.previewPanel}`} data-part="preview-panel">
      <div className={css.panelHead}>
        <span className={css.panelTitle}>매칭 미리보기</span>
        {status}
      </div>
      <label className={css.slider}>
        <span className={css.sliderHead}>
          <span>유사도 임계값</span>
          <span className={css.mono} data-part="threshold-value">
            {f.threshold.toFixed(2)}
          </span>
        </span>
        <input
          type="range"
          aria-label="유사도 임계값"
          className={css.range}
          min={THRESHOLD_MIN}
          max={THRESHOLD_MAX}
          step={0.01}
          value={clampThreshold(f.threshold)}
          disabled={doc.status !== "ready"}
          onChange={(e) => editSpec(doc.path, (s) => setThreshold(s, Number(e.target.value)))}
        />
      </label>
      <div className={css.checks}>
        <label className={css.check}>
          <input
            type="checkbox"
            checked={f.rgb}
            disabled={doc.status !== "ready"}
            onChange={(e) => editSpec(doc.path, (s) => setRgb(s, e.target.checked))}
          />
          색까지 확인
        </label>
        <label className={css.check}>
          <input
            type="checkbox"
            checked={f.multiscale}
            disabled={doc.status !== "ready"}
            onChange={(e) => editSpec(doc.path, (s) => setMultiscale(s, e.target.checked, doc.savedSpec))}
          />
          배율 0.8–1.25
        </label>
      </div>
    </div>
  );
}

function OffsetInput({ label, value, onCommit, disabled }: { label: string; value: number; onCommit(v: number): void; disabled: boolean }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const v = Number(draft);
    setDraft(null);
    if (draft.trim() !== "" && Number.isFinite(v) && Math.abs(v) <= 100_000) onCommit(v);
  };
  return (
    <input
      className={css.offsetInput}
      aria-label={label}
      inputMode="decimal"
      value={draft ?? formatOffset(value)}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setDraft(null);
      }}
    />
  );
}

function ClickPanel({ doc }: { doc: TargetDoc }) {
  const f = specFields(doc.spec);
  const disabled = doc.status !== "ready";
  const pickAnchor = (a: Anchor) =>
    editSpec(doc.path, (s) => {
      const next = setAnchor(s, a);
      // 9분할 지점을 고르면 그 지점을 누른다 (오프셋은 0으로)
      return f.offset[0] === 0 && f.offset[1] === 0 ? next : setOffset(next, [0, 0]);
    });
  return (
    <div className={`${css.panel} ${css.clickPanel}`} data-part="click-panel">
      <span className={css.panelTitle}>클릭 지점</span>
      <div className={css.anchors} role="group" aria-label="클릭 지점 9분할">
        {ANCHOR_ORDER.map((a) => (
          <button
            key={a}
            type="button"
            aria-label={ANCHOR_LABELS[a]}
            aria-pressed={f.anchor === a}
            className={css.anchor}
            disabled={disabled}
            data-anchor={a}
            onClick={() => pickAnchor(a)}
          />
        ))}
      </div>
      <span className={css.offset} data-part="offset">
        오프셋 dx
        <OffsetInput label="오프셋 dx" value={f.offset[0]} disabled={disabled} onCommit={(v) => editSpec(doc.path, (s) => setOffset(s, [v, f.offset[1]]))} />
        · dy
        <OffsetInput label="오프셋 dy" value={f.offset[1]} disabled={disabled} onCommit={(v) => editSpec(doc.path, (s) => setOffset(s, [f.offset[0], v]))} />
      </span>
    </div>
  );
}

export function TargetEditor({ path }: { path: string }) {
  const doc = useTargetDoc(path);
  if (doc === undefined) return <div className={css.editor} data-part="target-editor" data-path={path} data-status="loading" />;
  return (
    <div
      className={css.editor}
      data-part="target-editor"
      data-path={path}
      data-status={doc.status}
      data-new={String(doc.isNew)}
      data-dirty={String(targetDirty(doc))}
      data-saves={doc.saves}
      data-revision={doc.baseRevision ?? ""}
    >
      <Toolbar doc={doc} />
      <Banners doc={doc} />
      <div className={css.body}>
        <FrameView doc={doc} />
        <div className={css.panels}>
          <PreviewPanel doc={doc} />
          <ClickPanel doc={doc} />
        </div>
      </div>
    </div>
  );
}
