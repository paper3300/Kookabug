// 열린 캔버스가 밖(팔레트·메뉴)에 내놓는 동작. 캔버스가 붙을 때 등록하고 떨어질 때 지운다
import type { NodeTypeInfo } from "./mapping";

export interface CanvasActions {
  /** 보이는 화면 가운데에 노드를 더한다 (팔레트 Enter·두 번 누르기) */
  addAtCenter(info: NodeTypeInfo): void;
}

const actions = new Map<string, CanvasActions>();

export function registerCanvas(path: string, a: CanvasActions): () => void {
  actions.set(path, a);
  return () => {
    if (actions.get(path) === a) actions.delete(path);
  };
}

export function canvasActions(path: string | null): CanvasActions | undefined {
  return path === null ? undefined : actions.get(path);
}
