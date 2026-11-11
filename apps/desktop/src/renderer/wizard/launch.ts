// 2단계 "실행 파일로 띄우기" 순수 판정 (UX1 T2): 인자 글 ↔ 인자 목록, 띄운 프로세스의 창 고르기, 실패 문구

/**
 * 인자 칸 글 → 인자 목록. 게임이 실제로 받는 Windows `CommandLineToArgvW` 규칙(첫 인자 뒤)을 따른다.
 * - 공백·탭으로 나누고, 큰따옴표 안의 공백은 한 인자다 (따옴표는 인자 중간에도: `-path="C:\My Game"`)
 * - 따옴표 앞 백슬래시 2n개 → n개 + 따옴표 열고 닫기, 2n+1개 → n개 + 글자 따옴표(`\"`)
 * - 따옴표 앞이 아닌 백슬래시는 그대로 (Windows 경로)
 * - `""`는 빈 인자 하나. 따옴표 안의 `""`는 글자 따옴표. 닫지 않은 따옴표는 글 끝까지 묶는다
 */
export function parseArgs(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let started = false;
  let backslashes = 0;
  let quotes = 0; // 0이 아니면 따옴표 안 (Wine CommandLineToArgvW의 qcount)
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if ((ch === " " || ch === "\t") && quotes === 0) {
      if (started) out.push(cur);
      cur = "";
      started = false;
      backslashes = 0;
      i += 1;
      continue;
    }
    started = true;
    if (ch === "\\") {
      cur += ch;
      backslashes += 1;
      i += 1;
      continue;
    }
    if (ch === '"') {
      if (backslashes % 2 === 0) {
        cur = cur.slice(0, cur.length - backslashes / 2);
        quotes += 1;
      } else {
        cur = cur.slice(0, cur.length - (backslashes + 1) / 2) + '"';
      }
      backslashes = 0;
      i += 1;
      while (line[i] === '"') {
        quotes += 1;
        if (quotes === 3) {
          cur += '"';
          quotes = 0;
        }
        i += 1;
      }
      if (quotes === 2) quotes = 0;
      continue;
    }
    cur += ch;
    backslashes = 0;
    i += 1;
  }
  if (started) out.push(cur);
  return out;
}

/**
 * 인자 목록 → 인자 칸 글. `parseArgs`로 되읽으면 같은 목록이다 (Windows 인자 따옴표 규칙: 공백·따옴표가
 * 있거나 빈 인자는 따옴표로 묶고, 따옴표 앞·끝의 백슬래시는 두 배, 글자 따옴표는 `\"`)
 */
export function formatArgs(args: readonly string[]): string {
  return args.map(quoteArg).join(" ");
}

