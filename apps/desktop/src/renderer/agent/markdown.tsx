// 에이전트 답의 마크다운 → React 요소. 에이전트 글은 믿지 않는 입력이라 HTML을 그대로 넣지 않고(dangerouslySetInnerHTML
// 없음) 아래 문법만 요소로 만든다. 받는 중인 글(닫히지 않은 코드 블록 등)도 그린다.
// - 블록: 제목(#~######), 문단(줄바꿈은 그대로), 코드 블록(``` ~~~), 인용(>), 목록(-·*·+·1. 겹침·[ ] [x]), 표(GFM), 가로줄
// - 줄 안: `코드`, **굵게**·__굵게__, *기울임*·_기울임_, ~~취소선~~, [글](주소)·http(s) 주소
// 링크는 창을 이동시키지 않게 누를 수 없는 글자로 두고 주소는 title로 보인다
import type { ReactNode } from "react";
import css from "./agent.module.css";

export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; lines: string[] }
  | { kind: "code"; lang: string; text: string }
  | { kind: "quote"; blocks: Block[] }
  | { kind: "list"; ordered: boolean; start: number; items: { task: boolean | null; blocks: Block[] }[] }
  | { kind: "table"; align: ("left" | "center" | "right" | null)[]; head: string[]; rows: string[][] }
  | { kind: "rule" };

