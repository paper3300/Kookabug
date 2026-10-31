// 연결선 (시안 Main): 흐름은 회색, fail 출구는 주황 점선, 데이터는 출력 타입 색. 배열·객체 안쪽 `$link`면
// 가운데에 원소 위치(`[0]`, `.error`)를 쓴다
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";
import type { KbFlowEdge } from "../mapping";
import { pinColor } from "../pinColors";
import css from "./edges.module.css";

export function KbEdge(props: EdgeProps<KbFlowEdge>) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data } = props;
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const tone = data?.tone ?? "other";
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke: pinColor(tone),
          strokeWidth: 2,
          ...(tone === "fail" ? { strokeDasharray: "5 4" } : {}),
        }}
      />
      {data !== undefined && data.where !== "" && (
        <EdgeLabelRenderer>
          <div
            className={css.where}
            data-edge-label={id}
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {data.where}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
