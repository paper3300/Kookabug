// 에이전트 답 마크다운 (markdown.tsx): 블록·줄 안 문법, HTML은 글자 그대로, 받는 중인 글
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { Markdown, parseBlocks } from "./markdown";

const html = (text: string) => renderToStaticMarkup(<Markdown text={text} />).replace(/ class="[^"]*"/g, "");

describe("마크다운 블록", () => {
  test("제목·문단(줄바꿈 유지)·가로줄", () => {
    expect(html("### 녹화 쓰는 법\n첫 줄\n둘째 줄\n\n---")).toBe(
      '<div><h5 data-level="3">녹화 쓰는 법</h5><p>첫 줄<br/>둘째 줄</p><hr/></div>',
    );
  });

  test("코드 블록은 안을 해석하지 않고, 닫히지 않아도(받는 중) 그린다", () => {
    expect(html("```ts\nconst a = **b**;\n```")).toBe('<div><pre data-lang="ts"><code>const a = **b**;</code></pre></div>');
    expect(html("```\n받는 중")).toBe("<div><pre><code>받는 중</code></pre></div>");
  });

  test("목록: 겹침·번호 시작·할 일·이어 쓴 줄", () => {
    const blocks = parseBlocks("1. 하나\n   - 안쪽\n2. 둘\n   이어 씀\n\n- [x] 끝남\n- [ ] 남음");
    expect(blocks.map((b) => b.kind)).toEqual(["list", "list"]);
    const ol = blocks[0] as Extract<(typeof blocks)[number], { kind: "list" }>;
    expect(ol.ordered).toBe(true);
    expect(ol.items).toHaveLength(2);
    expect(ol.items[0]!.blocks.map((b) => b.kind)).toEqual(["paragraph", "list"]);
    expect(ol.items[1]!.blocks).toEqual([{ kind: "paragraph", lines: ["둘", "이어 씀"] }]);
    const ul = blocks[1] as Extract<(typeof blocks)[number], { kind: "list" }>;
    expect(ul.items.map((i) => i.task)).toEqual([true, false]);
    expect(html("3. 셋\n4. 넷")).toContain('<ol start="3">');
  });

  test("표·인용", () => {
    expect(html("| 이름 | 값 |\n|:--|--:|\n| a | `1` |")).toBe(
      '<div><div><table><thead><tr><th style="text-align:left">이름</th><th style="text-align:right">값</th></tr></thead>' +
        '<tbody><tr><td style="text-align:left">a</td><td style="text-align:right"><code>1</code></td></tr></tbody></table></div></div>',
    );
    expect(html("> 인용 **굵게**\n> 둘째")).toBe("<div><blockquote><p>인용 <strong>굵게</strong><br/>둘째</p></blockquote></div>");
  });
});

describe("마크다운 줄 안", () => {
  test("굵게·기울임·취소선·코드·링크·주소", () => {
    expect(html("**굵게** *기울임* ~~취소~~ `a*b*c` [문서](https://x.dev/a) https://y.dev/b.")).toBe(
      '<div><p><strong>굵게</strong> <em>기울임</em> <del>취소</del> <code>a*b*c</code> <span title="https://x.dev/a">문서</span> ' +
        '<span title="https://y.dev/b">https://y.dev/b</span>.</p></div>',
    );
  });

  test("낱말 안 밑줄·짝 없는 별표·이스케이프는 글자 그대로", () => {
    expect(html("snake_case_name 2*3 \\*별\\*")).toBe("<div><p>snake_case_name 2*3 *별*</p></div>");
  });

  test("HTML은 요소가 되지 않고 글자로 나온다", () => {
    expect(html('<img src=x onerror="alert(1)"> <b>굵게</b>')).toBe(
      "<div><p>&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &lt;b&gt;굵게&lt;/b&gt;</p></div>",
    );
  });
});
