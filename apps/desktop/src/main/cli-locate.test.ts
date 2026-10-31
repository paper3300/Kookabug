import path from "node:path";
import { describe, expect, test } from "vitest";
import { CLI_ENV, DEV_CLI, locateCli, PACKAGED_CLI } from "./cli-locate";

const installDir = path.resolve("C:/Program Files/Kookabug");
const repoRoot = path.resolve("D:/repo");
const envCli = path.resolve("E:/tools/kookabug.exe");
const packaged = path.join(installDir, ...PACKAGED_CLI);
const dev = path.join(repoRoot, ...DEV_CLI);

function run(opts: { env?: string; packaged: boolean; existing: string[] }) {
  return locateCli({
    env: opts.env === undefined ? {} : { [CLI_ENV]: opts.env },
    packaged: opts.packaged,
    installDir,
    repoRoot,
    exists: (f) => opts.existing.includes(f),
  });
}

describe("cli-locate", () => {
  test("test_env_then_packaged_then_dev_order", () => {
    // 환경 변수가 있고 파일이 있으면 그것이 먼저다 (패키지·개발 모두)
    expect(run({ env: envCli, packaged: true, existing: [envCli, packaged] })).toEqual({
      path: envCli,
      tried: [envCli],
    });
    expect(run({ env: envCli, packaged: false, existing: [envCli, dev] }).path).toBe(envCli);
    // 환경 변수가 가리키는 파일이 없으면 다음 후보로 간다
    expect(run({ env: envCli, packaged: true, existing: [packaged] })).toEqual({
      path: packaged,
      tried: [envCli, packaged],
    });
    // 패키지 앱은 설치 폴더 bin\kookabug.exe, 레포 .venv는 보지 않는다
    expect(run({ packaged: true, existing: [packaged, dev] })).toEqual({ path: packaged, tried: [packaged] });
    expect(run({ packaged: true, existing: [dev] })).toEqual({ path: null, tried: [packaged] });
    // 개발 모드는 레포 .venv\Scripts\kookabug.exe
    expect(run({ packaged: false, existing: [packaged, dev] })).toEqual({ path: dev, tried: [dev] });
    // 없으면 찾은 경로를 모두 돌려준다 (오류 화면에 보여 줌)
    expect(run({ env: envCli, packaged: false, existing: [] })).toEqual({ path: null, tried: [envCli, dev] });
    // 빈 환경 변수는 없는 것과 같다
    expect(run({ env: "  ", packaged: false, existing: [dev] })).toEqual({ path: dev, tried: [dev] });
  });
});