function quoteArg(arg: string): string {
  if (arg !== "" && !/[\s"]/.test(arg)) return arg;
  let out = '"';
  let backslashes = 0;
  for (const ch of arg) {
    if (ch === "\\") {
      backslashes += 1;
      continue;
    }
    if (ch === '"') out += "\\".repeat(backslashes * 2 + 1) + '"';
    else out += "\\".repeat(backslashes) + ch;
    backslashes = 0;
  }
  return out + "\\".repeat(backslashes * 2) + '"';
}

/** 화면을 연 때 읽은 이 PC 실행 설정 (칸을 채운 값) */
export interface StoredLaunch {
  executable: string | null;
  args: string[] | null;
}

/** 저장된 인자 배열로 채우는 칸 글 */
export function storedArgsText(stored: StoredLaunch): string {
  return stored.args === null ? "" : formatArgs(stored.args);
}

/** `local.settings.set`에 넘길 이 PC 실행 설정 (빠진 키는 파일 값 그대로, null이면 지움) */
export interface LaunchSettings {
  "game.executable"?: string;
  "game.args"?: string[] | null;
  "game.cwd"?: string | null;
}

/**
 * 칸 → 저장할 이 PC 실행 설정. 고친 칸의 키만 쓴다: 실행 파일 칸을 고쳤으면 실행 파일·작업 폴더(실행 파일 폴더),
 * 인자 칸을 고쳤으면 인자. 손으로 정한 작업 폴더는 실행 파일을 바꿀 때만 바뀐다. 둘 다 그대로면 null(쓰지 않는다)
 */
export function launchSettings(stored: StoredLaunch, exe: string, args: string): LaunchSettings | null {
  const exeSame = stored.executable !== null && exe === stored.executable;
  const argsSame = args === storedArgsText(stored);
  if (exeSame && argsSame) return null;
  const out: LaunchSettings = {};
  if (!exeSame) {
    const path = exe.trim();
    out["game.executable"] = path;
    out["game.cwd"] = exeFolder(path);
  }
  if (!argsSame) {
    const argv = parseArgs(args);
    out["game.args"] = argv; // 빈 칸 = 인자 없음([]): null이면 팀 인자가 다시 살아난다 (UX1 검수 3 M1)
  }
  return out;
}

/** 실행 파일 경로의 폴더 (작업 폴더로 쓴다). 폴더가 없는 이름뿐이면 null */
export function exeFolder(path: string): string | null {
  const p = path.trim();
  const i = Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"));
  if (i <= 0) return null;
  // "C:\Game.exe" → "C:\" (드라이브 뿌리는 구분자까지)
  return /^[A-Za-z]:$/.test(p.slice(0, i)) ? p.slice(0, i + 1) : p.slice(0, i);
}

/** 경로의 파일 이름 (소문자) */
export function exeName(path: string): string {
  const p = path.trim();
  return p.slice(Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/")) + 1).toLowerCase();
}

export interface LaunchWindow {
  handle: number;
  pid: number;
  process: string;
  title: string;
}

/**
 * 띄운 게임의 창: 그 PID의 창, 없으면 같은 실행 파일 이름의 창 가운데 띄우기 전에 없던 것(런처가 게임을 따로
 * 띄우는 경우). 제목이 빈 창과 Kookabug 창은 뺀다
 */
export function launchedWindows<W extends LaunchWindow>(
  windows: readonly W[],
  pid: number,
  exe: string,
  before: ReadonlySet<number>,
): W[] {
  const usable = windows.filter((w) => w.title.trim() !== "" && !/^Kookabug/.test(w.title));
  const own = usable.filter((w) => w.pid === pid);
  if (own.length > 0) return own;
  const name = exeName(exe);
  if (name === "") return [];
  return usable.filter((w) => w.process.toLowerCase() === name && !before.has(w.handle));
}

/** 창을 기다리는 상한 (ms) */
export const LAUNCH_WAIT_MS = 120_000;
/** windows.list를 되풀이하는 간격 (ms) */
export const LAUNCH_POLL_MS = 1_000;

/** 띄우기 실패 문구: 경로 없음·실행 실패·시간 초과·그 밖 */
export function launchErrorText(code: string | undefined, message: string): string {
  if (code === "exe_missing") return "실행 파일 경로를 입력해 주세요";
  if (code === "timeout") return "2분 안에 게임 창이 뜨지 않았어요. 게임이 떴다면 \"떠 있는 창 고르기\"에서 골라 주세요";
  if (code === "run_busy") return "테스트 실행 중이라 띄우지 않았어요. 실행이 끝난 뒤 다시 해 주세요";
  if (code === "recording_active") return "녹화 중이라 띄우지 않았어요";
  if (code === "job_active") return "무인 작업이 도는 중이라 띄우지 않았어요";
  if (code === "verification_active") return "자동 채택 검증이 도는 중이라 띄우지 않았어요. 검증이 끝난 뒤 다시 해 주세요";
  if (/WinError 2\b|No such file|cannot find|지정된 파일을 찾을 수 없/i.test(message)) {
    return "실행 파일을 찾지 못했어요. 경로를 확인해 주세요";
  }
  if (code === "launch_failed") return `게임을 실행하지 못했어요: ${message}`;
  return `게임을 띄우지 못했어요: ${message}`;
}
