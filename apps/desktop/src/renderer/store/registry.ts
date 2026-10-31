// 설치된 노드 타입 (nodes.list). 캔버스는 노드 제목·분류(머리 색)·순수 여부를 여기서 읽고, 팔레트(T9)도
// 같은 목록을 쓴다. 연결마다 다시 읽는다 (플러그인 설치가 바뀌었을 수 있다)
import { create } from "zustand";
import { indexNodeTypes, type NodeTypeInfo } from "../graph/mapping";
import { client } from "../rpc/client";

interface RegistryState {
  schemas: unknown[];
  types: ReadonlyMap<string, NodeTypeInfo>;
  loaded: boolean;
}

export const useRegistry = create<RegistryState>(() => ({ schemas: [], types: new Map(), loaded: false }));

let generation = 0;

export async function refreshRegistry(): Promise<void> {
  const mine = ++generation;
  const result = await client().call("nodes.list", {});
  if (mine !== generation) return;
  useRegistry.setState({ schemas: result.schemas, types: indexNodeTypes(result.schemas), loaded: true });
}

export function resetRegistry(): void {
  generation++;
  useRegistry.setState({ schemas: [], types: new Map(), loaded: false });
}
