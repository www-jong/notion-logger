// NOTION_AUTO_LOGGER_PLUGIN
// opencode 세션이 유휴(idle) 상태가 되면(= 어시스턴트 턴 종료)
// notion-logger run.py를 호출해 그동안의 새 턴을 노션에 기록한다.
//
// 데스크톱 앱(Embedded Node 런타임)과 TUI(Bun) 양쪽에서 동작하도록
// 런타임 전용 API 대신 Node 표준 API만 사용한다.
//
// 등록: ~/.config/opencode/opencode.jsonc 의 plugin 배열에 file:// 경로 추가
//   또는 ~/.config/opencode/plugins/ 아래에 복사
// (수정은 항상 notion-logger 저장소에서 하고 배포는 복사)

import { appendFileSync } from "node:fs";
import { spawn } from "node:child_process";

const RUN_PATH = "/Users/wonjong/.gemini/hooks/notion-logger/run.py";
const AGENT_NAME = "opencode";
const DEBUG_LOG =
  "/Users/wonjong/.gemini/hooks/notion-logger/tmp/opencode_plugin.log";

function trace(msg) {
  try {
    appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${msg}\n`);
  } catch (_) {}
}

export const NotionAutoLoggerPlugin = async ({ directory }) => {
  trace(`plugin loaded (directory=${directory})`);

  return {
    event: async ({ event }) => {
      try {
        if (!event || event.type !== "session.idle") return;
        trace(`event: session.idle`);

        const props = event.properties || {};
        const sessionID =
          props.info?.id || props.sessionID || props.info?.sessionID;
        if (!sessionID) {
          trace(`no sessionID. props keys=${Object.keys(props).join(",")}`);
          return;
        }
        trace(`trigger: ${sessionID}`);

        const payload = JSON.stringify({
          source: AGENT_NAME,
          sessionID,
          directory: directory || "",
        });

        const proc = spawn("python3", [RUN_PATH, AGENT_NAME], {
          stdio: ["pipe", "ignore", "ignore"],
          detached: false,
        });
        proc.stdin.write(payload);
        proc.stdin.end();
        proc.on("error", () => {});
        // 좀비 방지. run.py는 최대 몇 초 안에 끝난다.
        setTimeout(() => {
          try {
            proc.kill();
          } catch (_) {}
        }, 30000).unref?.();
      } catch (e) {
        trace(`error: ${e && e.message}`);
      }
    },
  };
};
