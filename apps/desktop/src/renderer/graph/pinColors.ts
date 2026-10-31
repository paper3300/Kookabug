// 핀 색 표 (M2 계획 2.7 "핀 색"). 타입 → 색 토큰 이름. 값은 tokens.css의 다크·라이트 두 벌이다
// (시안 Main·MainLight의 데이터 핀·연결선 색)
//   창 window · 정수·수 number · 이미지 image(찾기 대상 target 포함) · 영역·점·match region · 글자 text
//   흐름 핀 exec(삼각형), fail 출구 fail, 그 밖 other(회색)

export type PinTone = "exec" | "fail" | "window" | "number" | "image" | "region" | "text" | "other";

const BASE: Record<string, PinTone> = {
  window: "window",
  int: "number",
  float: "number",
  number: "number",
  image: "image",
  target: "image",
  rect: "region",
  point: "region",
  match: "region",
  string: "text",
  secret: "text",
};

/** 노드 스키마 핀 타입(`int`, `string|secret`, `list[point]`, `dict[str,target]`) → 색 */
export function pinTone(type: string): PinTone {
  for (const part of type.split("|")) {
    const t = part.trim();
    const inner = /^(?:list|dict)\[(.*)\]$/.exec(t);
    if (inner !== null) {
      // dict[str,X]의 값 타입, list[X]의 원소 타입
      const args = inner[1];
      const comma = args.indexOf(",");
      const tone = pinTone(comma < 0 ? args : args.slice(comma + 1));
      if (tone !== "other") return tone;
      continue;
    }
    const tone = BASE[t];
    if (tone !== undefined) return tone;
  }
  return "other";
}

export function pinColor(tone: PinTone): string {
  return `var(--kb-pin-${tone})`;
}
