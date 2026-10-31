// 열린 그래프 문서 표 (M2 계획 2.6·2.7, T8). 탭이 열리면 graph.open, 닫히면 graph.close를 보낸다.
// - 버퍼 값·dirty·base_revision은 렌더러가 갖는다 (조율자 결정 Q2). 열기는 값을 바꾸지 않는다
// - 모양(shapes)·진단은 daemon이 계산한다. 검증은 300 ms 디바운스로 graph.validate를 보내고, 마지막으로
//   보낸 seq의 응답만 쓴다
// - 응답 순서는 가정하지 않는다 (daemon은 요청을 따로 처리한다). 문서를 만들 때마다 인스턴스 번호를 주고,
//   열기·검증 응답은 요청을 낸 그 인스턴스에만 쓴다. 닫았다 다시 연 같은 경로에 앞 응답이 섞이지 않는다
// - doc_id는 연결마다 바뀔 수 있다: 저장·검증·닫기는 항상 지금 표의 doc_id를 쓴다 (T7 인계).
//   daemon은 graph.open마다 그 연결의 참조를 하나 늘리므로 닫을 때 연 횟수(refs)만큼 graph.close를 보낸다.
//   참조는 연결 단위라 refs가 생긴 연결이 지금 연결일 때만 닫는다 (앞 연결의 참조는 daemon이 이미 풀었다)
// - 다시 붙은 뒤 복구는 rpc/recovery.ts가 이 표의 DocHost로 한다
// - 보기 상태(펼친 그룹·선택·뷰포트)는 문서마다 두고 파일에 쓰지 않는다
// - 편집 (T9): 명령(값 → 새 값)마다 실행 취소 기록 하나. dirty = 버퍼가 마지막으로 열거나 저장한 값과 다름.
//   저장은 값 전체 + base_revision (graph.save). 디스크가 바뀌면 충돌 띠 (2.6 "충돌")
import { create } from "zustand";
import { autoLayout } from "../graph/autoLayout";
import { EMPTY_HISTORY, record, redo as redoHistory, undo as undoHistory, type History } from "../graph/history";
import {
  collapsedGroups,
  graphNodes,
  layoutPositions,
  type Diagnostic,
  type GraphValue,
  type NodeShapes,
  type Point,
} from "../graph/model";
import { jsonEqual } from "../graph/valueOps";
import { problemNode } from "../problems/locate";
import { client, toRpcError, type RpcError } from "../rpc/client";
import type { DocHost, GraphOpenResult, OpenDocRef } from "../rpc/recovery";
import { editsLocked } from "./dialog";
import { useTabs } from "./tabs";

/** 충돌 띠의 디스크 revision 자리: 파일이 지워짐 */
export const CONFLICT_DELETED = "deleted";

export interface DocError {
  /** error.data.code (invalid_json·not_found 등). 연결 문제면 not_connected */
  kind: string | null;
  message: string;
  line: number | null;
  column: number | null;
}

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface DocView {
  /** 보기로 펼친 접힌 그룹 */
  expanded: string[];
  /** 주로 고른 노드 (속성 편집기가 보는 노드). selection 안에 있다 */
  selected: string | null;
  /** 고른 노드 전부 (여러 개 고르기·지우기) */
  selection: string[];
  viewport: Viewport | null;
  /** 이 노드로 옮겨 가라는 요청 (nonce가 바뀔 때마다 한 번) */
  focus: { node: string; nonce: number } | null;
  /**
   * 열 때 좌표가 없던 노드의 보기용 자리 (열 때 한 번 정한다). 다른 노드를 더하거나 옮겨도 이 노드들이 다시
   * 배치되어 튀지 않게 한다. 값에는 쓰지 않는다 (2.6 "열기는 값을 바꾸지 않는다")
   */
  auto: ReadonlyMap<string, Point>;
}

