// 새 테스트·새 서브그래프 (M2 계획 T9, graph.create): 이름을 묻고 만든 뒤 탭으로 연다
import { client, toRpcError } from "../rpc/client";
import { ask, setDialogError } from "./dialog";
import { adoptCreated } from "./documents";
import { openTab } from "./tabs";
import { refreshTree } from "./workspace";

const BAD_NAME = /[\\/:*?"<>|\u0000-\u001f]/;

/** 새 그래프 파일 이름 검사 (오류 문구, 괜찮으면 null) */
export function checkGraphName(name: string): string | null {
  const n = name.trim();
  if (n === "") return "이름을 적어 주세요";
  if (n.length > 100) return "이름이 너무 길어요";
  if (BAD_NAME.test(n) || n.startsWith(".") || n.endsWith(".")) return "파일 이름에 쓸 수 없는 글자가 있어요";
  return null;
}

export function newGraphPath(kind: "test" | "subgraph", name: string): string {
  return `${kind === "test" ? "tests" : "subgraphs"}/${name.trim()}.graph.json`;
}

export async function createGraphInteractive(kind: "test" | "subgraph"): Promise<string | null> {
  const label = kind === "test" ? "새 테스트" : "새 서브그래프";
  let text = "";
  for (;;) {
    const r = await ask({
      title: label,
      input: { label: "이름", value: text, placeholder: kind === "test" ? "예: 로그인_확인" : "예: 월드_진입" },
      buttons: [
        { label: "만들기", value: "create", primary: true },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
      check: checkGraphName,
    });
    if (r.value !== "create") return null;
    text = r.text;
    const path = newGraphPath(kind, text);
    try {
      const result = await client().call("graph.create", { path, kind, title: text.trim() });
      adoptCreated(path, result);
      openTab({ path, kind: "graph", graphKind: kind });
      void refreshTree();
      return path;
    } catch (err) {
      const error = toRpcError(err);
      const message = error.kind === "exists" ? `'${path}'이(가) 이미 있어요` : `만들지 못했어요: ${error.message}`;
      // 같은 이름으로 대화 상자를 다시 띄우고 오류를 보인다
      queueMicrotask(() => setDialogError(message));
    }
  }
}
