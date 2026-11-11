// 상태 바 "보고함 N" (M8 계획 3.17, U7): N = 결정할 묶음이 있는 보고 + 도는 작업. 누르면 보고함 탭
import { useEffect } from "react";
import { Spinner } from "../app/Spinner";
import { useWorkspace } from "../store/workspace";
import { inboxCount, initReports, openReportsTab, reloadReports, useReports } from "./reportsStore";

export function ReportsButton({ className }: { className: string }) {
  const count = useReports((s) => inboxCount(s.rows));
  const running = useReports((s) => s.rows.some((r) => r.state === "running" || r.state === "ending"));
  const root = useWorkspace((s) => s.root);
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  useEffect(() => {
    initReports();
    if (connected && root !== null) void reloadReports();
  }, [connected, root]);
  return (
    <button
      type="button"
      className={className}
      data-part="status-reports"
      data-count={count}
      style={{ marginLeft: 8 }}
      title={running ? "작업이 도는 중이에요" : "작업마다 쌓이는 보고"}
      onClick={openReportsTab}
    >
      보고함 {count}
      {running && (
        <>
          {" · "}
          <Spinner size="sm" label="작업 중" delay={0} />
        </>
      )}
    </button>
  );
}
