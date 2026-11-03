// 스크린샷 줄의 칸 (M3 계획 2.10 "스크린샷 줄", 2.6 증거). 시안 "실행 전 · 대기 5초 · 시간 초과".
// - fail·error·stale_observation 스텝: step.end.evidence의 첫(_first)·중간(_mid)·마지막(_fail/_error). 중간은
//   최선 노력이라 없으면 그 칸에 "중간 장면 없음"을 쓴다 (2차 N3)
// - 증거가 없으면 썸네일(thumbs/<스텝>.jpg) 한 칸
// - 정책으로 남기지 않은 스크린샷·썸네일(step.end.omitted)은 시안 "정책으로 생략" 칸과 이유
// 후보 상자는 마지막 칸(_fail 이미지 좌표)에만 그린다
import type { events } from "@kookabug/schema";
import type { StepDetail, StepNode } from "./runIndexStore";

export type CellKind = "first" | "mid" | "last" | "thumb" | "omitted" | "missing";

export interface EvidenceCell {
  key: CellKind;
  label: string;
  /** 실행 폴더 기준 파일 (없으면 null) */
  file: string | null;
  /** 스텝 시작 기준 ms (모르면 null) */
  atMs: number | null;
  /** 칸에 쓸 이유 (생략·중간 장면 없음) */
  reason: string | null;
  /** 후보 상자를 이 칸에 그린다 */
  candidates: boolean;
}

const OMIT_REASON: Record<events.Omitted["reason"], string> = {
  policy_off: "기록 끔",
  secret_input: "비밀값 입력 스텝",
  capture_policy: "캡처 정책",
  sensitive_target: "민감한 영역",
};

/**
 * 생략 이유 글 (시안 "서브그래프 기록 끔"). source는 정책을 끈 층의 위치(`<파일>#/record`,
 * `<파일>#/nodes/<id>/record`, 워크스페이스는 kookabug.json)
 */
export function omittedText(o: events.Omitted, testGraph: string | null = null): string {
  const reason = OMIT_REASON[o.reason] ?? o.reason;
  if (o.reason !== "policy_off" || o.source === undefined) return reason;
  const [file, pointer = ""] = o.source.split("#");
  const where = pointer.startsWith("/nodes/")
    ? "노드"
    : file === "kookabug.json"
      ? "워크스페이스"
      : testGraph !== null && file === testGraph
        ? "테스트"
        : "서브그래프";
  return `${where} ${reason}`;
}

/** 실행 폴더 기준 파일 → kbimg 주소 (구간마다 인코딩) */
export function fileUrl(runDir: string, file: string): string {
  return `kbimg://ws/${`${runDir}/${file}`.split("/").map(encodeURIComponent).join("/")}`;
}

export interface Size {
  w: number;
  h: number;
}

/** object-fit: contain 으로 그린 그림의 상자 안 위치 (%) — 후보·차이 영역 상자를 그림 좌표에 맞춘다 */
export function fitted(img: Size, box: Size): { left: number; top: number; width: number; height: number } {
  const scale = Math.min(box.w / img.w, box.h / img.h);
  const w = img.w * scale;
  const h = img.h * scale;
  return { left: ((box.w - w) / 2 / box.w) * 100, top: ((box.h - h) / 2 / box.h) * 100, width: (w / box.w) * 100, height: (h / box.h) * 100 };
}

export function stepEnd(detail: StepDetail): events.StepEndEvent | null {
  const end = detail.events.find((e) => e.event === "step.end");
  return (end as events.StepEndEvent | undefined) ?? null;
}

/**
 * 증거 머리에 쓸 이유. 오류가 있는 step.end는 `code: message`(에디터 실행 결과 NodeResult와 같은 규칙),
 * 아니면 색인의 message. 상세를 아직 못 읽었으면 색인 message만
 */
export function headMessage(step: StepNode, detail: StepDetail | null): string | null {
  const end = detail === null ? null : stepEnd(detail);
  if (end?.error !== undefined) return `${end.error.code}: ${end.error.message}`;
  return step.message ?? end?.message ?? null;
}

function lastLabel(step: StepNode, end: events.StepEndEvent | null): string {
  if (end?.message?.startsWith("stale_observation") === true || step.message?.startsWith("stale_observation") === true) {
    return "오래된 관측";
  }
  if (step.status === "error") return "오류";
  if (step.exit === "timeout") return "시간 초과";
  return "실패";
}

function seconds(ms: number): string {
  const s = ms / 1000;
  return Number.isInteger(s) ? `${s}초` : `${s.toFixed(1)}초`;
}

/** 고른 스텝의 스크린샷 칸 */
export function evidenceCells(step: StepNode, detail: StepDetail, testGraph: string | null = null): EvidenceCell[] {
  const end = stepEnd(detail);
  const ev = end?.evidence;
  const omitted = (end?.omitted ?? step.omitted ?? []).filter((o) => o.kind === "screenshot" || o.kind === "thumbnail");
  const cells: EvidenceCell[] = [];
  if (ev !== undefined && (ev.first !== undefined || ev.last !== undefined || ev.mid !== undefined)) {
    if (ev.first !== undefined) {
      cells.push({ key: "first", label: "처음", file: ev.first, atMs: ev.first_at_ms ?? 0, reason: null, candidates: false });
    }
    if (typeof ev.mid === "string") {
      const at = ev.mid_at_ms ?? null;
      cells.push({
        key: "mid",
        label: at === null ? "중간" : `대기 ${seconds(at)}`,
        file: ev.mid,
        atMs: at,
        reason: null,
        candidates: false,
      });
    } else if (ev.mid === null || ev.mid_missing !== undefined) {
      cells.push({ key: "missing", label: "중간", file: null, atMs: null, reason: "중간 장면 없음", candidates: false });
    }
    if (ev.last !== undefined) {
      cells.push({
        key: "last",
        label: lastLabel(step, end),
        file: ev.last,
        atMs: ev.last_at_ms ?? null,
        reason: null,
        candidates: (ev.candidates?.length ?? 0) > 0,
      });
    }
  } else {
    // 증거가 없는 스텝: 실패 이미지(예전 실행)·썸네일
    const failed = (step.artifacts ?? end?.artifacts ?? []).find((a) => /_(fail|error)\.png$/.test(a));
    if (failed !== undefined) {
      cells.push({ key: "last", label: lastLabel(step, end), file: failed, atMs: null, reason: null, candidates: false });
    } else if (detail.thumbnail !== null) {
      cells.push({ key: "thumb", label: "마지막 화면", file: detail.thumbnail, atMs: null, reason: null, candidates: false });
    }
  }
  if (omitted.length > 0 && cells.every((c) => c.file === null)) {
    cells.unshift({
      key: "omitted",
      label: "정책으로 생략",
      file: null,
      atMs: null,
      reason: [...new Set(omitted.map((o) => omittedText(o, testGraph)))].join(" · "),
      candidates: false,
    });
  }
  return cells;
}

/** 매칭 후보 표 (시안 "매칭 후보 · <target> (임계값 0.80)") */
export function candidateRows(detail: StepDetail): { rank: number; score: number; x: number; y: number; scale: number; pass: boolean }[] {
  const ev = stepEnd(detail)?.evidence;
  const threshold = ev?.threshold ?? null;
  return (ev?.candidates ?? []).map((c, i) => ({
    rank: i + 1,
    score: c.score,
    x: c.rect[0],
    y: c.rect[1],
    scale: c.scale,
    pass: threshold !== null && c.score >= threshold,
  }));
}
