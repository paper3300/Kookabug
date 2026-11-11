// 2단계 "실행 파일로 띄우기" 순수 판정 (UX1 T2): 인자 나누기·되돌리기, 작업 폴더, 띄운 창 고르기, 실패 문구
import { describe, expect, test } from "vitest";
import {
  exeFolder,
  exeName,
  formatArgs,
  launchedWindows,
  launchErrorText,
  launchSettings,
  parseArgs,
  storedArgsText,
} from "./launch";

describe("인자 나누기", () => {
  test("공백으로 나누고 큰따옴표로 묶은 공백 포함 인자는 하나", () => {
    expect(parseArgs('-windowed -config "C:\\My Game\\user.ini"')).toEqual(["-windowed", "-config", "C:\\My Game\\user.ini"]);
    expect(parseArgs("  a   b\tc  ")).toEqual(["a", "b", "c"]);
    expect(parseArgs("")).toEqual([]);
    expect(parseArgs("   ")).toEqual([]);
  });

  test("인자 중간의 따옴표·빈 인자·닫지 않은 따옴표", () => {
    expect(parseArgs('-path="C:\\My Game" -x')).toEqual(["-path=C:\\My Game", "-x"]);
    expect(parseArgs('a "" b')).toEqual(["a", "", "b"]);
    expect(parseArgs('-name "two words')).toEqual(["-name", "two words"]);
    // 백슬래시는 그대로 (Windows 경로)
    expect(parseArgs("C:\\Games\\a.ini")).toEqual(["C:\\Games\\a.ini"]);
  });

  test("formatArgs → parseArgs는 같은 목록", () => {
    const cases = [
      ["-windowed"],
      ["-config", "C:\\My Game\\user.ini"],
      ["a", "", "b"],
      [],
      [""],
      // 검수 재현(H2): 따옴표 포함 JSON
      ['--payload={"mode":"qa"}'],
      ['{"path":"C:\\\\My Game\\\\"}'],
      // 끝 백슬래시 (공백 있음·없음), 따옴표 앞 백슬래시
      ["C:\\My Game\\", "C:\\Games\\", "-x"],
      ['a\\"b', 'a\\\\"b', '\\"', "\\\\", '"', '""'],
      // 공백·탭
      ["two  spaces", "tab\there", " lead", "trail "],
    ];
    for (const args of cases) expect(parseArgs(formatArgs(args))).toEqual(args);
    expect(formatArgs(["-config", "C:\\My Game\\a.ini"])).toBe('-config "C:\\My Game\\a.ini"');
    expect(formatArgs(["", "C:\\Games\\"])).toBe('"" C:\\Games\\');
    expect(formatArgs(['--payload={"mode":"qa"}'])).toBe('"--payload={\\"mode\\":\\"qa\\"}"');
    expect(formatArgs(["C:\\My Game\\"])).toBe('"C:\\My Game\\\\"');
  });

  test("Windows CommandLineToArgvW 규칙", () => {
    // 따옴표 앞 백슬래시 2n → n개 + 따옴표 묶기, 2n+1 → n개 + 글자 따옴표
    expect(parseArgs('a\\\\"b c"')).toEqual(["a\\b c"]);
    expect(parseArgs('a\\"b c')).toEqual(['a"b', "c"]);
    expect(parseArgs('a\\\\\\"b')).toEqual(['a\\"b']);
    // 따옴표 앞이 아닌 백슬래시는 그대로
    expect(parseArgs("a\\\\b")).toEqual(["a\\\\b"]);
    // 따옴표 안의 "" 는 글자 따옴표
    expect(parseArgs('"a""b"')).toEqual(['a"b']);
  });
});

