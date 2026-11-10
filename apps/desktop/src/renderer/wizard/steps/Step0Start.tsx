// 0단계 시작: 새 프로젝트 / 기존 프로젝트 열기 (시안 Setup0Welcome의 두 갈래). 시작 화면에서 "새 프로젝트 만들기"를
// 누르면 1단계부터 열리고, 1단계의 "이전"으로 여기에 온다
import { openFolder } from "../../store/workspace";
import { StepShell } from "../Wizard";
import { chooseNew, closeWizard } from "../wizardStore";
import css from "../wizard.module.css";

export function Step0Start() {
  return (
    <StepShell
      title="무엇부터 할까요?"
      lead="새 프로젝트를 만들거나, 팀이 만든 프로젝트를 열어요. 이미 있는 프로젝트는 이 PC에 필요한 것만 짧게 물어봐요."
      primary={{ label: "다음", enabled: false }}
      right={
        <div className={css.card}>
          <div className={css.cardHead}>설정 순서</div>
          {["프로젝트", "게임 연결", "환경 점검", "테스트 계정", "Agent", "프로젝트 정보", "자동화 정책", "기록", "완료"].map(
            (t, i) => (
              <div key={t} className={css.cardRow}>
                <span className={css.mark} data-state="wait">
                  {i + 1}
                </span>
                <span>{t}</span>
              </div>
            ),
          )}
        </div>
      }
    >
      <div className={css.list} role="group" aria-label="시작">
        <button type="button" className={css.row} style={{ width: "100%", border: 0 }} onClick={chooseNew}>
          <span className={css.avatar}>+</span>
          <span className={css.rowText} style={{ textAlign: "left" }}>
            <span className={css.rowTitle}>새 프로젝트 만들기</span>
            <span className={css.rowSub}>폴더·Git·지식 저장소를 만들어요</span>
          </span>
        </button>
        <button
          type="button"
          className={css.row}
          style={{ width: "100%", border: 0 }}
          onClick={() => {
            void closeWizard().then(() => openFolder());
          }}
        >
          <span className={css.avatar}>↗</span>
          <span className={css.rowText} style={{ textAlign: "left" }}>
            <span className={css.rowTitle}>이미 있는 프로젝트 열기</span>
            <span className={css.rowSub}>비어 있는 이 PC 설정만 짧은 마법사로 물어봐요</span>
          </span>
        </button>
      </div>
    </StepShell>
  );
}