export interface GraphDoc {
  path: string;
  /** 표에 넣을 때마다 새 번호 (같은 경로를 닫았다 다시 열면 다르다) */
  instance: number;
  status: "loading" | "ready" | "error";
  docId: string | null;
  /** refsConnection 연결에서 이 문서를 연 횟수 (닫을 때 그만큼 graph.close) */
  refs: number;
  refsConnection: string | null;
  baseRevision: string | null;
  value: GraphValue | null;
  dirty: boolean;
  canonical: boolean;
  diagnostics: Diagnostic[];
  shapes: NodeShapes;
  /** 마지막으로 보낸 graph.validate seq */
  validateSeq: number;
  error: DocError | null;
  /** 편집 중에 디스크가 바뀜 (그 디스크 revision, 지워졌으면 CONFLICT_DELETED). 충돌 띠를 띄운다 */
  conflict: string | null;
  view: DocView;
  /** 마지막으로 열거나 저장한 값 (dirty 기준) */
  savedValue: GraphValue | null;
  history: History;
  saving: boolean;
  /** 마지막 저장 실패 (충돌 말고) */
  saveError: string | null;
  /** 성공한 저장 수 (캔버스 data-saves. 검사가 저장 끝을 기다린다) */
  saves: number;
  /** 버퍼를 바꾼 횟수 (편집·실행 취소·다시 실행). 다시 열기 응답이 그사이 편집을 덮지 않게 본다 */
  edits: number;
  /** 디스크에서 다시 열기 요청 세대. 늦게 온 옛 응답은 버린다 */
  reloadSeq: number;
}

interface DocumentsState {
  docs: ReadonlyMap<string, GraphDoc>;
}

export const useDocuments = create<DocumentsState>(() => ({ docs: new Map() }));

export const VALIDATE_DEBOUNCE_MS = 300;

const timers = new Map<string, ReturnType<typeof setTimeout>>();
let focusNonce = 0;
let nextInstance = 0;
/** 지금 daemon 연결 (start_id·연결 번호). 연결이 없으면 null */
let connection: string | null = null;

/** 주 프로세스의 연결 상태가 바뀔 때 부른다 (store/workspace.ts) */
export function setDocumentsConnection(key: string | null): void {
  connection = key;
}

export function getDoc(path: string): GraphDoc | undefined {
  return useDocuments.getState().docs.get(path);
}

/** 그 인스턴스가 아직 표에 있을 때만 고친다 (instance를 주지 않으면 지금 문서) */
function update(path: string, patch: (doc: GraphDoc) => Partial<GraphDoc> | null, instance?: number): void {
  useDocuments.setState((s) => {
    const doc = s.docs.get(path);
    if (doc === undefined || (instance !== undefined && doc.instance !== instance)) return s;
    const p = patch(doc);
    if (p === null) return s;
    return { docs: new Map(s.docs).set(path, { ...doc, ...p }) };
  });
}

function emptyDoc(path: string): GraphDoc {
  return {
    path,
    instance: ++nextInstance,
    status: "loading",
    docId: null,
    refs: 0,
    refsConnection: null,
    baseRevision: null,
    value: null,
    dirty: false,
    canonical: true,
    diagnostics: [],
    shapes: {},
    validateSeq: 0,
    error: null,
    conflict: null,
    view: { expanded: [], selected: null, selection: [], viewport: null, focus: null, auto: new Map() },
    savedValue: null,
    history: EMPTY_HISTORY,
    saving: false,
    saveError: null,
    saves: 0,
    edits: 0,
    reloadSeq: 0,
  };
}

function errorOf(err: RpcError): DocError {
  const d = (err.data ?? {}) as { message?: unknown; line?: unknown; column?: unknown };
  return {
    kind: err.kind,
    message: typeof d.message === "string" ? d.message : err.message,
    line: typeof d.line === "number" ? d.line : null,
    column: typeof d.column === "number" ? d.column : null,
  };
}

/** 이 열기로 생긴 참조를 센다. 같은 연결·같은 doc_id면 하나 더, 아니면 새로 하나 */
function counted(doc: GraphDoc, docId: string, on: string | null): Partial<GraphDoc> {
  const same = doc.docId === docId && doc.refsConnection === on && on !== null;
  return { docId, refs: same ? doc.refs + 1 : 1, refsConnection: on };
}

