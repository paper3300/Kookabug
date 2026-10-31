// 캔버스가 그리는 문서 경로 (노드 컴포넌트가 보기 상태를 바꿀 때 쓴다)
import { createContext, useContext } from "react";

export const CanvasPathContext = createContext<string>("");

export function useCanvasPath(): string {
  return useContext(CanvasPathContext);
}
