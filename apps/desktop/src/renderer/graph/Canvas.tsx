// 그래프 캔버스 (M2 계획 T8·T9): 탭 하나의 문서를 React Flow로 그린다.
// 노드·연결선은 값에서 사상한 것(mapping.ts)이다. 편집은 값 명령(commands/*)으로만 하고, React Flow 상태는 화면
// 상태(잰 크기·끌기 중 좌표·고르기)로만 든다. 흐름은 한 방향이다: React Flow 변경 → 값 명령·보기 상태 → 사상 →
// React Flow (T8의 React 오류 185 무한 다시 그리기: React Flow 상태를 그대로 다시 보기 상태로 되돌려 쓰지 않는다.
// 고르기는 값이 같으면 표를 건드리지 않는다)
// - 옮기기: 끌기 중에는 화면 좌표만 바꾸고 끌기를 놓을 때 이동 명령 하나 (정수 반올림)
// - 연결: 핀을 끌어 놓으면 연결 명령. 끌기 중 호환 핀 강조, 데이터 연결이면 숨긴 선택 입력 핀도 보인다
// - 지우기: Delete·Backspace로 고른 노드·연결선을 명령 하나로 지운다
// - 팔레트에서 끌어 놓으면 그 자리에 노드를 더한다
// - 오른쪽 단추를 누른 채 끌면 화면 이동 (UX4, 노드 위에서도). 짧은 오른쪽 클릭은 노드 메뉴
// - 서브그래프 호출 노드를 더블클릭하면 그 서브그래프 탭으로 간다 (다듬기 P1-B)
import "@xyflow/react/dist/base.css";
import {
  applyNodeChanges,
  Background,
  BackgroundVariant,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
  type Connection as FlowConnection,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type OnConnectStartParams,
  type XYPosition,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent as ReactMouseEvent } from "react";
import { useRightDragPan } from "../app/rightDragPan";
import { PALETTE_MIME } from "../palette/groups";
import { applyEdit, getDoc, saveViewport, setSelection, useDocuments, type GraphDoc } from "../store/documents";
import { useEditsLocked } from "../store/dialog";
import { useRegistry } from "../store/registry";
import { NodeMenu, type NodeMenuAt } from "../debug/NodeMenu";
import { TabDebugContext, useTabDebugView } from "../debug/view";
import { TabRunContext, useTabRunView } from "../run/view";
import css from "./canvas.module.css";
import { registerCanvas } from "./canvasActions";
import { addNode, connect, deleteSelection, moveNodes } from "./commands";
import { compatible, type PinEnd } from "./compat";
import { KbEdge } from "./edges/KbEdge";
import { newNodeId, takenIds } from "./ids";
import { toFlow, type FlowGraph, type KbFlowEdge, type KbFlowNode, type NodeTypeInfo, type TypeIndex } from "./mapping";
import { CommentNode } from "./nodes/CommentNode";
import { CanvasPathContext, ConnectingContext } from "./nodes/context";
import { GraphNode, pinEnd } from "./nodes/GraphNode";
import { GroupNode } from "./nodes/GroupNode";
import { openSubgraph } from "./openSubgraph";
import { callTargetOf } from "./subgraphPlan";

const NODE_TYPES = { kb: GraphNode, kbGroup: GroupNode, kbComment: CommentNode };
const EDGE_TYPES = { kb: KbEdge };
const PRO = { hideAttribution: true };
const FIT = { padding: 0.15, maxZoom: 1 };
/** 시안 미니맵 120×72 (React Flow는 style의 너비·높이로 그림 크기를 정한다) */
const MINIMAP_SIZE = { width: 120, height: 72 };
const DELETE_KEYS = ["Delete", "Backspace"];
const CONNECTION_LINE = { stroke: "var(--kb-accent)", strokeWidth: 2 };
/** 놓은 자리가 노드 머리 가운데쯤 오게 (노드 너비 184px, 머리 32px) */
const DROP_OFFSET = { x: 92, y: 16 };
/** 노드 더블클릭으로 서브그래프를 열지 않는 노드 안 요소 (브레이크포인트 점·포트·입력 칸 등). */
const NODE_CONTROLS = "button, input, select, textarea, a, [contenteditable='true'], .react-flow__handle";

