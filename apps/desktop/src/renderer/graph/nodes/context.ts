// 캔버스가 그리는 문서 경로 (노드 컴포넌트가 보기 상태를 바꿀 때 쓴다), 연결 끌기 중인 핀 (호환 표시)
import { createContext, useContext } from "react";
import type { PinEnd } from "../compat";

export const CanvasPathContext = createContext<string>("");

export function useCanvasPath(): string {
  return useContext(CanvasPathContext);
}

/** 연결을 끌기 시작한 핀. 끌기 중이 아니면 null */
export const ConnectingContext = createContext<PinEnd | null>(null);

export function useConnecting(): PinEnd | null {
  return useContext(ConnectingContext);
}
