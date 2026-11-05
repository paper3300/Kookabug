// 녹화 커밋 (M4 계획 2.9 "커밋은 두 단계", T10): commit_prepare(검사·target 쓰기·조각) → 렌더러가 그래프를 만들고
// 저장(insertFragment + applyEdit 한 번) → commit_finish. 그래프 단계가 실패하면 commit_abort → 다른 이름·위치로
// 다시 (써진 target 재사용, 재녹화 없음).
// - 새 테스트로 저장: 이름 묻기 → tests/<이름>.graph.json → graph.create(test) → 시작 노드 뒤에 조각 → 저장
// - 커서 위치에 노드로 삽입: 열린 그래프 탭의 고른 노드의 ok 출구 뒤 (여럿이면 묻는다, 종료 노드는 거부).
//   저장이 실패하면 넣은 편집을 되돌린다(같은 녹화를 다시 넣을 때 두 번 들어가지 않게)
// 사용자 파일 손상 엄격: 그래프 값은 insertFragment가 바뀐 경로만 바꾸고, 실행 취소 한 번으로 넣기 전으로 돌아간다
import { insertExits, insertFragment, FragmentInsertError, type Fragment } from "../graph/commands/fragment";
import { graphNodes, isObject, own, type GraphValue } from "../graph/model";
import { client, toRpcError } from "../rpc/client";
import { ask, lockEdits, setDialogError } from "../store/dialog";
import { adoptCreated, applySystemEdit, getDoc, saveDoc, undoSystemEdit } from "../store/documents";
import { checkGraphName, newGraphPath } from "../store/newGraph";
import { activateTab, closeTab, openTab, REC_TAB_PATH, useTabs } from "../store/tabs";
import { refreshTree } from "../store/workspace";
import { recorderErrorText } from "./labels";
import { refreshState, useRecorder } from "./recorderStore";

type Prepared = { fragment: Fragment; token: string };

function notice(text: string, steps: string[] = []): void {
  useRecorder.setState({ notice: { tone: "error", text, steps } });
}

function failed(err: unknown, prefix: string): void {
  const e = toRpcError(err);
  const data = e.data as { steps?: unknown } | undefined;
  const steps = Array.isArray(data?.steps) ? data.steps.filter((x): x is string => typeof x === "string") : [];
  notice(`${prefix}${recorderErrorText(e.kind, e.message)}`, steps);
}

async function prepare(mode: "new_test" | "insert", graphPath: string, baseRevision?: string | null): Promise<Prepared | null> {
  try {
    const r = await client().call("recorder.commit_prepare", {
      mode,
      graph_path: graphPath,
      options: useRecorder.getState().options,
      ...(baseRevision === undefined ? {} : { base_revision: baseRevision }),
    });
    return { fragment: r.fragment, token: r.token };
  } catch (err) {
    failed(err, "저장하지 못했어요: ");
    await refreshState();
    return null;
  }
}

async function abort(token: string): Promise<void> {
  try {
    await client().call("recorder.commit_abort", { token });
  } catch {
    // 세션이 이미 끝남 (연결 끊김 등): 상태 알림이 정리한다
  }
  await refreshState();
}

async function finish(token: string, graphPath: string, warnings: string[]): Promise<void> {
  try {
    await client().call("recorder.commit_finish", { token, graph_path: graphPath });
  } catch (err) {
    failed(err, "녹화를 마무리하지 못했어요: ");
  }
  useRecorder.setState({ committed: { graph: graphPath, warnings } });
  closeTab(REC_TAB_PATH);
  activateTab(graphPath);
  await refreshState();
}

function entryNode(value: GraphValue | null): string | null {
  if (value === null) return null;
  return graphNodes(value).find((n) => n.type === "core.graph.entry")?.id ?? null;
}

