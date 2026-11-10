// 프로젝트를 연 뒤 마법사를 띄우는 작은 감시 (M8 계획 3.17 "진입점"). 앱 틀(App·Shell)은 main이 고치는 중이라 상태 바에
// 붙인다. daemon에 붙을 때마다 한 번 본다:
// - 이 PC 진행(wizard.json)이 있고 끝나지 않았으면 이어서 연다
// - 진행이 없고 팀 첫 설정을 마친 프로젝트(wiki/index.md)면 비어 있는 이 PC·사용자 단계(2·3·4·5)만 짧은 마법사 (U8)
// 마법사 겹 화면(WizardHost)도 여기서 그린다 (시작 화면에서는 Welcome이 그린다)
import { useEffect } from "react";
import { client } from "../rpc/client";
import { useWorkspace } from "../store/workspace";
import { WizardHost } from "./Wizard";
import { autoOpenPlan, openWizardWith, only, useWizard, type SetupSnapshot, type StepNo, type WizardFile } from "./wizardStore";

export async function loadSnapshot(): Promise<SetupSnapshot> {
  const [w, secrets, agents] = await Promise.all([
    client().call("wizard.get", {}),
    client()
      .call("secrets.list", {})
      .catch(() => ({ keys: [] as unknown[] })),
    client()
      .call("agents.get", {})
      .catch(() => ({ agents: [] as unknown[] })),
  ]);
  return {
    wizard: w.wizard as WizardFile | null,
    teamSetup: w.team_setup,
    gameExecutable: w.game.executable ?? null,
    gameTitle: w.game.title ?? null,
    secretKeys: secrets.keys.length,
    agents: agents.agents.length,
  };
}

/** 설정 도우미: 그 단계 하나만 다시 연다 (진행 기록은 이어 쓴다) */
export async function openSetupStep(n: StepNo): Promise<void> {
  let base: WizardFile | null = null;
  try {
    base = (await client().call("wizard.get", {})).wizard as WizardFile | null;
  } catch {
    // 못 읽으면 빈 기록에서
  }
  openWizardWith(only(n, base));
}

/** 이 연결(루트·daemon 시작)에서 이미 봤는가 — 다시 붙을 때마다 묻지 않게 */
let seen: string | null = null;

export function ShortWizardWatch() {
  const root = useWorkspace((s) => s.root);
  const status = useWorkspace((s) => s.daemon.status);
  const startId = useWorkspace((s) => s.daemon.startId);

  useEffect(() => {
    if (status !== "connected" || root === null) return;
    const key = `${root}:${startId ?? ""}`;
    if (seen === key) return;
    seen = key;
    // 새 프로젝트 마법사가 이미 떠 있으면(1단계에서 만든 직후) 건드리지 않는다
    if (useWizard.getState().open) return;
    void loadSnapshot()
      .then((snap) => {
        if (useWizard.getState().open || useWorkspace.getState().root !== root) return;
        const plan = autoOpenPlan(snap);
        if (plan !== null) openWizardWith(plan);
      })
      .catch(() => {
        // daemon이 마법사 메서드를 모르면(옛 daemon) 띄우지 않는다
      });
  }, [root, status, startId]);

  return <WizardHost />;
}