/** 열기 결과 전체를 쓴다 (처음 열기·디스크 값으로 다시 열기). 실행 취소 기록은 새로 시작한다 */
function opened(doc: GraphDoc, result: GraphOpenResult, on: string | null): Partial<GraphDoc> {
  const nodes = graphNodes(result.value);
  const ids = new Set(nodes.map((n) => n.id));
  const placed = layoutPositions(result.value);
  const auto = new Map([...autoLayout(nodes, placed)].filter(([id]) => !placed.has(id)));
  const selection = doc.view.selection.filter((id) => ids.has(id));
  return {
    ...counted(doc, result.doc_id, on),
    status: "ready",
    baseRevision: result.revision,
    value: result.value,
    dirty: false,
    canonical: result.canonical,
    diagnostics: result.diagnostics,
    shapes: result.shapes,
    error: null,
    conflict: null,
    savedValue: result.value,
    history: EMPTY_HISTORY,
    saveError: null,
    view: {
      ...doc.view,
      selection,
      selected: doc.view.selected !== null && ids.has(doc.view.selected) ? doc.view.selected : null,
      auto,
    },
  };
}

function sendClose(docId: string, times: number): void {
  for (let i = 0; i < times; i++) void client().call("graph.close", { doc_id: docId }).catch(() => {});
}

/** 쓰지 않을 열기 응답의 참조를 푼다. 그 사이 연결이 바뀌었으면 daemon이 이미 풀었다 */
function releaseUnused(docId: string, on: string | null): void {
  if (on !== null && on === connection) sendClose(docId, 1);
}

export async function openDoc(path: string): Promise<void> {
  if (getDoc(path) !== undefined) return;
  const doc = emptyDoc(path);
  const instance = doc.instance;
  useDocuments.setState((s) => ({ docs: new Map(s.docs).set(path, doc) }));
  const on = connection;
  let result: GraphOpenResult;
  try {
    result = await client().call("graph.open", { path });
  } catch (err) {
    update(path, () => ({ status: "error", error: errorOf(toRpcError(err)) }), instance);
    return;
  }
  // 기다리는 동안 탭이 닫혔거나 닫았다 다시 열렸다: 이 응답은 쓰지 않고 참조만 푼다
  if (getDoc(path)?.instance !== instance) {
    releaseUnused(result.doc_id, on);
    return;
  }
  update(path, (d) => opened(d, result, on), instance);
  applyPendingFocus(path);
}

export function closeDoc(path: string): void {
  const doc = getDoc(path);
  if (doc === undefined) return;
  const timer = timers.get(path);
  if (timer !== undefined) clearTimeout(timer);
  timers.delete(path);
  pendingFocus.delete(path);
  useDocuments.setState((s) => {
    const docs = new Map(s.docs);
    docs.delete(path);
    return { docs };
  });
  if (doc.docId !== null && doc.refsConnection !== null && doc.refsConnection === connection) {
    sendClose(doc.docId, doc.refs);
  }
}

/** 프로젝트가 바뀜: 앞 연결은 이미 놓았으므로 graph.close 없이 비운다 */
export function resetDocuments(): void {
  for (const t of timers.values()) clearTimeout(t);
  timers.clear();
  pendingFocus.clear();
  useDocuments.setState({ docs: new Map() });
}

async function validateNow(path: string): Promise<void> {
  const doc = getDoc(path);
  if (doc === undefined || doc.status !== "ready" || doc.docId === null || doc.value === null) return;
  const seq = doc.validateSeq + 1;
  const docId = doc.docId;
  const instance = doc.instance;
  update(path, () => ({ validateSeq: seq }), instance);
  try {
    const result = await client().call("graph.validate", { doc_id: docId, value: doc.value, seq });
    update(
      path,
      (d) =>
        d.validateSeq !== result.seq || d.docId !== docId
          ? null
          : { diagnostics: result.diagnostics, shapes: result.shapes },
      instance,
    );
  } catch {
    // doc_not_open·끊김: 다시 붙은 뒤 복구가 다시 열고 검증한다
  }
}