function ZoomBox() {
  const rf = useReactFlow();
  const { zoom } = useViewport();
  return (
    <div className={css.zoom} data-part="zoom">
      <button type="button" aria-label="축소" onClick={() => void rf.zoomOut({ duration: 120 })}>
        −
      </button>
      <span>{Math.round(zoom * 100)}%</span>
      <button type="button" aria-label="확대" onClick={() => void rf.zoomIn({ duration: 120 })}>
        +
      </button>
    </div>
  );
}

/** 사상한 노드에서 손잡이 하나의 핀 끝 (호환 판정용) */
function findEnd(flow: FlowGraph, node: string, handle: string | null | undefined): PinEnd | null {
  const n = flow.nodes.find((x) => x.id === node);
  if (n === undefined || n.type !== "kb" || handle === null || handle === undefined) return null;
  for (const row of n.data.rows) {
    if (row.left?.handle === handle) return pinEnd(node, row.left, "left");
    if (row.right?.handle === handle) return pinEnd(node, row.right, "right");
  }
  return null;
}

/** 팔레트 노드를 그 자리에 더한다 (명령 하나, 더한 노드를 고른다) */
function addNodeAt(path: string, info: NodeTypeInfo, at: XYPosition): string | null {
  const doc = getDoc(path);
  if (doc === undefined || doc.value === null) return null;
  const id = newNodeId(takenIds(doc.value));
  const plugin = info.plugin !== "" && info.pluginVersion !== "" ? { id: info.plugin, version: info.pluginVersion } : null;
  const added = applyEdit(
    path,
    (v) => addNode(v, { id, type: info.type, version: info.version, x: at.x, y: at.y, plugin }),
    [id],
  );
  return added ? id : null;
}

