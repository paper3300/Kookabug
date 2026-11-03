// 그래프 노드 (시안 Main): 머리(분류 색·제목·상태 줄), 핀 줄(왼쪽 흐름 입력·데이터 입력, 오른쪽 출구·출력),
// 설명 줄(주요 입력 요약 또는 첫 진단). 핀은 흐름 = 삼각형, 데이터 = 원이고 색은 pinColors 표다.
// 핀을 끌어 연결한다 (T9). 연결 끌기 중에는 이을 수 있는 핀을 강조하고 아닌 핀은 흐리게 그린다
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { toggleNodeBreakpoint } from "../../debug/commands";
import { REASON_TEXT } from "../../debug/pauseState";
import { useNodeDebug } from "../../debug/view";
import { runningText, type NodeRunView } from "../../run/highlight";
import { useNodeRun, useNow } from "../../run/view";
import { useRegistry } from "../../store/registry";
import { compatible, type PinEnd } from "../compat";
import type { KbNodeData, PinRow } from "../mapping";
import { pinColor } from "../pinColors";
import { useCanvasPath, useConnecting } from "./context";
import css from "./nodes.module.css";

export function pinEnd(node: string, pin: PinRow, side: "left" | "right"): PinEnd {
  return { node, handle: pin.handle, side: side === "left" ? "target" : "source", kind: pin.kind, type: pin.type };
}

function Pin({ node, pin, side }: { node: string; pin: PinRow; side: "left" | "right" }) {
  const connecting = useConnecting();
  const end = pinEnd(node, pin, side);
  const compat =
    connecting === null
      ? undefined
      : connecting.node === node && connecting.handle === pin.handle
        ? "from"
        : compatible(connecting, end)
          ? "ok"
          : "no";
  return (
    <Handle
      type={side === "left" ? "target" : "source"}
      position={side === "left" ? Position.Left : Position.Right}
      id={pin.handle}
      isConnectable
      className={`${css.pin} ${pin.kind === "exec" ? css.exec : ""}`}
      style={{ background: pinColor(pin.tone) }}
      data-pin={pin.handle}
      data-tone={pin.tone}
      data-compat={compat}
    />
  );
}

function labelClass(pin: PinRow, right: boolean): string {
  const classes = [css.label];
  if (right) classes.push(css.labelRight);
  if (pin.extra) classes.push(css.extra);
  else if (pin.tone === "fail") classes.push(css.fail);
  return classes.join(" ");
}

/** 실행 상태 줄 (T11): 성공 "✓ 38ms", 실행 중 "● 1.4s"(흐르는 시간), 반복 "3 / 10" */
function RunStatus({ view }: { view: NodeRunView }) {
  const now = useNow(view.since !== null);
  return (
    <span className={css.status} data-tone={view.tone} data-part="node-status" data-run-status={view.step.end?.status ?? "running"}>
      {view.since !== null ? runningText(view.since, now) : view.text}
    </span>
  );
}

/**
 * 브레이크포인트 점 자리 (M3 2.9, U1): 노드 머리 왼쪽. 걸렸으면 빨간 점, 아니면 올려 둘 때만 흐린 점. 누르면 토글.
 * 끌기·고르기와 섞이지 않게 노드 끌기를 막는다(nodrag)
 */
function BreakpointSpot({ id, on }: { id: string; on: boolean }) {
  const path = useCanvasPath();
  return (
    <button
      type="button"
      className={`${css.bpSpot} nodrag`}
      data-part="bp-spot"
      data-on={on}
      aria-label={on ? "브레이크포인트 해제" : "브레이크포인트 설정"}
      title={on ? "브레이크포인트 해제 (F9)" : "브레이크포인트 설정 (F9)"}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        toggleNodeBreakpoint(path, id);
      }}
      // 빠르게 두 번 눌러도 토글 두 번일 뿐, 노드 더블클릭(서브그래프 열기)이 아니다 (다듬기 P1-B)
      onDoubleClick={(e) => e.stopPropagation()}
    >
      <span className={css.bpDot} data-part={on ? "bp-dot" : undefined} />
    </button>
  );
}

export function GraphNode({ data, selected }: NodeProps<Node<KbNodeData, "kb">>) {
  const connecting = useConnecting();
  const run = useNodeRun(data.id);
  const debug = useNodeDebug(data.id);
  // 순수 노드에는 스텝이 없어 브레이크포인트를 걸 수 없다 (점 자리 없음)
  const pure = useRegistry((s) => s.types.get(data.type)?.pure === true);
  const dim = (pin: PinRow | null, side: "left" | "right") =>
    connecting !== null && pin !== null && !compatible(connecting, pinEnd(data.id, pin, side)) ? css.dim : "";
  const runState = run === null ? undefined : run.view?.highlight === true ? "active" : run.view !== null ? "done" : run.idle ? "idle" : undefined;
  const paused = debug?.paused ?? null;
  return (
    <div
      className={`${css.node} ${selected ? css.selected : ""}`}
      data-part="node"
      data-node-id={data.id}
      data-head={data.head}
      data-unknown={data.unknown}
      data-errors={data.errors}
      data-warnings={data.warnings}
      data-run={runState}
      data-run-tone={run?.view?.tone}
      data-breakpoint={debug?.breakpoint === true ? "true" : undefined}
      data-paused={paused !== null ? paused.reason : undefined}
    >
      <div className={css.head} data-part="node-head">
        {!pure && debug !== null && <BreakpointSpot id={data.id} on={debug.breakpoint} />}
        <span className={css.title} title={data.type}>
          {data.title}
        </span>
        {paused !== null ? (
          // 이유는 툴팁으로: 노드 머리(184px)에 다 쓰면 제목이 잘린다. 멈춤 띠·상태 바가 이유를 쓴다
          <span className={css.status} data-tone="paused" data-part="node-paused" title={`멈춤 · ${REASON_TEXT[paused.reason]}`}>
            ⏸ 멈춤
          </span>
        ) : run?.view != null ? (
          <RunStatus view={run.view} />
        ) : (
          data.status !== null && (
            <span className={css.status} data-tone={data.status.tone} data-part="node-status">
              {data.status.text}
            </span>
          )
        )}
      </div>
      <div className={css.body}>
        {data.rows.map((row, i) => (
          <div key={i} className={css.row}>
            {row.left !== null && <Pin node={data.id} pin={row.left} side="left" />}
            {row.left !== null && row.left.label !== "" && (
              <span className={`${labelClass(row.left, false)} ${dim(row.left, "left")}`} title={row.left.label}>
                {row.left.label}
              </span>
            )}
            {row.right !== null && (
              <span className={`${labelClass(row.right, true)} ${dim(row.right, "right")}`} title={row.right.label}>
                {row.right.label}
              </span>
            )}
            {row.right !== null && <Pin node={data.id} pin={row.right} side="right" />}
          </div>
        ))}
        {data.note !== null && (
          <div className={css.note} data-tone={data.note.tone} data-part="node-note">
            {data.note.text}
          </div>
        )}
      </div>
    </div>
  );
}
