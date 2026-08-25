// NOTION_AUTO_LOGGER_PLUGIN
// opencode 세션이 유휴(idle) 상태가 되면(= 어시스턴트 턴 종료)
// notion-logger run.py를 호출해 그동안의 새 턴을 노션에 기록한다.
//
// 배포 위치: ~/.config/opencode/plugins/session-logger.js
// (공식 문서 기준 복수형 plugins/ 디렉토리. 자동 로드됨 — 별도 설정 JSON 불필요)
// (수정은 항상 notion-logger 저장소에서 하고 복사한다)

const RUN_PATH = "/Users/wonjong/.gemini/hooks/notion-logger/run.py";
const AGENT_NAME = "opencode";

const DEBUG_LOG = "/Users/wonjong/.gemini/hooks/notion-logger/tmp/opencode_plugin.log";

function trace(msg) {
  try {
    Bun.write(Bun.file(DEBUG_LOG, { append: true }),
      `[${new Date().toISOString()}] ${msg}\n`);
  } catch (_) {}
}

export const NotionAutoLoggerPlugin = async ({ directory }) => {
  trace(`plugin loaded (directory=${directory})`);
  return {
    event: async ({ event }) => {
      try {
        trace(`event: ${event?.type}`);
        if (!event || event.type !== "session.idle") return;
        const props = event.properties || {};
        const sessionID =
          props.info?.id || props.sessionID || props.info?.sessionID;
        if (!sessionID) {
          trace(`no sessionID. props keys=${Object.keys(props).join(",")}`);
          return;
        }

        const payload = JSON.stringify({
          source: AGENT_NAME,
          sessionID,
          directory: directory || "",
        });

        const proc = Bun.spawn(["python3", RUN_PATH, AGENT_NAME], {
          stdin: "pipe",
          stdout: "ignore",
          stderr: "ignore",
        });
        proc.stdin.write(payload);
        proc.stdin.end();
        if (proc.exited && typeof proc.exited.catch === "function") {
          proc.exited.catch(() => {});
        }
      } catch (_) {}
    },
  };
};
