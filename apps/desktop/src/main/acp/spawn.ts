// 에이전트 도우미 프로세스 띄우기 (Node child_process). 띄우는 것은 `kookabug agent-host`(acp/host.ts)이고, 도우미가
// 에이전트와 모든 자손을 Job 하나에 넣는다. stdout은 ACP 줄, stderr에는 도우미 자기 오류만 온다(에이전트 stderr는
// 도우미가 버린다) — 끝날 때 오류 줄에 붙인다
import { spawn } from "node:child_process";
import type { SpawnRequest } from "./host";
import type { AgentProcess } from "./session";

const STDERR_LIMIT = 2048;

export function spawnAgent(request: SpawnRequest): AgentProcess {
  const child = spawn(request.file, request.args, {
    cwd: request.cwd,
    env: request.env,
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  let stderr = "";
  child.stderr.on("data", (chunk: string) => {
    stderr = (stderr + chunk).slice(-STDERR_LIMIT);
  });
  let exitCb: (code: number | null, message: string) => void = () => {};
  let exited = false;
  const finish = (code: number | null, message: string) => {
    if (exited) return;
    exited = true;
    const detail = stderr.trim().replace(/^agent-host: /gm, "");
    exitCb(code, detail === "" ? message : `${message}: ${detail}`);
  };
  child.on("error", (err) => finish(null, `에이전트 실행 실패: ${err.message}`));
  // close = 프로세스가 끝나고 stdio가 닫힘 (도우미는 끝나기 전에 Job을 끝낸다 — 정리가 끝난 뒤다)
  child.on("close", (code, signal) =>
    finish(code, signal !== null ? `에이전트가 끝났어요 (${signal})` : `에이전트가 끝났어요 (종료 코드 ${code ?? "?"})`),
  );
  // 에이전트가 입력을 닫아도 주 프로세스가 죽지 않게
  child.stdin.on("error", () => {});
  return {
    write(line) {
      if (!child.stdin.destroyed) child.stdin.write(line);
    },
    onStdout(cb) {
      child.stdout.on("data", (chunk: string) => cb(chunk));
    },
    onExit(cb) {
      exitCb = cb;
    },
    kill() {
      // 도우미를 끝내면 Job 핸들이 닫혀(kill_on_close) 에이전트·자손이 함께 끝난다
      if (child.exitCode === null && child.signalCode === null) child.kill();
    },
  };
}
