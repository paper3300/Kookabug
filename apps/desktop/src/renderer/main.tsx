import "./theme/fonts.css";
import "./theme/tokens.css";
import "./theme/base.css";
import { ReactFlowProvider } from "@xyflow/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { useTheme } from "./store/theme";

// 첫 칠하기 전에 테마를 정한다 (토큰이 data-theme에 걸려 있다)
document.documentElement.dataset.theme = useTheme.getState().theme;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ReactFlowProvider>
      <App />
    </ReactFlowProvider>
  </StrictMode>,
);
