// TARGET 탭 (M2 계획 2.9, T12): 시안 Recorder 오른쪽 영역. 안내 줄(정지 화면 출처·조작 안내·창에서 캡처·
// 이미지에서·저장) → 띠(충돌·실패·저장 결과) → 정지 화면 판 → 매칭 미리보기·클릭 지점 패널.
// 시안의 "여러 개면 좌상단부터"는 target 형식에 없어 그리지 않는다 (U7). 찾음/못 찾음과 (최고) 점수, 찾았으면
// 같은 사양으로 임계값을 넘는 서로 다른 자리 수("같은 모양 N곳", M4 T11)를 보인다
// M4 T11: 판·패널은 TargetEditorBody 하나이고 문서는 어댑터(adapter.ts)로 받는다 — 파일 target(이 탭)과
// 녹화 초안(REC 탭, T10)이 같이 쓴다. 더한 것(U14): 민감 대상, 색 허용치, 같은 모양 N곳·점선 상자, 검색 범위
// 숫자·지우기, 글자 읽기(target.read_text), 접힌 "다른 배율에서"(target.preview scales)
import { useEffect, useRef, useState } from "react";
import type { daemonRpc } from "@kookabug/schema";
import shell from "../app/shell.module.css";
import { client, toRpcError } from "../rpc/client";
import { ask } from "../store/dialog";
import { useWorkspace } from "../store/workspace";
import { fileTargetAdapter, type TargetDocAdapter, type TargetEditorView } from "./adapter";
import { FrameView, useTargetDoc } from "./FrameView";
import { ANCHOR_ORDER, clientToImageRect, normalizedToPixels, type Anchor, type Rect, type Size } from "./geometry";
import {
  clampColorTolerance,
  clampThreshold,
  COLOR_TOLERANCE_MAX,
  editRegion,
  formatOffset,
  setAnchor,
  setColorTolerance,
  setMultiscale,
  setOffset,
  setRegion,
  setRgb,
  setSensitive,
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
  loadImageFrame,
  PREVIEW_DEBOUNCE_MS,
  previewSummary,
  reloadTarget,
  sameShapeCount,
  saveBlocker,
  saveTarget,
  targetDirty,
  type FrameOutcome,
  type PreviewResult,
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

type Body = { doc: TargetEditorView; adapter: TargetDocAdapter };

/** 숫자 칸: 입력 중에는 글을 두고 Enter·포커스 잃음에 반영한다 (Escape는 되돌림) */
function NumberInput({
  label,
  value,
  format,
  onCommit,
  disabled,
  className,
}: {
  label: string;
  value: number;
  format(v: number): string;
  onCommit(v: number): void;
  disabled: boolean;
  className: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const v = Number(draft);
    setDraft(null);
    if (draft.trim() !== "" && Number.isFinite(v)) onCommit(v);
  };
  return (
    <input
      className={className}
      aria-label={label}
      inputMode="decimal"
      value={draft ?? format(value)}
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

function PreviewPanel({ doc, adapter }: Body) {
  const f = specFields(doc.spec);
  const p = doc.preview;
  const disabled = doc.status !== "ready";
  let status: React.ReactNode;
  if (p !== null) {
    const same = sameShapeCount(p);
    status = (
      <span className={p.found ? css.found : css.missing} data-part="preview-result" data-found={String(p.found)} data-seq={p.seq}>
        {previewSummary(p)}
        {same !== null && same > 1 && (
          <span
            className={css.peaks}
            data-part="same-shape"
            data-count={same}
            title="같은 모양이 여러 곳이면 다른 자리를 누를 수 있어요. 검색 범위를 좁히세요"
          >
            {` · 같은 모양 ${same}곳`}
          </span>
        )}
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
          disabled={disabled}
          onChange={(e) => adapter.editSpec((s) => setThreshold(s, Number(e.target.value)))}
        />
      </label>
      <div className={css.checks}>
        <label className={css.check}>
          <input type="checkbox" checked={f.rgb} disabled={disabled} onChange={(e) => adapter.editSpec((s) => setRgb(s, e.target.checked))} />
          색까지 확인
        </label>
        <span className={css.check} title={`찾은 자리와 이미지의 채널별 평균 차이 상한 (0~${COLOR_TOLERANCE_MAX})`}>
          허용치
          <NumberInput
            label="색 허용치"
            className={css.toleranceInput}
            value={f.colorTolerance}
            format={(v) => String(v)}
            disabled={disabled || !f.rgb}
            onCommit={(v) => adapter.editSpec((s) => setColorTolerance(s, clampColorTolerance(v)))}
          />
        </span>
        <label className={css.check}>
          <input
            type="checkbox"
            checked={f.multiscale}
            disabled={disabled}
            onChange={(e) => adapter.editSpec((s) => setMultiscale(s, e.target.checked, doc.savedSpec))}
          />
          배율 0.8–1.25
        </label>
        {/* 판을 넓게 두려고 한 줄에 넣는다. 설명은 툴팁 (B4 검수 Mid 3·Low 1) */}
        <label className={css.check} title={SENSITIVE_TIP}>
          <input
            type="checkbox"
            aria-label="민감 대상"
            data-part="sensitive"
            checked={f.sensitive}
            disabled={disabled}
            onChange={(e) => adapter.editSpec((s) => setSensitive(s, e.target.checked, doc.savedSpec))}
          />
          민감 대상
        </label>
      </div>
    </div>
  );
}

/** 사양에 적힌 클라이언트 크기 (정지 화면이 있으면 그것, 아니면 recorded) */
function clientSizeOf(doc: TargetEditorView): Size | null {
  if (doc.frame !== null) return doc.frame.client_size as Size;
  const size = (doc.spec.recorded as { client_size?: unknown } | undefined)?.client_size;
  return Array.isArray(size) && size.length === 2 && size.every((v) => typeof v === "number") ? (size as Size) : null;
}

const REGION_FIELDS = [
  [0, "x"],
  [1, "y"],
  [2, "w"],
  [3, "h"],
] as const;

function SearchPanel({ doc, adapter }: Body) {
  const f = specFields(doc.spec);
  const disabled = doc.status !== "ready";
  const client = clientSizeOf(doc);
  const shown = f.region ?? [0, 0, 1, 1];
  const px = client === null ? null : normalizedToPixels(shown, client);
  return (
    <div className={`${css.panel} ${css.searchPanel}`} data-part="search-panel">
      <div className={css.panelHead}>
        <span className={css.panelTitle}>검색 범위</span>
        <button
          type="button"
          className={`${css.button} ${css.small}`}
          data-part="clear-search"
          disabled={disabled || f.region === null}
          onClick={() => adapter.editSpec((s) => setRegion(s, null))}
        >
          검색 범위 지우기
        </button>
      </div>
      <div className={css.regionRow}>
        {REGION_FIELDS.map(([i, name]) => (
          <span key={name} className={css.check}>
            {name}
            <NumberInput
              label={`검색 범위 ${name}`}
              className={css.regionInput}
              value={shown[i]}
              format={(v) => String(Math.round(v * 10000) / 10000)}
              disabled={disabled}
              onCommit={(v) => {
                const next = editRegion(f.region, i, v);
                if (next !== null) adapter.editSpec((s) => setRegion(s, next));
              }}
            />
          </span>
        ))}
      </div>
      <span className={css.note} data-part="search-pixels" data-region={f.region === null ? "" : f.region.join(",")}>
        {f.region === null ? "화면 전체" : "정규화 (클라이언트 기준)"}
        {px !== null ? ` · 픽셀 ${px[0]}, ${px[1]} · ${px[2]}×${px[3]}` : ""}
      </span>
    </div>
  );
}

/** 글자를 읽을 영역 (정지 화면 픽셀): 새로 고른 영역, 아니면 찾은 상자 */
function readRect(doc: TargetEditorView): Rect | null {
  if (doc.template !== null) return doc.template;
  const m = doc.preview?.found === true ? doc.preview.match : null;
  if (m === null || m === undefined || doc.frame === null) return null;
  return clientToImageRect(m.rect as Rect, [doc.frame.width, doc.frame.height], doc.frame.client_size as Size);
}

function TextPanel({ doc }: Body) {
  const [state, setState] = useState<{ key: string; text: string; tone: "ok" | "note" } | null>(null);
  const rect = readRect(doc);
  const frameId = doc.frame?.frame_id ?? null;
  const key = `${frameId ?? ""}|${rect?.join(",") ?? ""}`;
  const shown = state !== null && state.key === key ? state : null;
  const read = async () => {
    if (frameId === null || rect === null) return;
    setState({ key, text: "읽는 중…", tone: "note" });
    try {
      const r = await client().call("target.read_text", { frame_id: frameId, rect: [...rect] });
      setState({ key, text: r.text === "" ? "(글자 없음)" : r.text, tone: "ok" });
    } catch (err) {
      const e = toRpcError(err);
      const text = e.kind === "secret_region_overlap" ? "비밀값 칸과 겹쳐 읽지 않았어요" : `읽지 못했어요: ${e.message}`;
      setState({ key, text, tone: "note" });
    }
  };
  return (
    <div className={`${css.panel} ${css.textPanel}`} data-part="text-panel">
      <div className={css.panelHead}>
        <span className={css.panelTitle}>영역 글자</span>
        <button
          type="button"
          className={`${css.button} ${css.small}`}
          data-part="read-text"
          disabled={doc.status !== "ready" || frameId === null || rect === null}
          title="고른 영역(없으면 찾은 상자)의 글자를 읽어요 — 글자 읽기·글자 확인 노드의 영역"
          onClick={() => void read()}
        >
          글자 읽기
        </button>
      </div>
      <span className={shown?.tone === "ok" ? css.textResult : css.note} data-part="read-text-result">
        {shown?.text ?? (rect === null ? "영역을 고르거나 찾은 뒤 읽어요" : "")}
      </span>
    </div>
  );
}

export const OTHER_SCALES = [1.0, 1.25, 1.5, 2.0] as const;
let scaleSeq = 0;

/** 보간으로 키운 화면 점수의 한계 (B4 검수 Mid 1: 실제 게임은 DPI가 바뀌면 다시 그려 점수가 더 낮을 수 있다) */
export const SCALE_NOTE = "화면을 키워 계산한 값이에요 — 실제 DPI 변경은 더 낮을 수 있어요";

/** 민감 대상 툴팁 (B4 검수 Low 1: 기록 가림은 워크스페이스 record.redact_secrets를 따른다 — D3) */
export const SENSITIVE_TIP = "OCR 결과를 비밀값으로 취급해요. 기록 가림은 워크스페이스 설정을 따라요";

/** "다른 배율에서": 정지 화면을 1.25·1.5·2.0배로 바꿔 같은 사양으로 찾은 점수 (D2를 target마다 미리 본다). 보조 패널을 펼쳤을 때만 그린다 */
function ScalePanel({ doc, adapter }: Body) {
  const [rows, setRows] = useState<{ key: string; rows: NonNullable<PreviewResult["scale_scores"]> | string } | null>(null);
  const threshold = specFields(doc.spec).threshold;
  const request = adapter.previewRequest(doc);
  const key = "params" in request ? JSON.stringify(request.params) : "";
  useEffect(() => {
    if (key === "" || !("params" in request)) return;
    let live = true;
    // 슬라이더를 끄는 동안 요청이 쌓이지 않게 미리보기와 같은 디바운스
    const timer = setTimeout(() => {
      const seq = ++scaleSeq;
      client()
        .call("target.preview", { ...request.params, seq, scales: [...OTHER_SCALES] })
        .then((r) => live && setRows({ key, rows: r.scale_scores ?? [] }))
        .catch((err: unknown) => live && setRows({ key, rows: `계산하지 못했어요: ${toRpcError(err).message}` }));
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // key가 요청 전체를 대신한다 (같은 요청이면 다시 보내지 않는다)
  }, [key]);
  const shown = rows !== null && rows.key === key ? rows.rows : null;
  return (
    <div className={`${css.panel} ${css.scales}`} data-part="scale-panel">
      <span className={css.panelTitle}>다른 배율에서</span>
      {key === "" &&<span className={css.note}>영역을 고르거나 찾은 뒤 계산해요</span>}
      {key !== "" && shown === null && <span className={css.note}>계산 중…</span>}
      {typeof shown === "string" && <span className={css.note}>{shown}</span>}
      {Array.isArray(shown) && (
        <table className={css.scaleTable} data-part="scale-table">
          <thead>
            <tr>
              <th>화면 배율</th>
              <th>점수</th>
              <th>결과</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const low = r.score === null || r.score < threshold;
              return (
                <tr key={r.factor} data-factor={r.factor} data-score={r.score ?? ""} className={low ? css.scaleLow : undefined}>
                  <td className={css.mono}>{r.factor.toFixed(2)}배</td>
                  <td className={css.mono}>{r.score === null ? "—" : r.score.toFixed(2)}</td>
                  <td>{r.found ? "찾음" : "못 찾음"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <span className={css.note} data-part="scale-note">
        {SCALE_NOTE}
      </span>
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

function ClickPanel({ doc, adapter }: Body) {
  const f = specFields(doc.spec);
  const disabled = doc.status !== "ready";
  const pickAnchor = (a: Anchor) =>
    adapter.editSpec((s) => {
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
        <OffsetInput label="오프셋 dx" value={f.offset[0]} disabled={disabled} onCommit={(v) => adapter.editSpec((s) => setOffset(s, [v, f.offset[1]]))} />
        · dy
        <OffsetInput label="오프셋 dy" value={f.offset[1]} disabled={disabled} onCommit={(v) => adapter.editSpec((s) => setOffset(s, [f.offset[0], v]))} />
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
      <TargetEditorBody doc={doc} adapter={fileTargetAdapter(path)} />
    </div>
  );
}

/** 편집기 부품 (정지 화면 판 + 패널). 파일 target·녹화 초안이 같이 쓴다 (문서 어댑터, M4 T11) */
export function TargetEditorBody({ doc, adapter }: Body) {
  return (
    <div className={css.body}>
      <FrameView doc={doc} adapter={adapter} />
      <div className={css.panels}>
        <PreviewPanel doc={doc} adapter={adapter} />
        <ClickPanel doc={doc} adapter={adapter} />
      </div>
      <ExtPanels doc={doc} adapter={adapter} />
    </div>
  );
}

/** 보조 패널 열림 (탭을 오가도 이 세션 동안 기억한다) */
let extOpen = false;

/**
 * 시안에 없는 보조 패널(U14: 검색 범위 숫자·영역 글자·다른 배율)은 한 줄로 접어 둔다. 하단 출력 패널이 열린
 * 1440×900에서도 정지 화면 판과 기본 조작부(미리보기·클릭 지점)가 스크롤 없이 같이 보이게 한다 (B4 검수 Mid 3).
 * 펼쳤을 때만 그리므로 다른 배율 점수도 펼쳤을 때만 계산한다
 */
function ExtPanels({ doc, adapter }: Body) {
  const [open, setOpen] = useState(extOpen);
  const f = specFields(doc.spec);
  return (
    <details
      className={css.ext}
      data-part="ext-panels"
      open={open}
      onToggle={(e) => {
        extOpen = (e.currentTarget as HTMLDetailsElement).open;
        setOpen(extOpen);
      }}
    >
      <summary className={css.extSummary} data-part="ext-summary">
        <span>검색 범위 · 영역 글자 · 다른 배율에서</span>
        <span className={css.note}>{f.region === null ? "검색 범위: 화면 전체" : "검색 범위 있음"}</span>
      </summary>
      {open && (
        <div className={css.panels}>
          <SearchPanel doc={doc} adapter={adapter} />
          <TextPanel doc={doc} adapter={adapter} />
          <ScalePanel doc={doc} adapter={adapter} />
        </div>
      )}
    </details>
  );
}
