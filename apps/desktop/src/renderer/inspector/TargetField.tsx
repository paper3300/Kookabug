// `$target` 칸 (M2 계획 2.9 "그래프와 연결", T12): 대상 고르기 + "새 대상 만들기". 새로 만든 대상은 TARGET 탭에서
// 저장되면 이 핀에 {"$target": "<경로>"}가 들어간다 (target/targetStore.ts fillOrigin)
import { newTargetInteractive } from "../target/newTarget";
import { TargetSelect, type EditorContext } from "./editors";

/** 새 이름 제안: 노드 제목 → 파일 이름에 쓸 수 있는 글자만 */
function suggestName(title: string | undefined): string {
  const base = (title ?? "").trim().replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_").replace(/^\.+|\.+$/g, "");
  return base.slice(0, 60);
}

export function TargetField({
  label,
  value,
  onCommit,
  ctx,
  node,
  pin,
  title,
}: {
  label: string;
  value: string;
  onCommit(path: string): void;
  ctx: EditorContext;
  node: string;
  pin: string;
  title?: string;
}) {
  const graph = ctx.graph;
  return (
    <TargetSelect
      label={label}
      value={value}
      onCommit={onCommit}
      ctx={ctx}
      {...(graph === undefined
        ? {}
        : { onCreate: () => void newTargetInteractive({ graph, node, pin }, suggestName(title)) })}
    />
  );
}
