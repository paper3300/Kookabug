// 4단계 테스트 계정 (선택, 시안 Setup4Accounts). 비밀값은 기존 `secrets.create`로만 만든다 — 그 메서드는 값을 RPC로
// 받지 않고 녹화 스텝의 메모리 원문을 자격 증명 관리자에 쓴다(M4). 그래서 이 화면은 값을 입력받지 않는다:
// 이미 있는 키(값 없음)를 보여 주고, 만드는 법(녹화 중 비밀번호 칸)을 안내한다. 값은 렌더러·wizard.json·로그에 없다
import { useEffect, useState } from "react";
import { client, toRpcError } from "../../rpc/client";
import { StepShell } from "../Wizard";
import { setSummary } from "../wizardStore";
import css from "../wizard.module.css";

export function Step4Accounts() {
  const [keys, setKeys] = useState<string[] | null>(null);
  const [envNote, setEnvNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await client().call("secrets.list", {});
      setKeys(r.keys.map((k) => k.key));
      setEnvNote(r.env_note);
    } catch (err) {
      setError(toRpcError(err).message);
      setKeys([]);
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const count = keys?.length ?? 0;
  return (
    <StepShell
      title="테스트 계정을 등록해요"
      lead="로그인이 필요한 테스트에 쓸 계정이에요. 비밀번호는 Windows 자격 증명 관리자에 저장되고 파일에는 남지 않아요."
      primary={{
        label: "다음",
        enabled: count > 0,
        run: () => {
          setSummary(4, `계정 키 ${count}개`);
          return true;
        },
      }}
      right={
        <>
          <div className={css.card}>
            <div className={css.cardHead}>Windows 자격 증명 관리자</div>
            {count === 0 && <div className={css.cardRow}>아직 이 프로젝트 키가 없어요</div>}
            {keys?.map((k) => (
              <div key={k} className={`${css.cardRow} ${css.mono}`}>
                <span style={{ flex: "1 1 auto" }}>kookabug:…:{k}</span>
                <span aria-hidden="true">●●●●</span>
              </div>
            ))}
          </div>
          <div className={css.caption}>그래프에는 키 이름만 들어가요. 값은 실행할 때 찾아 넣어요.</div>
        </>
      }
    >
      <div className={css.list} data-part="secret-keys">
        <div className={css.row}>
          <span className={css.rowText}>
            <span className={css.rowTitle}>키</span>
          </span>
          <span className={css.rowSub}>값은 이 화면에 오지 않아요</span>
        </div>
        {keys === null && <div className={css.row}>읽는 중…</div>}
        {keys?.map((k) => (
          <div key={k} className={css.row}>
            <span className={`${css.rowText} ${css.mono}`}>{k}</span>
            <span className={css.tag}>저장됨</span>
          </div>
        ))}
      </div>
      <div className={css.info}>
        계정 추가: 녹화 중 게임의 아이디·비밀번호 칸에 입력하면 "비밀값으로 저장"으로 이 키 목록에 들어와요. 그래프에는{" "}
        <span className={css.mono}>{'{ "$secret": "키" }'}</span>만 들어가요.
        {envNote !== "" && (
          <>
            <br />
            {envNote}
          </>
        )}
      </div>
      <button type="button" className={css.small} style={{ alignSelf: "flex-start" }} onClick={() => void load()}>
        목록 다시 읽기
      </button>
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
