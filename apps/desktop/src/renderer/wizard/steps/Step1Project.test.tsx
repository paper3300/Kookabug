// UX10 D: 1단계 "위치" 칸에 경로를 직접 붙여 넣거나 입력한다 (찾아보기 유지). 없는 폴더·쓸 수 없는 위치는 만들기 때
// 주 프로세스 검사(checkCreateRequest)가 찾아보기와 같은 안내로 거부하고, 그 글이 칸 아래 오류로 보인다
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { appErrorText, canCreate, parentPath, Step1Project } from "./Step1Project";

describe("위치 칸 직접 입력", () => {
  test("붙여 넣은 경로: 앞뒤 공백·따옴표를 떼고 그대로 쓴다", () => {
    expect(parentPath("  D:\\Games\\Projects  ")).toBe("D:\\Games\\Projects");
    expect(parentPath('"D:\\Games\\My Projects"')).toBe("D:\\Games\\My Projects");
    expect(parentPath("\\\\server\\share\\qa")).toBe("\\\\server\\share\\qa");
    expect(parentPath('  ""  ')).toBe("");
  });

  test("직접 입력한 위치로 만들기 단추가 켜진다", () => {
    expect(canCreate("my-game", "D:\\Games")).toBe(true);
    expect(canCreate("my-game", "   ")).toBe(false);
    expect(canCreate("my-game", '""')).toBe(false);
    expect(canCreate("  ", "D:\\Games")).toBe(false);
  });

  test("위치 칸은 읽기 전용이 아니고 찾아보기 단추도 있다", () => {
    const html = renderToStaticMarkup(<Step1Project />);
    const field = html.match(/<input[^>]*aria-label="위치"[^>]*>/)?.[0] ?? "";
    expect(field).not.toBe("");
    expect(field).not.toContain("readOnly");
    expect(field).toContain("경로를 붙여 넣거나 폴더를 고르세요");
    expect(html).toContain("찾아보기");
  });

  test("만들기 때 검사의 거부 글이 그대로 안내된다", () => {
    const remote = new Error("Error invoking remote method 'kb:app': Error: parent_missing: 위치 폴더가 없어요");
    expect(appErrorText(remote)).toBe("위치 폴더가 없어요");
    const relative = new Error("Error invoking remote method 'kb:app': Error: invalid_parent: 위치는 절대 경로여야 해요");
    expect(appErrorText(relative)).toBe("위치는 절대 경로여야 해요");
  });
});