/** 조각을 열린 문서에 넣는다 (편집 한 번 = 실행 취소 한 번). 넣은 값 (못 넣으면 null, 띠에 이유) */
function applyFragment(path: string, fragment: Fragment, options: Parameters<typeof insertFragment>[2]): GraphValue | null {
  let produced: GraphValue | null = null;
  let error: string | null = null;
  // 사용자 편집 잠금 중(insertAndSave)이라 앱 편집으로 넣는다
  const ok = applySystemEdit(path, (value) => {
    try {
      const r = insertFragment(value, fragment, options);
      produced = r.value;
      return r.value;
    } catch (err) {
      error = err instanceof FragmentInsertError ? err.message : String(err);
      return value;
    }
  });
  if (!ok || produced === null) {
    notice(error ?? "그래프에 넣지 못했어요 (편집할 수 없는 문서예요)");
    return null;
  }
  return produced;
}

export const STUCK_TEXT =
  "녹화한 노드가 그래프에 들어간 채 저장하지 못했어요. 그래프 탭에서 확인하고 저장하세요 — 같은 녹화를 다시 넣지 않아요";

/**
 * 넣기 → 저장 → (실패면) 되돌리기를 사용자 편집 잠금 안에서 한다 (B5 검수 H1): 저장을 기다리는 동안 사용자 편집이
 * 끼어 되돌리기를 못 하고 재삽입으로 녹화가 두 번 들어가는 일을 막는다.
 * - saved: 저장됨 / failed: 넣지 못함(값 그대로) / reverted: 저장 실패, 넣은 편집을 되돌림(다시 넣어도 됨)
 * - stuck: 저장 실패, 되돌리지 못함(문서가 닫히거나 다시 열림) — 다시 넣지 않는다
 */
async function insertAndSave(
  path: string,
  fragment: Fragment,
  options: Parameters<typeof insertFragment>[2],
): Promise<"saved" | "failed" | "reverted" | "stuck"> {
  const unlock = lockEdits();
  try {
    const produced = applyFragment(path, fragment, options);
    if (produced === null) return "failed";
    const outcome = await saveDoc(path);
    if (outcome === "saved" || outcome === "unchanged") return "saved";
    if (getDoc(path)?.value === produced && undoSystemEdit(path)) {
      notice(outcome === "conflict" ? "그래프 파일이 밖에서 바뀌어 저장하지 못했어요. 다시 넣으세요" : "그래프를 저장하지 못했어요. 다시 넣으세요");
      return "reverted";
    }
    useRecorder.setState({ retryBlocked: true });
    notice(STUCK_TEXT);
    return "stuck";
  } finally {
    unlock();
  }
}

/** 되돌리지 못한 삽입이 있으면 다시 넣지 않는다 */
function retryBlocked(): boolean {
  if (!useRecorder.getState().retryBlocked) return false;
  notice(STUCK_TEXT);
  return true;
}

function warningTexts(fragment: Fragment): string[] {
  return fragment.warnings.map((w) => w.message);
}