/** 편집·디스크 변경 뒤 검증 (디바운스). 마지막 요청의 응답만 쓴다 */
export function requestValidate(path: string, delay = VALIDATE_DEBOUNCE_MS): void {
  const old = timers.get(path);
  if (old !== undefined) clearTimeout(old);
  timers.set(
    path,
    setTimeout(() => {
      timers.delete(path);
      void validateNow(path);
    }, delay),
  );
}

/** 열린 문서 전부 (서브그래프·target 파일이 바뀌면 검증 결과가 달라진다) */
export function revalidateOpenDocs(delay = VALIDATE_DEBOUNCE_MS): void {
  for (const doc of useDocuments.getState().docs.values()) if (doc.status === "ready") requestValidate(doc.path, delay);
}

// ── 보기 상태 ────────────────────────────────────────────────────

/** 바뀌는 것이 없으면 표를 건드리지 않는다 (같은 값으로 다시 그리기를 부르지 않게) */
function setView(path: string, patch: (view: DocView) => Partial<DocView>): void {
  update(path, (doc) => {
    const p = patch(doc.view);
    const keys = Object.keys(p) as (keyof DocView)[];
    if (keys.every((k) => Object.is(p[k], doc.view[k]))) return null;
    return { view: { ...doc.view, ...p } };
  });
}

// ── 편집·실행 취소·저장 (T9) ──────────────────────────────────────

/** 편집할 수 있는 문서 (열렸고 값이 있음) */
function editable(doc: GraphDoc | undefined): doc is GraphDoc & { value: GraphValue } {
  return doc !== undefined && doc.status === "ready" && doc.value !== null;
}

function dirtyOf(doc: GraphDoc, value: GraphValue): boolean {
  return value !== doc.savedValue && !jsonEqual(value, doc.savedValue);
}

/** 값이 바뀐 뒤 고른 노드 중 없어진 것을 뺀다 */
function keepSelection(view: DocView, value: GraphValue, select?: readonly string[]): DocView {
  const ids = new Set(graphNodes(value).map((n) => n.id));
  const selection = (select ?? view.selection).filter((id) => ids.has(id));
  const selected =
    select !== undefined
      ? (selection.at(-1) ?? null)
      : view.selected !== null && ids.has(view.selected)
        ? view.selected
        : (selection.at(-1) ?? null);
  return sameList(selection, view.selection) && selected === view.selected ? view : { ...view, selection, selected };
}

/**
 * 편집 명령 하나를 적용한다. fn이 같은 값을 돌려주면 아무것도 하지 않는다(기록도 없음). 적용하면 실행 취소 기록
 * 하나를 남기고 검증을 요청한다. select를 주면 편집 뒤 그 노드들을 고른다
 */
export function applyEdit(path: string, fn: (value: GraphValue) => GraphValue, select?: readonly string[]): boolean {
  const doc = getDoc(path);
  // 대화 상자·저장하고 닫기 중에는 고치지 않는다 (store/dialog 편집 잠금)
  if (!editable(doc) || editsLocked()) return false;
  const next = fn(doc.value);
  if (next === doc.value) {
    if (select !== undefined) setSelection(path, select);
    return false;
  }
  update(
    path,
    (d) =>
      d.value !== doc.value
        ? null
        : {
            value: next,
            edits: d.edits + 1,
            history: record(d.history, d.value),
            dirty: dirtyOf(d, next),
            view: keepSelection(d.view, next, select),
          },
    doc.instance,
  );
  requestValidate(path);
  return true;
}

function travel(path: string, step: typeof undoHistory): boolean {
  const doc = getDoc(path);
  if (!editable(doc) || editsLocked()) return false;
  const moved = step(doc.history, doc.value);
  if (moved === null) return false;
  update(
    path,
    (d) => ({
      value: moved.value,
      edits: d.edits + 1,
      history: moved.history,
      dirty: dirtyOf(d, moved.value),
      view: keepSelection(d.view, moved.value),
    }),
    doc.instance,
  );
  requestValidate(path);
  return true;
}

export function undoEdit(path: string): boolean {
  return travel(path, undoHistory);
}

export function redoEdit(path: string): boolean {
  return travel(path, redoHistory);
}

