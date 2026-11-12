// 6단계 "Agent가 읽어도 되는 폴더" 묶음 (UX3): 여러 줄, 자동 포함 줄(고칠 수 없음·거부 경고), 저장 거부 이유
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { RpcError } from "../rpc/client";
import { initialRootRows, READ_ROOTS_NOTE, ReadRootsGroup, rootErrorText, rootsChanged, rootsToSave, type AutoRoot } from "./readRoots";

const noop = () => undefined;
const GAME: AutoRoot = { id: "read:game", path: "D:\\Games\\Sample", title: "게임 실행 파일 폴더(자동)", state: "ok", reason: null, message: null };

function render(rows: string[], auto: AutoRoot[] = [GAME], error: string | null = null): string {
  return renderToStaticMarkup(
    <ReadRootsGroup rows={rows} auto={auto} error={error} disabled={false} onChange={noop} onAdd={noop} onRemove={noop} onPick={noop} />,
  );
}

describe("읽기 허용 폴더 줄", () => {
  test("저장된 목록 → 줄, 빈 줄은 저장에서 뺀다", () => {
    expect(initialRootRows([])).toEqual([""]);
    expect(initialRootRows(["D:/Tools", "E:/Servers"])).toEqual(["D:/Tools", "E:/Servers"]);
    expect(rootsToSave([" D:/Tools ", "", "  ", "E:/Servers"])).toEqual(["D:/Tools", "E:/Servers"]);
    expect(rootsChanged([], [""])).toBe(false);
    expect(rootsChanged(["D:/Tools"], ["D:/Tools", ""])).toBe(false);
    expect(rootsChanged(["D:/Tools"], ["D:/Tools", "E:/Servers"])).toBe(true);
    expect(rootsChanged(["D:/Tools", "E:/Servers"], ["E:/Servers", "D:/Tools"])).toBe(true);
  });

  test("여러 줄과 + 추가·찾아보기·− 단추, 설명 한 줄", () => {
    const html = render(["D:\\Tools", "E:\\Servers"]);
    expect(html.match(/data-part="read-root"/g)).toHaveLength(2);
    expect(html).toContain('value="D:\\Tools"');
    expect(html).toContain('value="E:\\Servers"');
    expect(html).toContain('data-part="read-root-add"');
    expect(html.match(/data-part="read-root-pick"/g)).toHaveLength(2);
    expect(html.match(/data-part="read-root-remove"/g)).toHaveLength(2);
    expect(html).toContain(READ_ROOTS_NOTE);
    expect(READ_ROOTS_NOTE).toBe("여기 넣은 폴더 아래 파일은 Agent(외부 AI 서비스)에게 보일 수 있어요. 비밀값은 가리지만 민감한 폴더는 넣지 마세요.");
  });

  test("자동 포함 줄은 읽기 전용, 허용하지 않는 폴더면 뺐다는 경고", () => {
    const html = render([""]);
    expect(html).toMatch(/data-part="read-root-auto"[^>]*data-root="read:game"[^>]*data-state="ok"/);
    expect(html).toContain("게임 실행 파일 폴더(자동)");
    expect(html).toMatch(/aria-label="게임 실행 파일 폴더\(자동\)" readOnly="" value="D:\\Games\\Sample"/);
    expect(html).not.toContain("read-root-auto-warn");
    const refused = render([""], [{ ...GAME, state: "refused", reason: "contains_workspace", message: "워크스페이스를 품는 폴더는 쓸 수 없다" }]);
    expect(refused).toContain('data-part="read-root-auto-warn"');
    expect(refused).toContain("자동 포함에서 뺐어요 — 워크스페이스를 품는 폴더는 쓸 수 없다");
    expect(render([""], [{ ...GAME, state: "missing" }])).toContain("폴더가 없어요");
    expect(render([""], [])).not.toContain("read-root-auto");
  });

  test("저장 거부 이유를 그대로, 몇째 줄인지 (빈 줄 건너뛴 번호를 화면 줄로)", () => {
    const err = new RpcError(-32100, "드라이브 루트는 읽기 허용 폴더로 쓸 수 없다", { code: "policy_path", reason: "drive_root", index: 1 });
    const text = rootErrorText(err, ["D:/Tools", "", "C:\\"]);
    expect(text).toBe("3번째 폴더를 저장하지 않았어요: 드라이브 루트는 읽기 허용 폴더로 쓸 수 없다");
    expect(rootErrorText(new RpcError(-32100, "그 폴더가 없다", { code: "policy_path", reason: "missing" }), ["x"])).toBe(
      "저장하지 않았어요: 그 폴더가 없다",
    );
    expect(rootErrorText(new RpcError(-32000, "끊겼다", {}), ["x"])).toBe("끊겼다");
    const html = render(["C:\\"], [GAME], text);
    expect(html).toMatch(/role="alert"[^>]*data-part="read-roots-error"/);
    expect(html).toContain("3번째 폴더를 저장하지 않았어요");
  });
});
