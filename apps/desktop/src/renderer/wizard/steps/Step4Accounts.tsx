// 4단계 테스트 계정 (선택, 시안 Setup4Accounts). UX5부터 첫 실행 흐름 밖이다 — 설정 도우미에서 열거나, 접속 경로를 만들다
// 로그인 화면을 만난 Agent가 남긴 보고함 테스트 계정 질문(`kind: credential`)의 "테스트 계정 등록"이 연다.
//
// 값은 두 길로만 들어간다: 녹화 중 비밀번호 칸(`secrets.create`, 녹화 스텝의 메모리 원문 — M4)과, 이 화면의 가린 입력 칸
// (`app.secretSet` → 주 프로세스가 `kookabug secret set`의 표준 입력으로만 넘긴다, UX5). 둘 다 Windows 자격 증명 관리자에만
// 쓰고 daemon RPC·wizard.json·미지수·보고·로그에는 값이 없다. 등록이 끝나면 입력 칸을 비운다.
// 질문에서 열었으면 제안된 키를 모두 등록한 뒤 그 질문을 답함으로 남긴다(`unknowns.answer` — daemon이 키가 등록됐는지 보고
// 키 이름만 담은 고정 글을 남긴다)
import { useEffect, useState } from "react";
import { reloadReports } from "../../reports/reportsStore";
import { client, toRpcError } from "../../rpc/client";
import { askReady, registerAsk, secretInputOk } from "../credential";
import { StepShell } from "../Wizard";
import { setSummary, useWizard } from "../wizardStore";
import { appErrorText } from "./Step1Project";
import css from "../wizard.module.css";

/** 키 하나 등록 (값은 주 프로세스로만) */
async function register(key: string, value: string): Promise<void> {
  await window.kookabug.app.secretSet(key, value);
}

export function Step4Accounts() {
  const credential = useWizard((s) => s.credential);
  const [keys, setKeys] = useState<string[] | null>(null);
  const [envNote, setEnvNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  /** 질문에서 연 화면: 제안된 키마다 값 (등록하면 비운다) */
  const [values, setValues] = useState<Record<string, string>>({});
  /** 직접 등록 칸 */
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [busy, setBusy] = useState(false);

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

  const addOne = async () => {
    if (!secretInputOk(newKey.trim(), newValue) || busy) return;
    setBusy(true);
    setError(null);
    try {
      await register(newKey.trim(), newValue);
      setMessage(`${newKey.trim()} 등록했어요`);
      setNewValue("");
      setNewKey("");
      await load();
    } catch (err) {
      setError(appErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  /** 질문의 키를 모두 등록하고 질문을 답함으로 (끝나면 true — 화면을 닫는다) */
  const registerAsked = async (): Promise<boolean> => {
    if (credential === null) return false;
    setError(null);
    try {
      await registerAsk(credential, values, keys ?? [], {
        register,
        answer: (id, rev, text) => client().call("unknowns.answer", { id, base_rev: rev, text }),
      });
      setValues({});
    } catch (err) {
      setError(appErrorText(err));
      await load();
      return false;
    }
    setSummary(4, `계정 키 ${credential.keys.length}개 등록`);
    void reloadReports();
    return true;
  };

  const count = keys?.length ?? 0;
  const askedReady = credential !== null && askReady(credential, values, keys ?? []);
  return (
    <StepShell
      title="테스트 계정을 등록해요"
      lead="로그인이 필요한 테스트에 쓸 계정이에요. 값은 Windows 자격 증명 관리자에만 저장되고 파일·보고·위키에는 남지 않아요."
      primary={
        credential !== null
          ? { label: "등록", enabled: askedReady && !busy, run: registerAsked, busyLabel: "등록 중…" }
          : {
              label: "다음",
              enabled: count > 0 && !busy,
              run: () => {
                setSummary(4, `계정 키 ${count}개`);
                return true;
              },
            }
      }
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
      {credential !== null && (
        <div className={css.list} data-part="credential-ask" data-unknown={credential.unknown}>
          <div className={css.row}>
            <span className={css.rowText}>
              <span className={css.rowTitle}>Agent가 물었어요</span>
              <span className={css.rowSub}>{credential.question}</span>
            </span>
          </div>
          {credential.keys.map((k) => (
            <label key={k} className={css.row} data-secret-key={k}>
              <span className={`${css.rowText} ${css.mono}`}>
                {k}
                {keys?.includes(k) === true && <span className={css.tag}>저장됨</span>}
              </span>
              <input
                className={css.input}
                type="password"
                autoComplete="off"
                aria-label={`값: ${k}`}
                placeholder={keys?.includes(k) === true ? "비워 두면 그대로" : "값"}
                value={values[k] ?? ""}
                disabled={busy}
                onChange={(e) => setValues((cur) => ({ ...cur, [k]: e.target.value }))}
              />
            </label>
          ))}
        </div>
      )}
      <div className={css.list} data-part="secret-keys">
        <div className={css.row}>
          <span className={css.rowText}>
            <span className={css.rowTitle}>키</span>
          </span>
          <span className={css.rowSub}>값은 이 화면에 다시 오지 않아요</span>
        </div>
        {keys === null && <div className={css.row}>읽는 중…</div>}
        {keys?.map((k) => (
          <div key={k} className={css.row}>
            <span className={`${css.rowText} ${css.mono}`}>{k}</span>
            <span className={css.tag}>저장됨</span>
          </div>
        ))}
      </div>
      {credential === null && (
        <div className={css.inputRow} data-part="secret-add">
          <input
            className={`${css.input} ${css.mono}`}
            aria-label="새 키"
            placeholder="키 (예: login.password)"
            value={newKey}
            disabled={busy}
            onChange={(e) => setNewKey(e.target.value)}
          />
          <input
            className={css.input}
            type="password"
            autoComplete="off"
            aria-label="새 키 값"
            placeholder="값"
            value={newValue}
            disabled={busy}
            onChange={(e) => setNewValue(e.target.value)}
          />
          <button type="button" className={css.small} disabled={busy || !secretInputOk(newKey.trim(), newValue)} onClick={() => void addOne()}>
            등록
          </button>
        </div>
      )}
      <div className={css.info}>
        그래프에는 <span className={css.mono}>{'{ "$secret": "키" }'}</span>만 들어가요. 녹화 중 게임의 아이디·비밀번호 칸에 입력하고 "비밀값으로
        저장"해도 이 목록에 들어와요.
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
      {message !== null && (
        <p role="status" className={css.hint} data-part="secret-message">
          {message}
        </p>
      )}
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