export function canUndo(doc: GraphDoc | undefined): boolean {
  return editable(doc) && doc.history.past.length > 0;
}

export function canRedo(doc: GraphDoc | undefined): boolean {
  return editable(doc) && doc.history.future.length > 0;
}

/** 저장 안 된 문서 */
export function dirtyDocs(): GraphDoc[] {
  return [...useDocuments.getState().docs.values()].filter((d) => d.dirty);
}

export type SaveOutcome = "saved" | "unchanged" | "conflict" | "failed" | "busy";

function saveFailure(err: RpcError): string {
  const d = (err.data ?? {}) as { pointer?: unknown; diagnostics?: unknown };
  if (err.kind === "number_not_finite") {
    return `저장하지 못했어요: 유한하지 않은 수(NaN·무한)는 쓸 수 없어요${typeof d.pointer === "string" ? ` (${d.pointer})` : ""}`;
  }
  if (err.kind === "validation_failed" && Array.isArray(d.diagnostics) && d.diagnostics.length > 0) {
    const first = d.diagnostics[0] as { message?: unknown };
    return `저장하지 못했어요: ${typeof first.message === "string" ? first.message : err.message}`;
  }
  if (err.kind === "not_connected") return "저장하지 못했어요: daemon에 연결되어 있지 않아요";
  return `저장하지 못했어요: ${err.message}`;
}

/**
 * 버퍼 값 전체를 저장한다 (graph.save, 2.6). 아무것도 안 바꿨어도 보낸다(daemon이 지금 디스크와 같으면 쓰지
 * 않는다). force는 충돌 띠의 "내 편집으로 덮어쓰기"
 */
export async function saveDoc(path: string, options: { force?: boolean } = {}): Promise<SaveOutcome> {
  const doc = getDoc(path);
  if (!editable(doc) || doc.docId === null || doc.baseRevision === null) return "failed";
  if (doc.saving) return "busy";
  const value = doc.value;
  const instance = doc.instance;
  update(path, () => ({ saving: true }), instance);
  try {
    const result = await client().call("graph.save", {
      doc_id: doc.docId,
      value,
      base_revision: doc.baseRevision,
      ...(options.force === true ? { force: true } : {}),
    });
    update(
      path,
      (d) => ({
        saving: false,
        saves: d.saves + 1,
        baseRevision: result.revision,
        savedValue: value,
        dirty: d.value === null ? false : d.value !== value && !jsonEqual(d.value, value),
        conflict: null,
        saveError: null,
        ...(result.canonicalized ? { canonical: true } : {}),
        ...(d.value === value ? { diagnostics: result.diagnostics } : {}),
      }),
      instance,
    );
    // 서브그래프를 저장하면 그것을 부르는 다른 문서의 검증 결과가 바뀐다
    revalidateOpenDocs();
    return result.wrote ? "saved" : "unchanged";
  } catch (err) {
    const error = toRpcError(err);
    if (error.kind === "revision_conflict") {
      const disk = (error.data as { revision?: unknown } | undefined)?.revision;
      update(
        path,
        () => ({ saving: false, conflict: typeof disk === "string" ? disk : CONFLICT_DELETED, saveError: null }),
        instance,
      );
      return "conflict";
    }
    update(path, () => ({ saving: false, saveError: saveFailure(error) }), instance);
    return "failed";
  }
}

/** 다시 열기 응답이 왔는데 요청 뒤에 버퍼가 바뀌었다: 버퍼·기록은 두고 새 doc_id에 붙인 뒤 충돌로 본다 */
function keepEditsOnReload(doc: GraphDoc, result: GraphOpenResult, on: string | null): Partial<GraphDoc> {
  return {
    ...counted(doc, result.doc_id, on),
    status: "ready",
    error: null,
    conflict: result.revision === doc.baseRevision ? doc.conflict : result.revision,
  };
}

/**
 * 디스크 값으로 다시 연다 (편집·실행 취소 기록을 버린다). 요청한 때의 버퍼만 버린다: 응답을 기다리는 동안
 * 편집이 생겼으면 그 편집과 기록을 두고 충돌 띠로 바꾼다. 더 새 다시 열기 요청이 있으면 이 응답은 버린다
 * (T9 검수 1차: 응답 역전·대기 중 편집 유실)
 */
