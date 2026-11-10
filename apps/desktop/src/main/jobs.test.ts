// 마법사·보고함 메인 IPC (M8 B7, jobs.ts·ipc-guard.ts): 렌더러가 실행 파일·인자를 넘기지 못하고, 명령줄은 셸 없는
// 인자 배열이며, 플레이북·경로·Agent는 허용 목록·정규화를 지난다. CLI 출력은 정해진 필드만
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { APP_ACTIONS, checkJobArgs, IpcGuardError, RENDERER_EVENTS, RENDERER_METHODS } from "./ipc-guard";
import {
  checkCreateRequest,
  checkProjectName,
  JobRunner,
  JobsError,
  nodeExec,
  pickDoctor,
  pickResult,
  pickRunningJob,
  type ExecOutcome,
} from "./jobs";

const ROOT = path.resolve("C:/ws/game");

function runner(over: Partial<ConstructorParameters<typeof JobRunner>[0]> = {}) {
  const calls: { file: string; args: string[] }[] = [];
  const emitted: unknown[] = [];
  let finish: ((o: ExecOutcome) => void) | null = null;
  const r = new JobRunner({
    cli: () => "C:/app/bin/kookabug.exe",
    root: () => ROOT,
    agentIds: async () => ["claude-code", "codex", "custom-x"],
    exec: async (file, args) => {
      calls.push({ file, args });
      return { code: 0, stdout: '{"exit_code":0,"probe_ok":true,"token":"SECRET","message":"C:/Users/me/x"}\n' };
    },
    spawn: (file, args, onExit) => {
      calls.push({ file, args });
      finish = onExit;
      return { done: new Promise<void>(() => {}), killTree: () => {} };
    },
    emit: (x) => emitted.push(x),
    override: null,
    ...over,
  });
  return { r, calls, emitted, finish: (o: ExecOutcome) => finish?.(o) };
}

describe("ipc-guard 새 채널", () => {
  test("앱 동작·알림·렌더러 메서드가 등록돼 있다", () => {
    for (const a of ["pickFolder", "workspaceCreate", "agentProbe", "agentJobRun", "doctor"]) expect(APP_ACTIONS.has(a)).toBe(true);
    for (const n of ["job.changed", "job.budget", "reports.changed", "knowledge.changed"]) expect(RENDERER_EVENTS.has(n)).toBe(true);
    for (const m of ["report.decide", "adopt.revert", "unknowns.answer", "job.end", "wizard.set"]) expect(RENDERER_METHODS.has(m)).toBe(true);
    // Agent만 쓰는 쓰기·작업 토큰 쪽은 렌더러에 없다
    for (const m of ["knowledge.apply", "wiki.write", "cases.open", "cases.update", "adopt.request", "job.begin", "job.finish", "job.note", "job.heartbeat", "cheats.adopt"]) {
      expect(RENDERER_METHODS.has(m)).toBe(false);
    }
  });

  test("인자 모양 거부 (양성 대조: 맞는 모양은 지나간다)", () => {
    expect(() => checkJobArgs("agentJobRun", ["init", "claude-code"])).not.toThrow();
    expect(() => checkJobArgs("workspaceCreate", [{ parent: "C:/x", name: "a", git: true }])).not.toThrow();
    const bad: [string, unknown[]][] = [
      ["agentJobRun", ["repair", "claude-code"]], // 허용 목록 밖 플레이북
      ["agentJobRun", ["init", "claude code"]], // 공백
      ["agentJobRun", ["init", "--agent-command"]], // 옵션처럼 보이는 값
      ["agentJobRun", ["init", "a", "--agent-command=calc"]], // 인자 더하기
      ["agentProbe", ['"x"']],
      ["agentProbe", ["../x"]],
      ["workspaceCreate", [{ parent: "C:/x", name: "a", git: true, command: "calc" }]],
      ["workspaceCreate", ["C:/x"]],
      ["doctor", ["--profile", "x"]],
      ["pickFolder", ["C:/"]],
    ];
    for (const [action, args] of bad) expect(() => checkJobArgs(action, args), `${action} ${JSON.stringify(args)}`).toThrow(IpcGuardError);
  });
});