/** "새 테스트로 저장" */
export async function commitNewTest(): Promise<boolean> {
  if (useRecorder.getState().busy !== null || retryBlocked()) return false;
  let text = "";
  for (;;) {
    const r = await ask({
      title: "새 테스트로 저장",
      input: { label: "이름", value: text, placeholder: "예: 로그인_녹화" },
      buttons: [
        { label: "저장", value: "save", primary: true },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
      check: checkGraphName,
    });
    if (r.value !== "save") return false;
    text = r.text;
    const path = newGraphPath("test", text);
    useRecorder.setState({ busy: "commit", notice: null });
    try {
      const outcome = await commitNewTestAt(path, text.trim());
      if (outcome === "exists") {
        // 같은 이름 파일: commit_abort 뒤 다른 이름으로 (재녹화 없음, 써진 target 재사용 — 검수 M5)
        queueMicrotask(() => setDialogError(`'${path}'이(가) 이미 있어요. 다른 이름을 적으세요`));
        continue;
      }
      return outcome === "done";
    } finally {
      useRecorder.setState({ busy: null });
    }
  }
}

async function commitNewTestAt(path: string, title: string): Promise<"done" | "exists" | "failed"> {
  const prepared = await prepare("new_test", path);
  if (prepared === null) return "failed";
  let created;
  try {
    created = await client().call("graph.create", { path, kind: "test", title });
  } catch (err) {
    await abort(prepared.token);
    if (toRpcError(err).kind === "exists") return "exists";
    failed(err, "테스트 파일을 만들지 못했어요: ");
    return "failed";
  }
  adoptCreated(path, created);
  openTab({ path, kind: "graph", graphKind: "test" });
  void refreshTree();
  const entry = entryNode(getDoc(path)?.value ?? null);
  const outcome = await insertAndSave(path, prepared.fragment, entry === null ? {} : { after: { node: entry, exit: "start" } });
  if (outcome !== "saved") {
    // 되돌리지 못했으면 세션을 committing에 둔다 (다시 넣지 않게) — 사람이 그래프를 확인하거나 녹화를 버린다
    if (outcome !== "stuck") await abort(prepared.token);
    return "failed";
  }
  await finish(prepared.token, path, warningTexts(prepared.fragment));
  return "done";
}

/** 넣을 그래프: 지금 그래프 탭 (스냅샷·읽기 전용 아님) */
export function insertTarget(): string | null {
  const { active, tabs } = useTabs.getState();
  const tab = tabs.find((t) => t.path === active);
  if (tab?.kind !== "graph" || tab.snapshot === true) return null;
  const doc = getDoc(tab.path);
  return doc !== undefined && doc.status === "ready" && !doc.readOnly ? tab.path : null;
}

/** 고른 노드 없이 넣을 자리: 기존 노드 아래 */
function freeSpot(value: GraphValue): { x: number; y: number } {
  const layout = own(own(value, "layout"), "nodes");
  let minX = Infinity;
  let maxY = -Infinity;
  if (isObject(layout)) {
    for (const k of Object.keys(layout)) {
      const x = own(layout[k], "x");
      const y = own(layout[k], "y");
      if (typeof x === "number" && typeof y === "number") {
        minX = Math.min(minX, x);
        maxY = Math.max(maxY, y);
      }
    }
  }
  return Number.isFinite(minX) ? { x: minX, y: maxY + 220 } : { x: 0, y: 0 };
}

/** "커서 위치에 노드로 삽입" */
export async function commitInsert(): Promise<boolean> {
  if (useRecorder.getState().busy !== null || retryBlocked()) return false;
  const path = insertTarget();
  const doc = path === null ? undefined : getDoc(path);
  if (path === null || doc === undefined || doc.value === null) {
    notice("넣을 그래프 탭을 열고 넣을 자리의 노드를 고르세요");
    return false;
  }
  let after: { node: string; exit: string } | null = null;
  const selected = doc.view.selected;
  if (selected !== null) {
    const type = own(own(own(doc.value, "nodes"), selected), "type");
    const choice = insertExits(typeof type === "string" ? type : "", doc.shapes[selected]?.exits);
    if (choice.kind === "terminal") {
      notice("끝 노드 뒤에는 넣을 수 없어요. 다른 노드를 고르세요");
      return false;
    }
    let exit = choice.kind === "one" ? choice.exit : null;
    if (choice.kind === "many") {
      const r = await ask({
        title: "어느 출구 뒤에 넣을까요?",
        message: "고른 노드의 출구가 여럿이에요. 녹화한 노드를 이을 출구를 고르세요.",
        buttons: [...choice.exits.map((e, i) => ({ label: e, value: e, primary: i === 0 })), { label: "취소", value: "" }],
        cancelValue: "",
      });
      if (r.value === "") return false;
      exit = r.value;
    }
    if (exit !== null) after = { node: selected, exit };
  }
  useRecorder.setState({ busy: "commit", notice: null });
  try {
    const prepared = await prepare("insert", path, doc.baseRevision);
    if (prepared === null) return false;
    const now = getDoc(path);
    if (now === undefined || now.value === null) {
      await abort(prepared.token);
      notice("그래프 탭이 닫혀 넣지 못했어요");
      return false;
    }
    const outcome = await insertAndSave(path, prepared.fragment, after === null ? { at: freeSpot(now.value) } : { after });
    if (outcome !== "saved") {
      if (outcome !== "stuck") await abort(prepared.token);
      return false;
    }
    await finish(prepared.token, path, warningTexts(prepared.fragment));
    return true;
  } finally {
    useRecorder.setState({ busy: null });
  }
}
