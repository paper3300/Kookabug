// 그래프 캔버스 (M2 계획 T8): 탭 하나의 문서를 React Flow로 그린다. T8은 보기만 한다(옮기기·연결은 T9).
// 노드·연결선은 값에서 사상한 것(mapping.ts)이고, React Flow가 재는 노드 크기만 화면 상태로 붙인다.
// 고르기·펼친 그룹·뷰포트는 문서의 보기 상태(store/documents.ts)라 파일에 쓰지 않는다
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
  type NodeChange,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { saveViewport, selectNode, useDocuments, type GraphDoc } from "../store/documents";
import { useRegistry } from "../store/registry";
import css from "./canvas.module.css";
import { KbEdge } from "./edges/KbEdge";
import { toFlow, type KbFlowNode, type TypeIndex } from "./mapping";
import { CommentNode } from "./nodes/CommentNode";
import { CanvasPathContext } from "./nodes/context";
import { GraphNode } from "./nodes/GraphNode";
import { GroupNode } from "./nodes/GroupNode";

const NODE_TYPES = { kb: GraphNode, kbGroup: GroupNode, kbComment: CommentNode };
const EDGE_TYPES = { kb: KbEdge };
const PRO = { hideAttribution: true };
const FIT = { padding: 0.15, maxZoom: 1 };
/** 시안 미니맵 120×72 (React Flow는 style의 너비·높이로 그림 크기를 정한다) */
const MINIMAP_SIZE = { width: 120, height: 72 };

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

function FlowView({ doc, types }: { doc: GraphDoc; types: TypeIndex }) {
  const rf = useReactFlow();
  const path = doc.path;
  const { expanded: expandedList, selected, viewport, focus } = doc.view;
  const expanded = useMemo(() => new Set(expandedList), [expandedList]);
  const flow = useMemo(
    () =>
      toFlow({
        path,
        value: doc.value!,
        shapes: doc.shapes,
        types,
        diagnostics: doc.diagnostics,
        view: { expanded, selected },
      }),
    [path, doc.value, doc.shapes, doc.diagnostics, types, expanded, selected],
  );

  // React Flow가 잰 크기(measured)만 화면 상태로 들고, 나머지는 매번 값에서 다시 만든다
  const [nodes, setNodes] = useState<KbFlowNode[]>(flow.nodes);
  useEffect(() => {
    setNodes((prev) => {
      const measured = new Map(prev.map((n) => [n.id, n.measured]));
      return flow.nodes.map((n) => {
        const m = measured.get(n.id);
        return m === undefined ? n : { ...n, measured: m };
      });
    });
  }, [flow.nodes]);
  // 고르기의 권위는 문서 보기 상태 하나다 (누르기 → 보기 상태 → 노드의 selected). React Flow의 고르기 변경을
  // 다시 보기 상태로 되돌려 쓰면 두 쪽이 서로를 고쳐 다시 그리기가 멈추지 않을 수 있다
  const onNodesChange = useCallback((changes: NodeChange<KbFlowNode>[]) => {
    // 보기 전용: 크기만 받는다. 옮기기·지우기는 T9
    const allowed = changes.filter((c) => c.type === "dimensions");
    if (allowed.length > 0) setNodes((ns) => applyNodeChanges(allowed, ns));
  }, []);
  const onNodeClick = useCallback(
    (_: unknown, node: KbFlowNode) => selectNode(path, node.type === "kb" ? node.id : null),
    [path],
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

  const empty = flow.nodes.every((n) => n.type !== "kb" && n.type !== "kbGroup");
  return (
    <CanvasPathContext.Provider value={path}>
      <ReactFlow<KbFlowNode>
        nodes={nodes}
        edges={flow.edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onNodeClick={onNodeClick}
        onPaneClick={() => selectNode(path, null)}
        onMoveEnd={(_, vp) => saveViewport(path, vp)}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        edgesFocusable={false}
        selectionOnDrag={false}
        deleteKeyCode={null}
        minZoom={0.2}
        maxZoom={2}
        {...(viewport === null ? { fitView: true, fitViewOptions: FIT } : { defaultViewport: viewport })}
        proOptions={PRO}
        className={css.flow}
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
      {empty && <div className={css.emptyHint}>팔레트에서 노드를 끌어 놓으세요</div>}
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
    >
      {body}
    </div>
  );
}