const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([^`\s]*)/;
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^ {0,3}([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^ {0,3}>\s?(.*)$/;
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

function indentOf(line: string): number {
  const m = /^\s*/.exec(line);
  return m === null ? 0 : m[0].replace(/\t/g, "    ").length;
}

function cells(line: string): string[] {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|") && !t.endsWith("\\|")) t = t.slice(0, -1);
  return t.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

function startsBlock(line: string, next: string | undefined): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    QUOTE.test(line) ||
    ITEM.test(line) ||
    (line.includes("|") && next !== undefined && TABLE_SEP.test(next) && next.includes("-"))
  );
}

/** 마크다운 글 → 블록 */
export function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (line.trim() === "") {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence !== null) {
      const mark = fence[1]!;
      const body: string[] = [];
      i++;
      while (i < lines.length && !new RegExp(`^ {0,3}${mark[0] === "`" ? "`" : "~"}{${mark.length},}\\s*$`).test(lines[i]!)) {
        body.push(lines[i]!);
        i++;
      }
      i++; // 닫는 줄 (없으면 끝까지 — 받는 중)
      out.push({ kind: "code", lang: fence[2] ?? "", text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading !== null) {
      out.push({ kind: "heading", level: heading[1]!.length, text: heading[2]! });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      out.push({ kind: "rule" });
      i++;
      continue;
    }
    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (i < lines.length && lines[i]!.trim() !== "") {
        const q = QUOTE.exec(lines[i]!);
        body.push(q === null ? lines[i]! : q[1]!);
        i++;
      }
      out.push({ kind: "quote", blocks: parseBlocks(body.join("\n")) });
      continue;
    }
    const item = ITEM.exec(line);
    if (item !== null) {
      const base = indentOf(line);
      const ordered = /\d/.test(item[2]!);
      const list: Extract<Block, { kind: "list" }> = { kind: "list", ordered, start: ordered ? parseInt(item[2]!, 10) : 1, items: [] };
      while (i < lines.length) {
        const m = ITEM.exec(lines[i]!);
        if (m === null || indentOf(lines[i]!) !== base || /\d/.test(m[2]!) !== ordered) break;
        let first = m[3]!;
        let task: boolean | null = null;
        const t = /^\[([ xX])\]\s+(.*)$/.exec(first);
        if (t !== null) {
          task = t[1] !== " ";
          first = t[2]!;
        }
        const body = [first];
        i++;
        // 이어지는 줄: 더 들여 쓴 줄(겹친 목록·이어 쓴 글), 빈 줄 뒤라도 들여 쓰면 같은 항목
        while (i < lines.length) {
          const l = lines[i]!;
          if (l.trim() === "") {
            const nxt = lines[i + 1];
            if (nxt !== undefined && nxt.trim() !== "" && indentOf(nxt) > base) {
              body.push("");
              i++;
              continue;
            }
            break;
          }
          if (indentOf(l) > base) {
            body.push(l);
            i++;
            continue;
          }
          if (ITEM.test(l) || startsBlock(l, lines[i + 1])) break;
          body.push(l); // 들여 쓰지 않고 이어 쓴 글
          i++;
        }
        const rest = body.slice(1);
        const cut = Math.min(...rest.filter((l) => l.trim() !== "").map(indentOf), Infinity);
        const inner = [body[0]!, ...rest.map((l) => (cut === Infinity ? l : l.slice(Math.min(cut, indentOf(l)))))];
        list.items.push({ task, blocks: parseBlocks(inner.join("\n")) });
        // 항목 사이 빈 줄 하나는 같은 목록
        if (lines[i]?.trim() === "" && lines[i + 1] !== undefined) {
          const m2 = ITEM.exec(lines[i + 1]!);
          if (m2 !== null && indentOf(lines[i + 1]!) === base && /\d/.test(m2[2]!) === ordered) i++;
        }
      }
      out.push(list);
      continue;
    }
    const next = lines[i + 1];
    if (line.includes("|") && next !== undefined && TABLE_SEP.test(next) && next.includes("-")) {
      const head = cells(line);
      const align = cells(next).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : c.startsWith(":") ? "left" : null));
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i]!.includes("|") && lines[i]!.trim() !== "") {
        rows.push(cells(lines[i]!));
        i++;
      }
      out.push({ kind: "table", align, head, rows });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i]!.trim() !== "" && (para.length === 0 || !startsBlock(lines[i]!, lines[i + 1]))) {
      para.push(lines[i]!.trim());
      i++;
    }
    out.push({ kind: "paragraph", lines: para });
  }
  return out;
}

// ── 줄 안 ──────────────────────────────────────────────────────────

const URL_RE = /^https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"\]]/;

/** 줄 안 문법 → React 요소 */
export function renderInline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let buf = "";
  let n = 0;
  const flush = () => {
    if (buf !== "") out.push(buf);
    buf = "";
  };
  const push = (node: ReactNode) => {
    flush();
    out.push(node);
  };
  let i = 0;
  while (i < text.length) {
    const ch = text[i]!;
    const rest = text.slice(i);
    if (ch === "\\" && i + 1 < text.length && /[\\`*_~[\]()#>|!-]/.test(text[i + 1]!)) {
      buf += text[i + 1];
      i += 2;
      continue;
    }
    if (ch === "`") {
      const ticks = /^`+/.exec(rest)![0];
      const end = text.indexOf(ticks, i + ticks.length);
      if (end !== -1) {
        push(
          <code key={`${key}${n++}`} className={css.mdCode}>
            {text.slice(i + ticks.length, end).trim()}
          </code>,
        );
        i = end + ticks.length;
        continue;
      }
    }
    const strong = /^(\*\*|__)(?=\S)([\s\S]*?[^\s\\])\1/.exec(rest);
    if (strong !== null && (strong[1] === "**" || !/\w/.test(text[i - 1] ?? ""))) {
      push(<strong key={`${key}${n++}`}>{renderInline(strong[2]!, `${key}${n}s`)}</strong>);
      i += strong[0].length;
      continue;
    }
    const strike = /^~~(?=\S)([\s\S]*?[^\s\\])~~/.exec(rest);
    if (strike !== null) {
      push(<del key={`${key}${n++}`}>{renderInline(strike[1]!, `${key}${n}d`)}</del>);
      i += strike[0].length;
      continue;
    }
    const em = /^([*_])(?=\S)([\s\S]*?[^\s*_\\])\1(?![*_])/.exec(rest);
    if (em !== null && (em[1] === "*" || (!/\w/.test(text[i - 1] ?? "") && !/\w/.test(text[i + em[0].length] ?? "")))) {
      push(<em key={`${key}${n++}`}>{renderInline(em[2]!, `${key}${n}e`)}</em>);
      i += em[0].length;
      continue;
    }
    const link = /^\[([^\]]+)\]\(\s*<?([^\s)>]+)>?(?:\s+"[^"]*")?\s*\)/.exec(rest);
    if (link !== null) {
      push(
        <span key={`${key}${n++}`} className={css.mdLink} title={link[2]}>
          {renderInline(link[1]!, `${key}${n}l`)}
        </span>,
      );
      i += link[0].length;
      continue;
    }
    if ((ch === "h" || ch === "H") && !/\w/.test(text[i - 1] ?? "")) {
      const url = URL_RE.exec(rest);
      if (url !== null) {
        push(
          <span key={`${key}${n++}`} className={css.mdLink} title={url[0]}>
            {url[0]}
          </span>,
        );
        i += url[0].length;
        continue;
      }
    }
    buf += ch;
    i++;
  }
  flush();
  return out;
}

// ── 블록 그리기 ─────────────────────────────────────────────────────

function renderBlocks(blocks: readonly Block[], key: string): ReactNode[] {
  return blocks.map((b, idx) => {
    const k = `${key}-${idx}`;
    switch (b.kind) {
      case "heading": {
        const Tag = `h${Math.min(b.level + 2, 6)}` as "h3";
        return (
          <Tag key={k} className={css.mdHeading} data-level={b.level}>
            {renderInline(b.text, k)}
          </Tag>
        );
      }
      case "paragraph":
        return (
          <p key={k} className={css.mdPara}>
            {b.lines.flatMap((l, j) => (j === 0 ? renderInline(l, `${k}.${j}`) : [<br key={`${k}br${j}`} />, ...renderInline(l, `${k}.${j}`)]))}
          </p>
        );
      case "code":
        return (
          <pre key={k} className={css.mdPre} data-lang={b.lang || undefined}>
            <code>{b.text}</code>
          </pre>
        );
      case "quote":
        return (
          <blockquote key={k} className={css.mdQuote}>
            {renderBlocks(b.blocks, k)}
          </blockquote>
        );
      case "list": {
        const items = b.items.map((it, j) => (
          <li key={`${k}li${j}`} data-task={it.task === null ? undefined : it.task}>
            {it.task !== null && <span className={css.mdTask}>{it.task ? "☑" : "☐"}</span>}
            {renderBlocks(it.blocks, `${k}li${j}`)}
          </li>
        ));
        return b.ordered ? (
          <ol key={k} className={css.mdList} start={b.start === 1 ? undefined : b.start}>
            {items}
          </ol>
        ) : (
          <ul key={k} className={css.mdList}>
            {items}
          </ul>
        );
      }
      case "table":
        return (
          <div key={k} className={css.mdTableWrap}>
            <table className={css.mdTable}>
              <thead>
                <tr>
                  {b.head.map((c, j) => (
                    <th key={j} style={b.align[j] ? { textAlign: b.align[j]! } : undefined}>
                      {renderInline(c, `${k}h${j}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri}>
                    {b.head.map((_, j) => (
                      <td key={j} style={b.align[j] ? { textAlign: b.align[j]! } : undefined}>
                        {renderInline(r[j] ?? "", `${k}r${ri}c${j}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case "rule":
        return <hr key={k} className={css.mdRule} />;
    }
  });
}

/** 에이전트 답 본문 */
export function Markdown({ text }: { text: string }) {
  return <div className={css.md}>{renderBlocks(parseBlocks(text), "b")}</div>;
}