function FlowView({ doc, types }: { doc: GraphDoc; types: TypeIndex }) {
  const rf = useReactFlow();
  const path = doc.path;
  const { expanded: expandedList, selection, viewport, focus, auto } = doc.view;
  const expanded = useMemo(() => new Set(expandedList), [expandedList]);
  const selected = useMemo(() => new Set(selection), [selection]);
  // 대화 상자·저장하고 닫기 중에는 끌기·잇기·지우기를 끈다 (값 명령도 store가 거부한다).
  // 실행 스냅샷 그래프는 늘 읽기 전용이다 (M3 2.10)
  const dialogLocked = useEditsLocked();
  const locked = dialogLocked || doc.readOnly;
  const [connecting, setConnecting] = useState<PinEnd | null>(null);
  const revealInputs = connecting?.kind === "data";
  const flow = useMemo(
    () =>
      toFlow({
        path,
        value: doc.value!,
        shapes: doc.shapes,
        types,
        diagnostics: doc.diagnostics,
        view: { expanded, selected, revealInputs, auto },
      }),
    [path, doc.value, doc.shapes, doc.diagnostics, types, expanded, selected, revealInputs, auto],
  );
  const flowRef = useRef(flow);
  flowRef.current = flow;

  // React Flow가 잰 크기(measured)와 끌기 중 좌표만 화면 상태로 들고, 나머지는 매번 값에서 다시 만든다
  const dragging = useRef(new Map<string, XYPosition>());
  const nodesRef = useRef<KbFlowNode[]>(flow.nodes);
  const [nodes, setNodesState] = useState<KbFlowNode[]>(flow.nodes);
  const setNodes = useCallback((next: KbFlowNode[]) => {
    nodesRef.current = next;
    setNodesState(next);
  }, []);
  useEffect(() => {
    const prev = new Map(nodesRef.current.map((n) => [n.id, n]));
    setNodes(
      flow.nodes.map((n) => {
        const old = prev.get(n.id);
        const at = dragging.current.get(n.id);
        let out = n;
        if (old?.measured !== undefined) out = { ...out, measured: old.measured };
        if (at !== undefined) out = { ...out, position: at, dragging: true };
        return out;
      }),
    );
  }, [flow.nodes, setNodes]);

  const onNodesChange = useCallback(
    (changes: NodeChange<KbFlowNode>[]) => {
      // 지우기는 onDelete가 값 명령으로 한다. 크기·끌기 중 좌표·고르기만 화면 상태로 받는다
      const keep = changes.filter((c) => c.type === "dimensions" || c.type === "position" || c.type === "select");
      if (keep.length === 0) return;
      for (const c of keep) {
        if (c.type === "position" && c.position !== undefined && c.dragging === true) dragging.current.set(c.id, c.position);
      }
      const next = applyNodeChanges(keep, nodesRef.current);
      setNodes(next);
      if (keep.some((c) => c.type === "select")) {
        // 보기 상태가 같으면 setSelection은 표를 건드리지 않는다 (되먹임이 멈춘다)
        setSelection(
          path,
          next.filter((n) => n.type === "kb" && n.selected === true).map((n) => n.id),
        );
      }
    },
    [path, setNodes],
  );

  const onNodeDragStop = useCallback(
    (_: unknown, __: KbFlowNode, dragged: KbFlowNode[]) => {
      const moves = dragged
        .filter((n) => n.type === "kb")
        .map((n) => {
          const at = dragging.current.get(n.id) ?? n.position;
          return { id: n.id, x: at.x, y: at.y };
        });
      dragging.current.clear();
      // 끌기 하나 = 명령 하나 (2.6·T9). 같은 자리에 놓으면 값이 같아 기록을 남기지 않는다
      applyEdit(path, (v) => moveNodes(v, moves));
    },
    [path],
  );

  // 연결선 고르기는 화면 상태다 (지우기 대상)
  const [edgeSelection, setEdgeSelection] = useState<ReadonlySet<string>>(() => new Set());
  const edges = useMemo(
    () => flow.edges.map((e) => (edgeSelection.has(e.id) ? { ...e, selected: true } : e)),
    [flow.edges, edgeSelection],
  );
  const onEdgesChange = useCallback((changes: EdgeChange<KbFlowEdge>[]) => {
    const select = changes.filter((c) => c.type === "select");
    if (select.length === 0) return;
    setEdgeSelection((prev) => {
      const next = new Set(prev);
      for (const c of select) {
        if (c.selected) next.add(c.id);
        else next.delete(c.id);
      }
      return next.size === prev.size && [...next].every((id) => prev.has(id)) ? prev : next;
    });
  }, []);

  const onDelete = useCallback(
    ({ nodes: gone, edges: cut }: { nodes: KbFlowNode[]; edges: Edge[] }) => {
      const nodeIds = gone.filter((n) => n.type === "kb").map((n) => n.id);
      const edgeIds = cut.map((e) => e.id);
      if (nodeIds.length === 0 && edgeIds.length === 0) return;
      applyEdit(path, (v) => deleteSelection(v, nodeIds, edgeIds));
      setEdgeSelection(new Set());
    },
    [path],
  );

  const onConnectStart = useCallback((_: unknown, p: OnConnectStartParams) => {
    if (p.nodeId === null) return;
    setConnecting(findEnd(flowRef.current, p.nodeId, p.handleId));
  }, []);
  const onConnectEnd = useCallback(() => setConnecting(null), []);
  const isValidConnection = useCallback((c: FlowConnection | Edge) => {
    const a = findEnd(flowRef.current, c.source, c.sourceHandle);
    const b = findEnd(flowRef.current, c.target, c.targetHandle);
    return a !== null && b !== null && compatible(a, b);
  }, []);
  const onConnect = useCallback(
    (c: FlowConnection) => {
      setConnecting(null);
      applyEdit(path, (v) => connect(v, c));
    },
    [path],
  );

  // 팔레트에서 끌어 놓기
  const [dropping, setDropping] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const onDragOver = useCallback((e: DragEvent) => {
    if (doc.readOnly || !e.dataTransfer.types.includes(PALETTE_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setDropping(true);
  }, [doc.readOnly]);
  const onDragLeave = useCallback((e: DragEvent) => {
    if (!(e.relatedTarget instanceof Node) || !e.currentTarget.contains(e.relatedTarget)) setDropping(false);
  }, []);
  const onDrop = useCallback(
    (e: DragEvent) => {
      setDropping(false);
      const type = e.dataTransfer.getData(PALETTE_MIME);
      const info = types.get(type);
      if (info === undefined) return;
      e.preventDefault();
      const at = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      addNodeAt(path, info, { x: at.x - DROP_OFFSET.x, y: at.y - DROP_OFFSET.y });
    },
    [path, rf, types],
  );
  useEffect(
    () =>
      registerCanvas(path, {
        addAtCenter(info) {
          const box = wrapper.current?.getBoundingClientRect();
          if (box === undefined) return;
          const at = rf.screenToFlowPosition({ x: box.left + box.width / 2, y: box.top + box.height / 2 });
          addNodeAt(path, info, { x: at.x - DROP_OFFSET.x, y: at.y - DROP_OFFSET.y });
        },
      }),
    [path, rf],
  );

  // 문제 패널에서 고른 노드로 화면을 옮긴다. 막 펼친 그룹의 노드·막 연 탭은 크기를 잴 때까지 기다리고,
  // 처음 맞춤(fitView)이 끝나도록 두 화면 더 기다린 뒤 옮긴다
  useEffect(() => {
    if (focus === null) return;
    let frame = 0;
    let tries = 0;
    let settled = 0;
    const go = () => {
      const n = rf.getInternalNode(focus.node);
      const w = n?.measured.width;
      const h = n?.measured.height;
      if (n === undefined || w === undefined || h === undefined || !rf.viewportInitialized || settled++ < 2) {
        if (tries++ < 120) frame = requestAnimationFrame(go);
        return;
      }
      const { x, y } = n.internals.positionAbsolute;
      void rf.setCenter(x + w / 2, y + h / 2, { zoom: Math.max(rf.getZoom(), 1), duration: 200 });
    };
    go();
    return () => cancelAnimationFrame(frame);
    // focus는 요청마다 새 객체(nonce)라 같은 노드를 다시 눌러도 옮긴다
  }, [focus, rf]);

  // 실행 중 강조·노드 상태 줄 (T11): 값 사상과 따로 맥락으로 넘긴다 (이벤트마다 사상을 다시 하지 않는다)
  const run = useTabRunView(path, doc.value);
  // 브레이크포인트 점·멈춘 노드 (M3 T9): 같은 방식
  const debug = useTabDebugView(path, doc.value);
  const [menu, setMenu] = useState<NodeMenuAt | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  // 오른쪽 단추 끌기 = 화면 이동 (UX4). 짧은 오른쪽 클릭은 지금처럼 노드 메뉴
  const rightPan = useRightDragPan(
    (dx, dy) => {
      const vp = rf.getViewport();
      void rf.setViewport({ x: vp.x + dx, y: vp.y + dy, zoom: vp.zoom });
    },
    () => saveViewport(path, rf.getViewport()),
  );
  // 스냅샷 그래프에는 브레이크포인트를 걸지 않는다 (브레이크포인트는 워크스페이스 그래프 경로가 열쇠)
  const onNodeContextMenu = useCallback((e: ReactMouseEvent, node: KbFlowNode) => {
    if (node.type !== "kb" || doc.readOnly) return;
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, node: node.id });
  }, [doc.readOnly]);

  // 서브그래프 호출 노드 더블클릭 → 그 서브그래프 탭 (다듬기 P1-B). 읽기 전용·실행 중에도 된다 (보기 이동이다)
  const value = doc.value;
  const onNodeDoubleClick = useCallback(
    (e: ReactMouseEvent, node: KbFlowNode) => {
      if (node.type !== "kb") return;
      // 노드 안의 단추·포트·입력 칸에서 온 더블클릭은 그 요소의 조작이다 (노드 본문만 연다)
      if (e.target instanceof Element && e.target.closest(NODE_CONTROLS) !== null) return;
      const target = callTargetOf(value, node.id);
      if (target === null) return;
      e.preventDefault();
      void openSubgraph(path, target);
    },
    [path, value],
  );

  const empty = flow.nodes.every((n) => n.type !== "kb" && n.type !== "kbGroup");
  return (
    <CanvasPathContext.Provider value={path}>
      <TabRunContext.Provider value={run}>
      <TabDebugContext.Provider value={doc.readOnly ? null : debug}>
      <ConnectingContext.Provider value={connecting}>
        <ReactFlow<KbFlowNode, KbFlowEdge>
          ref={wrapper}
          onPointerDownCapture={rightPan.onPointerDownCapture}
          onContextMenuCapture={rightPan.onContextMenuCapture}
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={onNodeDragStop}
          onNodeContextMenu={onNodeContextMenu}
          onNodeDoubleClick={onNodeDoubleClick}
          onDelete={onDelete}
          onConnectStart={onConnectStart}
          onConnectEnd={onConnectEnd}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onMoveEnd={(_, vp) => saveViewport(path, vp)}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          nodesDraggable={!locked}
          nodesConnectable={!locked}
          elementsSelectable
          edgesFocusable={false}
          selectionOnDrag={false}
          deleteKeyCode={locked ? null : DELETE_KEYS}
          nodeDragThreshold={3}
          connectionLineStyle={CONNECTION_LINE}
          minZoom={0.2}
          maxZoom={2}
          {...(viewport === null ? { fitView: true, fitViewOptions: FIT } : { defaultViewport: viewport })}
          proOptions={PRO}
          className={css.flow}
          data-dropping={dropping}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="var(--kb-canvas-dot)" />
          <div className={css.corner}>
            <ZoomBox />
            <MiniMap
              className={css.minimap}
              style={MINIMAP_SIZE}
              pannable
              zoomable
              ariaLabel="미니맵"
              nodeColor="var(--kb-node-border)"
              nodeStrokeColor="transparent"
              bgColor="var(--kb-node-bg)"
              maskColor="transparent"
              maskStrokeColor="var(--kb-minimap-view)"
              maskStrokeWidth={1}
            />
          </div>
        </ReactFlow>
      </ConnectingContext.Provider>
      </TabDebugContext.Provider>
      </TabRunContext.Provider>
      {menu !== null && <NodeMenu graph={path} at={menu} onClose={closeMenu} />}
      {empty && !dropping && !doc.readOnly && <div className={css.emptyHint}>팔레트에서 노드를 끌어 놓으세요</div>}
      {dropping && (
        <div className={css.dropZone} data-part="drop-zone">
          <span className={css.dropHint}>여기에 놓으면 노드를 더해요</span>
        </div>
      )}
    </CanvasPathContext.Provider>
  );
}

