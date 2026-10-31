// E2E가 쓰는 실제 daemon 도우미 (M2 계획 작업 크기 메모: daemon 띄우기 도우미는 이 파일 하나).
// 예제 워크스페이스를 임시 폴더에 복사하고, 앱이 띄운 daemon(레포 .venv의 kookabug daemon)을 검사 끝에 끈다
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type Page } from "@playwright/test";
import { REPO_ROOT } from "./app";

export const SAMPLE_WORKSPACE = path.join(REPO_ROOT, "fixtures", "sample-game", "workspace");

/** 예제 워크스페이스 사본. 폴더 이름이 탐색기 머리·경로 표시줄에 나온다 */
export function copySampleWorkspace(name = "sample-rpg"): string {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), "kb-ws-"));
  const root = path.join(parent, name);
  fs.cpSync(SAMPLE_WORKSPACE, root, { recursive: true });
  return root;
}

/**
 * 열린 워크스페이스 폴더를 통째로 복사한다 (살아 있는 daemon의 session.json까지). daemon이 쥔
 * daemon.lock은 공유 없이 열려 있어 복사하지 못하므로 뺀다. skip은 워크스페이스 기준 상대 경로
 */
export function copyWorkspaceFolder(src: string, name: string, skip: string[] = []): string {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), "kb-ws-"));
  const root = path.join(parent, name);
  const skipped = new Set([path.join(".kookabug", "daemon.lock"), ...skip.map((p) => path.normalize(p))]);
  fs.cpSync(src, root, { recursive: true, filter: (from) => !skipped.has(path.relative(src, from)) });
  return root;
}

/** 실제 경로 비교 (8.3 짧은 이름·대소문자) */
export function samePath(a: string, b: string): boolean {
  const real = (p: string) => fs.realpathSync.native(p).toLowerCase();
  return real(a) === real(b);
}

export interface SessionFile {
  pid: number;
  port: number;
  start_id: string;
  workspace: string;
}

export function readSession(root: string): SessionFile | null {
  try {
    return JSON.parse(fs.readFileSync(path.join(root, ".kookabug", "session.json"), "utf8")) as SessionFile;
  } catch {
    return null;
  }
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** daemon 프로세스를 죽인다 (잠금이 풀리고 session.json은 남는다) */
export async function killDaemon(root: string): Promise<SessionFile> {
  const session = readSession(root);
  if (session === null) throw new Error(`session.json이 없다: ${root}`);
  process.kill(session.pid);
  await expect.poll(() => alive(session.pid), { timeout: 10_000 }).toBe(false);
  return session;
}

/** 검사 끝: 남은 daemon을 끄고 사본을 지운다 (UI를 꺼도 daemon은 남는 것이 정상이라 직접 끈다) */
export async function cleanupWorkspace(root: string): Promise<void> {
  const session = readSession(root);
  if (session !== null && alive(session.pid)) {
    try {
      process.kill(session.pid);
    } catch {
      // 이미 끝남
    }
    await expect.poll(() => alive(session.pid), { timeout: 10_000 }).toBe(false);
  }
  // 끝난 프로세스의 파일 핸들은 조금 늦게 풀린다. 임시 폴더라 끝내 못 지워도 검사는 실패시키지 않는다
  const parent = path.dirname(root);
  for (let i = 0; i < 50; i++) {
    try {
      fs.rmSync(parent, { recursive: true, force: true });
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  console.warn(`임시 워크스페이스를 지우지 못했다: ${parent}`);
}

/** 상태 바가 daemon 연결됨을 보일 때까지 */
export async function waitConnected(page: Page, timeout = 30_000): Promise<void> {
  await expect(page.locator('[data-part="statusbar"] [data-status]')).toHaveAttribute("data-status", "connected", {
    timeout,
  });
}