describe("프로젝트 만들기 요청", () => {
  const fsLike = {
    realpath: (p: string) => (p.toLowerCase().includes("junction") ? path.resolve("D:/real") : path.resolve(p)),
    isDir: (p: string) => !p.includes("missing"),
    exists: (p: string) => p.endsWith("taken"),
    isLink: () => false,
    isEmptyDir: () => false,
  };

  test("이름 거부: 경로 글자·옵션·예약어·앞뒤 공백·점", () => {
    for (const name of ["a/b", "a\\b", "..", ".hidden", "-x", "--name=x", "con", "NUL.txt", " a", "a ", "a.", 'a"b', "a:b", ""]) {
      expect(() => checkProjectName(name), name).toThrow(JobsError);
    }
    expect(checkProjectName("샘플 게임")).toBe("샘플 게임");
  });

  test("위치: 절대 경로만, '..' 거부, 정션은 실제 폴더 아래로", () => {
    expect(() => checkCreateRequest({ parent: "rel/dir", name: "a", git: false }, fsLike)).toThrow(JobsError);
    expect(() => checkCreateRequest({ parent: "C:/a/../b", name: "a", git: false }, fsLike)).toThrow(JobsError);
    expect(() => checkCreateRequest({ parent: "C:/missing", name: "a", git: false }, fsLike)).toThrow(JobsError);
    expect(() => checkCreateRequest({ parent: "C:/p", name: "taken", git: false }, fsLike)).toThrow(/비어 있지 않아요/);
    expect(checkCreateRequest({ parent: "C:/junction", name: "a", git: true }, fsLike).folder).toBe(path.join(path.resolve("D:/real"), "a"));
  });

  test("CLI는 셸 없는 인자 배열, 이름은 --name=으로 붙인다", async () => {
    const { calls } = runner();
    const r = new JobRunner({
      cli: () => "C:/app/bin/kookabug.exe",
      root: () => null,
      agentIds: async () => [],
      exec: async (file, args) => {
        calls.push({ file, args });
        return { code: 0, stdout: '{"exit_code":0,"root":"C:/x"}' };
      },
      spawn: () => ({ done: Promise.resolve(), killTree: () => {} }),
      emit: () => {},
      override: null,
    });
    // 실제 파일 시스템: 임시 폴더 아래
    const os = await import("node:os");
    await r.createWorkspace({ parent: os.tmpdir(), name: "kb-b7-unit", git: true });
    expect(calls[0].args.slice(0, 2)).toEqual(["workspace", "new"]);
    expect(calls[0].args).toContain("--name=kb-b7-unit");
    expect(calls[0].args).toContain("--git");
  });
});

// 실제 CLI (레포 venv): 검수 재현처럼 검사 결과를 그대로 `workspace new`에 넘긴다
const VENV_PYTHON = path.resolve(import.meta.dirname, "../../../../.venv/Scripts/python.exe");
const realCli = process.platform === "win32" && fs.existsSync(VENV_PYTHON);

