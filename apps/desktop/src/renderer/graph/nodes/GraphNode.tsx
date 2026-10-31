// 그래프 노드 (시안 Main): 머리(분류 색·제목·상태 줄), 핀 줄(왼쪽 흐름 입력·데이터 입력, 오른쪽 출구·출력),
// 설명 줄(주요 입력 요약 또는 첫 진단). 핀은 흐름 = 삼각형, 데이터 = 원이고 색은 pinColors 표다.
// 핀을 끌어 연결한다 (T9). 연결 끌기 중에는 이을 수 있는 핀을 강조하고 아닌 핀은 흐리게 그린다
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { compatible, type PinEnd } from "../compat";
import type { KbNodeData, PinRow } from "../mapping";
import { pinColor } from "../pinColors";
import { useConnecting } from "./context";
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

export function GraphNode({ data, selected }: NodeProps<Node<KbNodeData, "kb">>) {
  const connecting = useConnecting();
  const dim = (pin: PinRow | null, side: "left" | "right") =>
    connecting !== null && pin !== null && !compatible(connecting, pinEnd(data.id, pin, side)) ? css.dim : "";
  return (
    <div
      className={`${css.node} ${selected ? css.selected : ""}`}
      data-part="node"
      data-node-id={data.id}
      data-head={data.head}
      data-unknown={data.unknown}
      data-errors={data.errors}
      data-warnings={data.warnings}
    >
      <div className={css.head} data-part="node-head">
        <span className={css.title} title={data.type}>
          {data.title}
        </span>
        {data.status !== null && (
          <span className={css.status} data-tone={data.status.tone} data-part="node-status">
            {data.status.text}
          </span>
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
