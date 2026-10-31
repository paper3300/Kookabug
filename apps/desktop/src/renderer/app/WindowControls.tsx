// 프레임 없는 창의 최소화·최대화·닫기 (시안 Main 타이틀 바 오른쪽)
import { useEffect } from "react";
import type { WindowState } from "../../preload/bridge";
import { useUi } from "../store/ui";
import { CloseIcon, MaximizeIcon, MinimizeIcon, RestoreIcon } from "../theme/icons";
import css from "./shell.module.css";

export function WindowControls({ height }: { height?: number }) {
  const maximized = useUi((s) => s.maximized);
  useEffect(() => {
    void window.kookabug.app.windowState().then((s) => useUi.setState({ maximized: s.maximized }));
    const off = window.kookabug.on("window.state", (data) =>
      useUi.setState({ maximized: (data as WindowState).maximized }),
    );
    return () => off();
  }, []);
  const control = (action: "minimize" | "maximize" | "close") => () => void window.kookabug.app.windowControl(action);
  const style = height === undefined ? undefined : { height };
  return (
    <div className={css.windowControls}>
      <button type="button" aria-label="최소화" style={style} onClick={control("minimize")}>
        <MinimizeIcon />
      </button>
      <button type="button" aria-label={maximized ? "이전 크기로" : "최대화"} style={style} onClick={control("maximize")}>
        {maximized ? <RestoreIcon /> : <MaximizeIcon />}
      </button>
      <button type="button" aria-label="닫기" className={css.closeButton} style={style} onClick={control("close")}>
        <CloseIcon />
      </button>
    </div>
  );
}
