// 주석 (layout.comments): 노드 뒤에 깔리는 상자. 만들기·고치기는 이후 (보류 H3), M2는 보여 주고 보존한다
import type { Node, NodeProps } from "@xyflow/react";
import type { CommentNodeData } from "../mapping";
import css from "./nodes.module.css";

export function CommentNode({ data }: NodeProps<Node<CommentNodeData, "kbComment">>) {
  return (
    <div className={css.comment} data-part="comment" data-comment-id={data.id}>
      {data.text}
    </div>
  );
}