describe("검수 재현 B7-1", () => {
  test.skipIf(!realCli)("review_create_refuses_existing_child_junction", async () => {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), "kb-b7-junction-"));
    try {
      const selected = path.join(base, "selected");
      const outside = path.join(base, "outside");
      fs.mkdirSync(selected);
      fs.mkdirSync(outside);
      fs.symlinkSync(outside, path.join(selected, "game"), "junction");
      const exec = nodeExec(process.env);
      const r = new JobRunner({
        cli: () => VENV_PYTHON,
        root: () => null,
        agentIds: async () => [],
        exec: (file, args, timeoutMs) => exec(file, ["-X", "utf8", "-m", "kookabug_cli", ...args], timeoutMs),
        spawn: () => ({ done: Promise.resolve(), killTree: () => {} }),
        emit: () => {},
        override: null,
      });
      await expect(r.createWorkspace({ parent: selected, name: "game", git: false })).rejects.toBeInstanceOf(JobsError);
      expect(fs.existsSync(path.join(outside, "kookabug.json"))).toBe(false);
      expect(fs.readdirSync(outside)).toEqual([]);
      // 양성 대조: 같은 위치의 새 폴더는 만든다
      const made = await r.createWorkspace({ parent: selected, name: "plain", git: false });
      expect(fs.existsSync(path.join(made.folder, "kookabug.json"))).toBe(true);
    } finally {
      fs.rmSync(base, { recursive: true, force: true });
    }
  }, 120_000);

  test("검사: 이미 있는 대상이 링크이거나 실제 위치가 부모의 직접 하위가 아니면 거부", () => {
    const fsLike = {
      realpath: (p: string) => (p.endsWith("moved") ? path.resolve("D:/elsewhere/moved") : path.resolve(p)),
      isDir: () => true,
      exists: (p: string) => p.endsWith("link") || p.endsWith("moved") || p.endsWith("empty"),
      isLink: (p: string) => p.endsWith("link"),
      isEmptyDir: () => true,
    };
    expect(() => checkCreateRequest({ parent: "C:/p", name: "link", git: false }, fsLike)).toThrow(JobsError);
    expect(() => checkCreateRequest({ parent: "C:/p", name: "moved", git: false }, fsLike)).toThrow(JobsError);
    // 양성 대조: 일반 빈 폴더·없는 폴더
    expect(checkCreateRequest({ parent: "C:/p", name: "empty", git: false }, fsLike).folder).toBe(path.join(path.resolve("C:/p"), "empty"));
    expect(checkCreateRequest({ parent: "C:/p", name: "new", git: false }, fsLike).folder).toBe(path.join(path.resolve("C:/p"), "new"));
  });

  test("review_concurrent_probe_spawns_once: 동시 두 번이면 CLI 1번, 오류 뒤에는 다시", async () => {
    let calls = 0;
    let fail = false;
    let ids = 0;
    const r = new JobRunner({
      cli: () => "C:/app/bin/kookabug.exe",
      root: () => ROOT,
      agentIds: async () => {
        ids++;
        if (fail) throw new Error("daemon 끊김");
        return ["codex"];
      },
      exec: async () => {
        calls++;
        await new Promise((res) => setTimeout(res, 20));
        return { code: 0, stdout: '{"probe_ok":true}' };
      },
      spawn: () => ({ done: Promise.resolve(), killTree: () => {} }),
      emit: () => {},
      override: null,
    });
    const both = await Promise.allSettled([r.probe("codex"), r.probe("codex")]);
    expect(calls).toBe(1);
    expect(both.map((b) => b.status).sort()).toEqual(["fulfilled", "rejected"]);
    expect(both.find((b) => b.status === "rejected")).toMatchObject({ reason: { code: "probe_active" } });
    // 첫 await(agentIds)에서 실패해도 놓는다 → 다시 시작할 수 있다
    fail = true;
    await expect(r.probe("codex")).rejects.toThrow("daemon 끊김");
    fail = false;
    await expect(r.probe("codex")).resolves.toMatchObject({ ok: true });
    expect(calls).toBe(2);
    expect(ids).toBe(3);
  });

  test("같은 모양: run·만들기·doctor도 동시 두 번이면 한 번만 띄운다", async () => {
    const spawned: string[][] = [];
    const execs: string[][] = [];
    const r = new JobRunner({
      cli: () => "C:/app/bin/kookabug.exe",
      root: () => ROOT,
      agentIds: async () => ["codex"],
      exec: async (_f, args) => {
        execs.push(args);
        await new Promise((res) => setTimeout(res, 20));
        return { code: 0, stdout: '{"ok":true,"checks":[]}' };
      },
      spawn: (_f, args) => {
        spawned.push(args);
        return { done: new Promise(() => {}), killTree: () => {} };
      },
      emit: () => {},
      override: null,
    });
    const runs = await Promise.all([r.runJob("init", "codex"), r.runJob("init", "codex")]);
    expect(spawned).toHaveLength(1);
    expect(runs).toContainEqual({ started: false, error_code: "job_active" });
    // doctor는 인자가 없어 거부하지 않고 진행 중인 결과를 같이 받는다 (CLI는 한 번)
    const doctors = await Promise.allSettled([r.doctor(), r.doctor()]);
    expect(execs.filter((a) => a[0] === "doctor")).toHaveLength(1);
    expect(doctors.map((d) => d.status)).toEqual(["fulfilled", "fulfilled"]);
    await r.doctor(); // 끝난 뒤에는 다시 돈다
    expect(execs.filter((a) => a[0] === "doctor")).toHaveLength(2);
    const parent = fs.mkdtempSync(path.join(os.tmpdir(), "kb-b7-twice-"));
    try {
      const made = await Promise.allSettled([
        r.createWorkspace({ parent, name: "g", git: false }),
        r.createWorkspace({ parent, name: "g", git: false }),
      ]);
      expect(execs.filter((a) => a[0] === "workspace")).toHaveLength(1);
      expect(made.find((m) => m.status === "rejected")).toMatchObject({ reason: { code: "create_active" } });
    } finally {
      fs.rmSync(parent, { recursive: true, force: true });
    }
  });
});

