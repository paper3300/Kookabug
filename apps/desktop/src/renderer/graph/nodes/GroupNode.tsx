// 접힌 그룹 (스키마 1장 "접기"): layout.collapsed. 펼치기·접기는 보기 상태라 파일을 바꾸지 않는다.
// 접혀 있으면 구성원과 밖을 잇는 연결이 이 노드의 손잡이(g:in·g:out)로 온다
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { toggleGroup } from "../../store/documents";
import { GROUP_IN, GROUP_OUT, type GroupNodeData } from "../mapping";
import css from "./nodes.module.css";
import { useCanvasPath } from "./context";

export function GroupNode({ data }: NodeProps<Node<GroupNodeData, "kbGroup">>) {
  const path = useCanvasPath();
  const problems = data.errors > 0 ? `✕ 오류 ${data.errors}` : data.warnings > 0 ? `⚠ 경고 ${data.warnings}` : null;
  return (
    <div className={css.group} data-part="group" data-group-id={data.id} data-expanded={data.expanded}>
      <Handle type="target" position={Position.Left} id={GROUP_IN} isConnectable={false} className={css.groupPin} />
      <div className={css.groupHead}>
        <span className={css.title}>{data.title}</span>
        {problems !== null && (
          <span className={css.status} data-tone={data.errors > 0 ? "error" : "warn"}>
            {problems}
          </span>
        )}
      </div>
      <div className={css.groupBody}>
        <span>노드 {data.count}개</span>
        <button type="button" className={`${css.groupButton} nodrag`} onClick={() => toggleGroup(path, data.id)}>
          {data.expanded ? "접기" : "펼치기"}
        </button>
      </div>
      <Handle type="source" position={Position.Right} id={GROUP_OUT} isConnectable={false} className={css.groupPin} />
    </div>
  );
}