describe("이 PC 실행 설정 저장", () => {
  const stored = { executable: "C:\\Games\\Game.exe", args: ['--payload={"mode":"qa"}', ""] };

  test("칸을 고치지 않았으면 다시 쓰지 않는다", () => {
    expect(launchSettings(stored, stored.executable, storedArgsText(stored))).toBeNull();
    expect(launchSettings({ executable: "C:\\G.exe", args: null }, "C:\\G.exe", "")).toBeNull();
  });

  test("실행 파일 칸만 고쳤으면 실행 파일·작업 폴더만 쓴다 (인자는 쓰지 않는다)", () => {
    const got = launchSettings(stored, "D:\\Other\\Game.exe", storedArgsText(stored));
    expect(got).toEqual({ "game.executable": "D:\\Other\\Game.exe", "game.cwd": "D:\\Other" });
  });

  test("인자 칸만 고쳤으면 game.args만 쓴다 (사람이 정한 작업 폴더를 덮지 않는다)", () => {
    const got = launchSettings(stored, stored.executable, '-x "a b"');
    expect(got).toEqual({ "game.args": ["-x", "a b"] });
    expect(launchSettings(stored, stored.executable, "")).toEqual({ "game.args": [] });
  });

  test("두 칸 다 고쳤으면 셋 다 쓴다", () => {
    const got = launchSettings(stored, "D:\\Other\\Game.exe", "-new");
    expect(got).toEqual({ "game.executable": "D:\\Other\\Game.exe", "game.args": ["-new"], "game.cwd": "D:\\Other" });
  });

  test("저장된 설정이 없으면 칸 값으로", () => {
    const got = launchSettings({ executable: null, args: null }, " C:\\G\\g.exe ", "");
    expect(got).toEqual({ "game.executable": "C:\\G\\g.exe", "game.cwd": "C:\\G" });
  });
});

describe("작업 폴더·실행 파일 이름", () => {
  test("실행 파일 폴더", () => {
    expect(exeFolder("C:\\Games\\MyGame\\Game.exe")).toBe("C:\\Games\\MyGame");
    expect(exeFolder("C:/Games/Game.exe")).toBe("C:/Games");
    expect(exeFolder("C:\\Game.exe")).toBe("C:\\");
    expect(exeFolder("Game.exe")).toBeNull();
    expect(exeName(" C:\\Games\\MyGame\\Game.EXE ")).toBe("game.exe");
  });
});

describe("띄운 게임의 창", () => {
  const w = (handle: number, pid: number, process: string, title = "Game") => ({ handle, pid, process, title });

  test("그 PID의 창이 먼저 (Kookabug·제목 없는 창은 빼고)", () => {
    const list = [w(1, 10, "other.exe"), w(2, 20, "game.exe"), w(3, 20, "game.exe", ""), w(4, 20, "game.exe", "Kookabug")];
    expect(launchedWindows(list, 20, "C:\\g\\game.exe", new Set()).map((x) => x.handle)).toEqual([2]);
  });

  test("PID 창이 없으면 같은 실행 파일의 새 창 (런처가 따로 띄움), 띄우기 전 창은 빼고", () => {
    const list = [w(1, 10, "Game.exe"), w(2, 30, "game.exe"), w(5, 31, "game.exe")];
    expect(launchedWindows(list, 20, "C:\\g\\game.exe", new Set([1])).map((x) => x.handle)).toEqual([2, 5]);
    expect(launchedWindows(list, 20, "", new Set())).toEqual([]);
  });
});

describe("실패 문구", () => {
  test("경로 없음·실행 실패·시간 초과", () => {
    expect(launchErrorText("exe_missing", "")).toContain("실행 파일 경로");
    expect(launchErrorText("launch_failed", "게임을 띄우지 못했다: [WinError 2] 지정된 파일을 찾을 수 없습니다")).toContain("찾지 못했어요");
    expect(launchErrorText("launch_failed", "게임을 띄우지 못했다: [WinError 5] 액세스가 거부되었습니다")).toContain("실행하지 못했어요");
    expect(launchErrorText("timeout", "")).toContain("2분 안에");
    expect(launchErrorText("run_busy", "x")).toContain("테스트 실행 중");
    // 작업·검증·녹화 중 거부 (UX1 검수 M2 — daemon이 사람 띄우기도 막는다)
    expect(launchErrorText("job_active", "x")).toBe("무인 작업이 도는 중이라 띄우지 않았어요");
    expect(launchErrorText("verification_active", "x")).toContain("검증이 도는 중");
    expect(launchErrorText("recording_active", "x")).toBe("녹화 중이라 띄우지 않았어요");
  });
});