describe("앱 종료 때 작업 (shutdown)", () => {
  const listed = (tag: string) =>
    JSON.stringify({
      exit_code: 0,
      jobs: [
        { id: "j-20200101-000000-aaaa", state: "running", started_at: "2020-01-01T00:00:00Z" }, // 표지 없음 (남의 작업)
        { id: "j-20261110-000000-bbbb", state: "done", launch_tag: tag }, // 끝난 작업
        { id: "j-20261110-000001-cccc", state: "running", launch_tag: tag },
      ],
    });

  function harness(exitOnCancel: boolean) {
    const execs: string[][] = [];
    let exit: () => void = () => {};
    let killed = 0;
    let tag = "";
    const r = new JobRunner({
      cli: () => "C:/app/bin/kookabug.exe",
      root: () => ROOT,
      agentIds: async () => ["codex"],
      exec: async (_f, args) => {
        execs.push(args);
        if (args[1] === "list") return { code: 0, stdout: listed(tag) };
        if (args[1] === "cancel" && exitOnCancel) setTimeout(() => exit(), 10);
        return { code: 0, stdout: "{}" };
      },
      spawn: (_f, args) => {
        tag = args[args.indexOf("--launch-tag") + 1];
        return {
          done: new Promise<void>((res) => {
            exit = res;
          }),
          killTree: () => killed++,
        };
      },
      emit: () => {},
      override: null,
    });
    return { r, execs, killed: () => killed };
  }

  test("돌던 run에 취소를 요청하고, 상한 안에 끝나면 트리를 끄지 않는다", async () => {
    const idle = harness(true);
    expect(await idle.r.shutdown()).toBe("idle"); // 띄운 작업이 없으면 아무것도 하지 않는다
    expect(idle.execs).toEqual([]);
    const { r, execs, killed } = harness(true);
    await r.runJob("init", "codex");
    expect(r.running).toBe(true);
    expect(await r.shutdown(3_000)).toBe("exited");
    expect(execs).toContainEqual(["agent-job", "list", "--workspace", ROOT, "--json"]);
    expect(execs).toContainEqual(["agent-job", "cancel", "j-20261110-000001-cccc", "--workspace", ROOT, "--json"]);
    expect(execs.some((a) => a.includes("j-20200101-000000-aaaa"))).toBe(false);
    expect(killed()).toBe(0);
  });

  test("상한을 넘기면 자식 프로세스 트리를 끝낸다", async () => {
    const { r, execs, killed } = harness(false);
    await r.runJob("init", "codex");
    const started = Date.now();
    expect(await r.shutdown(100)).toBe("killed");
    expect(Date.now() - started).toBeLessThan(2_000);
    expect(killed()).toBe(1);
    expect(execs.some((a) => a[1] === "cancel")).toBe(true); // 끄기 전에 취소는 요청했다
  });

  test("작업 ID 고르기: 실행 표지가 같은 running·ending만, 형식이 틀린 ID·표지는 버린다", () => {
    const tag = "0123456789abcdef0123456789abcdef";
    const out = (jobs: unknown[]) => `log\n${JSON.stringify({ jobs })}\n`;
    expect(pickRunningJob(out([{ id: "j-20261110-000005-abcd", state: "ending", launch_tag: tag }]), tag)).toBe("j-20261110-000005-abcd");
    expect(pickRunningJob(out([{ id: "--workspace", state: "running", launch_tag: tag }]), tag)).toBeNull();
    expect(pickRunningJob(out([{ id: "j-20261110-000005-abcd", state: "running" }]), tag)).toBeNull(); // 표지 없음
    expect(pickRunningJob(out([{ id: "j-20261110-000005-abcd", state: "running", launch_tag: "f".repeat(32) }]), tag)).toBeNull();
    expect(pickRunningJob(out([{ id: "j-20261110-000005-abcd", state: "done", launch_tag: tag }]), tag)).toBeNull();
    expect(pickRunningJob(out([{ id: "j-20261110-000005-abcd", state: "running", launch_tag: "" }]), "")).toBeNull(); // 빈 표지끼리
    expect(pickRunningJob("not json", tag)).toBeNull();
  });
});

