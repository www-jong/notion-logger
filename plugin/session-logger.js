// NOTION_AUTO_LOGGER_PLUGIN
// opencode 세션이 유휴(idle) 상태가 되면(= 어시스턴트 턴 종료)
// notion-logger run.py를 호출해 그동안의 새 턴을 노션에 기록한다.
//
// 데스크톱 앱(Embedded Node 런타임)과 TUI(Bun) 양쪽에서 동작하도록
// 런타임 전용 API 대신 Node 표준 API만 사용한다.
//
// 등록 방법은 README "opencode" 섹션 참고.
// ★ 사용 전 아래 RUN_PATH를 본인 환경에 맞게 수정할 것 ★

import { appendFileSync, mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";

// ===== 사용자 설정 (반드시 수정) =====
// notion-logger 저장소의 run.py 절대 경로.
// 예: "/Users/me/dev/notion-logger/run.py" 또는 "C:/dev/notion-logger/run.py"
const RUN_PATH = "";
// ====================================

const AGENT_NAME = "opencode";
const PYTHON = process.platform === "win32" ? "python" : "python3";
// 로그는 run.py 옆 tmp/ 에 기록된다 (RUN_PATH 설정 시 자동 결정)
const DEBUG_LOG = RUN_PATH
  ? join(dirname(RUN_PATH), "tmp", "opencode_plugin.log")
  : "";

function trace(msg) {
  if (!DEBUG_LOG) return;
  try {
    mkdirSync(dirname(DEBUG_LOG), { recursive: true });
    appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${msg}\n`);
  } catch (_) {}
}

export const NotionAutoLoggerPlugin = async ({ directory }) => {
  if (!RUN_PATH) {
    // 설정 안 됐으면 조용히 무기능 (에이전트 방해 금지)
    console.warn("[notion-auto-logger] plugin/session-logger.js 의 RUN_PATH 를 설정하세요");
    return {};
  }
  trace(`plugin loaded (directory=${directory})`);

  return {
    event: async ({ event }) => {
      try {
        if (!event || event.type !== "session.idle") return;

        const props = event.properties || {};
        const sessionID =
          props.info?.id || props.sessionID || props.info?.sessionID;
        if (!sessionID) return;

        const payload = JSON.stringify({
          source: AGENT_NAME,
          sessionID,
          directory: directory || "",
        });

        const proc = spawn(PYTHON, [RUN_PATH, AGENT_NAME], {
          stdio: ["pipe", "ignore", "ignore"],
          detached: false,
        });
        proc.stdin.write(payload);
        proc.stdin.end();
        proc.on("error", () => {});
        // 좀비 방지. run.py는 최대 몇십 초 안에 끝난다.
        setTimeout(() => {
          try {
            proc.kill();
          } catch (_) {}
        }, 60000).unref?.();
      } catch (e) {
        trace(`error: ${e && e.message}`);
      }
    },
  };
};
