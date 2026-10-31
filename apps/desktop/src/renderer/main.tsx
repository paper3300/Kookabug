import "./theme/fonts.css";
import "./theme/base.css";
import { ReactFlowProvider } from "@xyflow/react";
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { useTheme } from "./store/theme";

// 앱 틀(타이틀 바·사이드바·탭·패널)은 T7, 캔버스는 T8. 지금은 시안 배경색의 빈 화면이다
function Root() {
  const theme = useTheme((s) => s.theme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  return <ReactFlowProvider>{null}</ReactFlowProvider>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
