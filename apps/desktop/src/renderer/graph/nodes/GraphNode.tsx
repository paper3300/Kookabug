// 그래프 노드 (시안 Main): 머리(분류 색·제목·상태 줄), 핀 줄(왼쪽 흐름 입력·데이터 입력, 오른쪽 출구·출력),
// 설명 줄(주요 입력 요약 또는 첫 진단). 핀은 흐름 = 삼각형, 데이터 = 원이고 색은 pinColors 표다
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { KbNodeData, PinRow } from "../mapping";
import { pinColor } from "../pinColors";
import css from "./nodes.module.css";

function Pin({ pin, side }: { pin: PinRow; side: "left" | "right" }) {
  return (
    <Handle
      type={side === "left" ? "target" : "source"}
      position={side === "left" ? Position.Left : Position.Right}
      id={pin.handle}
      isConnectable={false}
      className={`${css.pin} ${pin.kind === "exec" ? css.exec : ""}`}
      style={{ background: pinColor(pin.tone) }}
      data-pin={pin.handle}
      data-tone={pin.tone}
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
            {row.left !== null && <Pin pin={row.left} side="left" />}
            {row.left !== null && row.left.label !== "" && (
              <span className={labelClass(row.left, false)} title={row.left.label}>
                {row.left.label}
              </span>
            )}
            {row.right !== null && (
              <span className={labelClass(row.right, true)} title={row.right.label}>
                {row.right.label}
              </span>
            )}
            {row.right !== null && <Pin pin={row.right} side="right" />}
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