describe("검수 재현 B7-2: 종료는 앱이 띄운 작업만", () => {
  const A = path.resolve("D:/review/A");
  const B = path.resolve("D:/review/B");
  const tagOf = (args: string[]) => {
    const i = args.indexOf("--launch-tag");
    return i < 0 ? undefined : args[i + 1];
  };
  const listOut = (jobs: unknown[]) => ({ code: 0, stdout: `${JSON.stringify({ exit_code: 0, jobs })}\n` });
  const flush = async () => {
    for (let i = 0; i < 20; i++) await Promise.resolve();
  };

  function probeHarness(list: (root: string, tag: string | undefined) => Promise<ExecOutcome> | ExecOutcome) {
    const execs: string[][] = [];
    const spawned: string[][] = [];
    let current = A;
    let exit: () => void = () => {};
    let killed = 0;
    let tag: string | undefined;
    let agentLookup: Promise<string[]> = Promise.resolve(["codex"]);
    const r = new JobRunner({
      cli: () => "C:/app/bin/kookabug.exe",
      root: () => current,
      agentIds: () => agentLookup,
      exec: async (_f, args) => {
        execs.push(args);
        if (args[1] === "list") return list(args[args.indexOf("--workspace") + 1], tag);
        return { code: 0, stdout: "{}" };
      },
      spawn: (_f, args) => {
        spawned.push(args);
        tag = tagOf(args);
        return {
          done: new Promise<void>((res) => {
            exit = res;
          }),
          killTree: () => killed++,
        };
      },
      emit: () => {},
      override: null,
    });
    return {
      r,
      execs,
      spawned,
      killed: () => killed,
      exit: () => exit(),
      setRoot: (p: string) => {
        current = p;
      },
      setAgentLookup: (p: Promise<string[]>) => {
        agentLookup = p;
      },
    };
  }

  test("review_shutdown_keeps_launch_workspace_and_does_not_cancel_other_workspace", async () => {
    const h = probeHarness((root, tag) =>
      root === B
        ? listOut([{ id: "j-20261110-000001-abcd", state: "running", started_at: new Date().toISOString() }])
        : listOut([{ id: "j-20261110-000002-aaaa", state: "running", started_at: new Date().toISOString(), launch_tag: tag }]),
    );
    await h.r.runJob("init", "codex");
    h.setRoot(B); // 앱이 다른 프로젝트를 열었다
    setTimeout(() => h.exit(), 50);
    expect(await h.r.shutdown(3_000)).toBe("exited");
    expect(h.execs.some((a) => a.includes(B))).toBe(false);
    expect(h.execs).toContainEqual(["agent-job", "cancel", "j-20261110-000002-aaaa", "--workspace", A, "--json"]);
    expect(tagOf(h.spawned[0])).toMatch(/^[0-9a-f]{32}$/);
  });

  test("review_shutdown_does_not_cancel_foreign_job_started_one_second_before_launch", async () => {
    const launched = Date.now();
    const h = probeHarness(() =>
      listOut([
        { id: "j-20261110-000001-abcd", state: "running", started_at: new Date(launched - 1_000).toISOString() },
        { id: "j-20261110-000003-bbbb", state: "running", started_at: new Date(launched).toISOString(), launch_tag: "f".repeat(32) },
      ]),
    );
    await h.r.runJob("init", "codex");
    expect(await h.r.shutdown(150)).toBe("killed"); // 표지가 맞는 작업이 없다 → 취소 없음, 상한 뒤 자기 자식만
    await flush();
    expect(h.execs.filter((a) => a[1] === "cancel")).toEqual([]);
    expect(h.killed()).toBe(1);
  });

  test("review_shutdown_stops_delayed_cancellation_after_child_has_exited", async () => {
    let answer: (o: ExecOutcome) => void = () => {};
    let tagSeen: string | undefined;
    const h = probeHarness(
      (_root, tag) =>
        new Promise<ExecOutcome>((res) => {
          tagSeen = tag;
          answer = res;
        }),
    );
    await h.r.runJob("init", "codex");
    const closing = h.r.shutdown(3_000);
    await flush();
    h.exit(); // 목록 응답 전에 자식이 끝났다
    expect(await closing).toBe("exited");
    answer(listOut([{ id: "j-20261110-000004-cccc", state: "running", started_at: new Date().toISOString(), launch_tag: tagSeen }]));
    await flush();
    await new Promise((res) => setTimeout(res, 20));
    expect(h.execs.filter((a) => a[1] === "cancel")).toEqual([]);
    expect(h.killed()).toBe(0);
  });

  test("review_shutdown_during_agent_lookup_does_not_spawn_after_returning", async () => {
    const h = probeHarness(() => listOut([]));
    let release: (ids: string[]) => void = () => {};
    h.setAgentLookup(
      new Promise<string[]>((res) => {
        release = res;
      }),
    );
    const starting = h.r.runJob("init", "codex");
    expect(h.r.running).toBe(true);
    expect(await h.r.shutdown(100)).toBe("idle");
    release(["codex"]);
    await expect(starting).rejects.toMatchObject({ code: "shutting_down" });
    expect(h.spawned).toEqual([]);
    // probe·만들기도 종료 뒤에는 띄우지 않는다
    await expect(h.r.probe("codex")).rejects.toMatchObject({ code: "shutting_down" });
    expect(h.execs).toEqual([]);
  });
});