export async function reloadDoc(path: string): Promise<void> {
  const doc = getDoc(path);
  if (doc === undefined) return;
  const instance = doc.instance;
  const seq = doc.reloadSeq + 1;
  const edits = doc.edits;
  const on = connection;
  update(path, () => ({ reloadSeq: seq }), instance);
  const current = () => {
    const d = getDoc(path);
    return d !== undefined && d.instance === instance && d.reloadSeq === seq ? d : undefined;
  };
  let result: GraphOpenResult;
  try {
    result = await client().call("graph.open", { path });
  } catch (err) {
    const d = current();
    if (d !== undefined && d.edits === edits) update(path, () => ({ status: "error", error: errorOf(toRpcError(err)) }), instance);
    return;
  }
  const d = current();
  if (d === undefined) {
    releaseUnused(result.doc_id, on);
    return;
  }
  update(path, (x) => (x.edits === edits ? opened(x, result, on) : keepEditsOnReload(x, result, on)), instance);
  applyPendingFocus(path);
}

/** 충돌 띠 닫기: 버퍼·base_revision은 그대로라 저장하면 다시 충돌한다 */
export function dismissConflict(path: string): void {
  update(path, () => ({ conflict: null }));
}

export function dismissSaveError(path: string): void {
  update(path, () => ({ saveError: null }));
}

/**
 * 열린 문서의 디스크가 바뀜 (graph.changed). 편집하지 않은 문서는 조용히 다시 열고(2.6 "외부 변경, dirty
 * 아님"), 편집 중이면 충돌 띠를 띄운다
 */
export function onGraphChanged(docId: string, revision: string | null): void {
  const doc = [...useDocuments.getState().docs.values()].find((d) => d.docId === docId);
  if (doc === undefined || doc.status !== "ready") return;
  if (revision !== null && revision === doc.baseRevision) {
    if (doc.conflict !== null) update(doc.path, () => ({ conflict: null }), doc.instance);
    return;
  }
  if (!doc.dirty && revision !== null) {
    void reloadDoc(doc.path);
    return;
  }
  update(doc.path, () => ({ conflict: revision ?? CONFLICT_DELETED }), doc.instance);
}

/** graph.create 결과를 문서 표에 넣는다 (그 연결의 참조 하나). 탭은 부르는 쪽이 연다 */
export function adoptCreated(path: string, result: GraphOpenResult): void {
  const old = getDoc(path);
  if (old !== undefined) {
    releaseUnused(result.doc_id, connection);
    return;
  }
  const doc = emptyDoc(path);
  useDocuments.setState((s) => ({ docs: new Map(s.docs).set(path, { ...doc, ...opened(doc, result, connection) }) }));
}

export function selectNode(path: string, node: string | null): void {
  setSelection(path, node === null ? [] : [node]);
}

function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

/** 고른 노드 전부를 바꾼다. 주 노드는 남아 있으면 그대로, 아니면 목록의 마지막 */
export function setSelection(path: string, ids: readonly string[]): void {
  setView(path, (v) => {
    const selection = [...new Set(ids)];
    const selected = v.selected !== null && selection.includes(v.selected) ? v.selected : (selection.at(-1) ?? null);
    return {
      ...(sameList(selection, v.selection) ? {} : { selection }),
      ...(selected === v.selected ? {} : { selected }),
    };
  });
}

export function toggleGroup(path: string, group: string): void {
  setView(path, (v) => ({
    expanded: v.expanded.includes(group) ? v.expanded.filter((g) => g !== group) : [...v.expanded, group],
  }));
}

export function saveViewport(path: string, viewport: Viewport): void {
  setView(path, () => ({ viewport }));
}

