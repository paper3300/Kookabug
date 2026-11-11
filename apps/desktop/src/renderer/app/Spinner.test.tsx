// 진행 중 표시 (UX1 U1): 표시 지연·role=status·aria-busy·글
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { Spinner } from "./Spinner";

describe("Spinner", () => {
  test("지연 없이 켜면 role=status·aria-busy와 글", () => {
    const html = renderToStaticMarkup(<Spinner label="저장 중…" delay={0} />);
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("저장 중…");
  });

  test("글이 없으면 화면 읽기 프로그램용 '진행 중'", () => {
    expect(renderToStaticMarkup(<Spinner delay={0} />)).toContain("진행 중");
  });

  test("표시 지연 동안·꺼짐이면 아무것도 그리지 않는다 (짧은 일이 깜빡이지 않게)", () => {
    expect(renderToStaticMarkup(<Spinner label="x" />)).toBe("");
    expect(renderToStaticMarkup(<Spinner label="x" active={false} delay={0} />)).toBe("");
  });
});