describe("agent-job", () => {
  test("probe: 루트는 주 프로세스 값, Agent ID → 프로필, 결과는 정해진 필드만 (토큰·메시지 버림)", async () => {
    const { r, calls } = runner();
    const out = await r.probe("claude-code");
    expect(calls[0].args).toEqual(["agent-job", "probe", "--workspace", ROOT, "--agent", "claude", "--json"]);
    expect(out).toEqual({ exit_code: 0, probe_ok: true, ok: true });
    expect(JSON.stringify(out)).not.toContain("SECRET");
  });

  test("사용자 설정에 없는 Agent·감지 표 밖 ID는 띄우지 않는다", async () => {
    const { r, calls } = runner();
    await expect(r.probe("evil")).rejects.toMatchObject({ code: "unknown_agent" });
    await expect(r.probe("custom-x")).rejects.toMatchObject({ code: "agent_job_unsupported" });
    await expect(r.probe("a b")).rejects.toMatchObject({ code: "invalid_agent" });
    expect(calls).toEqual([]);
  });

  test("E2E custom 명령은 주 프로세스가 준 값만 (렌더러 값이 아니다)", async () => {
    const { r, calls } = runner({ override: "python -m fake" });
    await r.probe("custom-x");
    expect(calls[0].args).toEqual(["agent-job", "probe", "--workspace", ROOT, "--agent", "custom", "--agent-command", "python -m fake", "--json"]);
  });

  test("run: 허용 플레이북만, 하나만 동시에, 끝나면 정해진 필드로 알린다", async () => {
    const { r, calls, emitted, finish } = runner();
    await expect(r.runJob("repair", "claude-code")).rejects.toMatchObject({ code: "invalid_playbook" });
    expect(await r.runJob("init", "codex")).toEqual({ started: true });
    expect(calls[0].args).toEqual([
      "agent-job",
      "run",
      "--workspace",
      ROOT,
      "--playbook",
      "init",
      "--agent",
      "codex",
      "--launch-tag",
      expect.stringMatching(/^[0-9a-f]{32}$/),
      "--json",
    ]);
    expect(await r.runJob("init", "codex")).toEqual({ started: false, error_code: "job_active" });
    finish({ code: 3, stdout: 'log line\n{"exit_code":3,"code":"job_active","job":"j-1","agent_log":"raw"}\n' });
    expect(emitted).toEqual([{ action: "run", playbook: "init", exit_code: 3, code: "job_active", job: "j-1" }]);
    expect(await r.runJob("init", "codex")).toEqual({ started: true }); // 끝난 뒤에는 다시
  });

  test("결과 고르기: 마지막 JSON 줄, 객체·배열 값은 버림", () => {
    expect(pickResult('{"job":"j-1"}\n{"state":"done","used":{"runs":1},"exit_code":0}', 0)).toEqual({ state: "done", exit_code: 0 });
    expect(pickResult("not json", 2)).toEqual({ exit_code: 2 });
  });

  test("doctor: 항목 ID·통과만 (detail의 경로는 넘기지 않는다)", () => {
    const out = pickDoctor('{"ok":false,"checks":[{"id":"dpi","ok":true,"detail":"C:/Users/me"},{"id":"ocr.models","ok":false,"detail":"x"}]}', 1);
    expect(out).toEqual({ ok: false, checks: [{ id: "dpi", ok: true }, { id: "ocr.models", ok: false }] });
  });
});