/** 그 노드를 고르고 화면을 옮긴다. 접힌 그룹 안이면 그 그룹을 보기로 펼친다 */
export function focusNode(path: string, node: string): boolean {
  const doc = getDoc(path);
  if (doc === undefined || doc.value === null) return false;
  const ids = new Set(graphNodes(doc.value).map((n) => n.id));
  if (!ids.has(node)) return false;
  const groups = collapsedGroups(doc.value, ids)
    .filter((g) => g.nodes.includes(node))
    .map((g) => g.id);
  setView(path, (v) => ({
    expanded: [...v.expanded, ...groups.filter((g) => !v.expanded.includes(g))],
    selected: node,
    selection: [node],
    focus: { node, nonce: ++focusNonce },
  }));
  return true;
}

/** 다른 파일의 진단이 가리키는 노드 (진단의 node·pointer 그대로) */
export interface FocusTarget {
  node?: string | null;
  pointer?: string | null;
}

/** 열리고 있는 문서에 옮겨 갈 노드. 문서가 준비되면 한 번 적용한다 */
const pendingFocus = new Map<string, FocusTarget>();

function resolveFocus(path: string, target: FocusTarget): string | null {
  const doc = getDoc(path);
  if (doc === undefined || doc.value === null) return null;
  const ids = new Set(graphNodes(doc.value).map((n) => n.id));
  return problemNode(
    { severity: "error", code: "", message: "", file: path, node: target.node ?? null, pointer: target.pointer ?? null },
    path,
    ids,
  );
}

function applyPendingFocus(path: string): void {
  const target = pendingFocus.get(path);
  const doc = getDoc(path);
  if (target === undefined || doc === undefined || doc.status !== "ready") return;
  pendingFocus.delete(path);
  const node = resolveFocus(path, target);
  if (node !== null) focusNode(path, node);
}

/**
 * 그 문서의 노드(진단의 node 또는 pointer)로 옮겨 간다. 문서가 아직 열리는 중이면 준비된 뒤 적용한다.
 * 탭 열기·고르기는 부르는 쪽이 한다
 */
export function requestFocus(path: string, target: FocusTarget): void {
  pendingFocus.set(path, target);
  applyPendingFocus(path);
}

// ── 다시 붙은 뒤 복구 (rpc/recovery.ts) ─────────────────────────────

export const documentsHost: DocHost = {
  docs(): OpenDocRef[] {
    return [...useDocuments.getState().docs.values()].map((d) => ({
      path: d.path,
      baseRevision: d.baseRevision,
      dirty: d.dirty,
    }));
  },
  rebind(path, result) {
    // 버퍼는 그대로 두고 새 doc_id에 붙인다. 앞 연결에서 다시 열기에 실패해 오류였어도 이제 열렸다
    // 앞 연결에서 보낸 다시 열기 응답은 이제 쓰지 않는다 (reloadSeq를 올린다)
    update(path, (doc) => ({
      ...(doc.value === null
        ? opened(doc, result, connection)
        : { ...counted(doc, result.doc_id, connection), status: "ready" as const, error: null }),
      reloadSeq: doc.reloadSeq + 1,
    }));
    applyPendingFocus(path);
  },
  conflict(path, diskRevision) {
    update(path, () => ({ conflict: diskRevision }));
  },
  reload(path, result) {
    // 복구가 clean으로 본 뒤 다시 여는 사이에 편집이 생겼으면 버퍼를 두고 충돌로 본다
    update(path, (doc) => ({
      ...(doc.dirty ? keepEditsOnReload(doc, result, connection) : opened(doc, result, connection)),
      reloadSeq: doc.reloadSeq + 1,
    }));
    applyPendingFocus(path);
  },
  failed(path, error) {
    update(path, (doc) => ({
      status: "error",
      docId: null,
      refs: 0,
      refsConnection: null,
      error: errorOf(error),
      reloadSeq: doc.reloadSeq + 1,
    }));
  },
  validateAll() {
    revalidateOpenDocs(0);
  },
};

// 탭이 열리고 닫히는 것을 따라 문서를 열고 닫는다
useTabs.subscribe((state) => {
  const graphTabs = new Set(state.tabs.filter((t) => t.kind === "graph").map((t) => t.path));
  for (const path of graphTabs) if (getDoc(path) === undefined) void openDoc(path);
  for (const path of useDocuments.getState().docs.keys()) if (!graphTabs.has(path)) closeDoc(path);
});