function ErrorView({ doc }: { doc: GraphDoc }) {
  const e = doc.error;
  const where = e !== null && e.line !== null ? `줄 ${e.line}${e.column !== null ? `, 칸 ${e.column}` : ""}: ` : "";
  const title =
    e?.kind === "not_found"
      ? "파일이 없어요"
      : e?.kind === "not_connected"
        ? "daemon에 연결되면 열어요"
        : "그래프를 열 수 없어요";
  return (
    <div className={css.message} role="alert" data-part="graph-error" data-kind={e?.kind ?? ""}>
      <strong>{title}</strong>
      <span className={css.messagePath}>{doc.path}</span>
      {e !== null && e.kind !== "not_found" && (
        <span className={css.messageDetail}>
          {where}
          {e.message}
        </span>
      )}
    </div>
  );
}

/** 탭 내용: 문서 하나의 캔버스 */
export function GraphCanvas({ path }: { path: string }) {
  const doc = useDocuments((s) => s.docs.get(path));
  const types = useRegistry((s) => s.types);
  let body;
  if (doc === undefined || (doc.status === "loading" && doc.value === null)) {
    body = <div className={css.message}>여는 중…</div>;
  } else if (doc.status === "error" || doc.value === null) {
    body = <ErrorView doc={doc} />;
  } else {
    body = (
      <ReactFlowProvider>
        <FlowView doc={doc} types={types} />
      </ReactFlowProvider>
    );
  }
  return (
    <div
      className={css.canvas}
      data-part="canvas"
      data-path={path}
      data-status={doc?.status ?? "loading"}
      data-dirty={doc?.dirty ?? false}
      data-readonly={doc?.readOnly ?? false}
      data-saves={doc?.saves ?? 0}
      data-revision={doc?.baseRevision ?? ""}
    >
      {body}
    </div>
  );
}
