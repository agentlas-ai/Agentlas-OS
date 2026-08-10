/**
 * Agentlas One memory hook for OpenClaw.
 *
 * OpenClaw has no session-end event, so the checkpoint runs on the commands
 * that end a session (`/new`, `/reset`) and reads the previous session entry.
 * Only assistant `## Memory Events` envelopes are harvested; the runtime never
 * stores raw prompts or transcripts.
 */
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const CHECKPOINT_TIMEOUT_MS = 15_000;
const END_ACTIONS = new Set(["new", "reset"]);

function runnerPath() {
  const home = os.homedir();
  return path.join(home, ".agentlas", "runtime", "current", "bin", "agentlas-one");
}

/**
 * Run the checkpoint without letting it block or outlive the command.
 */
function checkpoint(transcript, workspace) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(runnerPath(), ["stop-hook", "openclaw"], {
        stdio: ["pipe", "ignore", "ignore"],
      });
    } catch {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      try {
        child.kill();
      } catch {
        // The child may have exited between the timeout and the kill.
      }
      resolve();
    }, CHECKPOINT_TIMEOUT_MS);
    const done = () => {
      clearTimeout(timer);
      resolve();
    };
    child.on("error", done);
    child.on("close", done);
    try {
      child.stdin.end(JSON.stringify({ cwd: workspace, transcript_path: transcript }));
    } catch {
      done();
    }
  });
}

const harvestOnSessionEnd = async (event) => {
  if (event?.type !== "command" || !END_ACTIONS.has(event?.action)) return;
  try {
    const context = event.context || {};
    // The session being closed is the previous entry; the new one has no content yet.
    const entry = context.previousSessionEntry || context.sessionEntry || {};
    const transcript = entry.sessionFile;
    if (!transcript) return;
    await checkpoint(transcript, context.workspaceDir || "");
  } catch {
    // A checkpoint failure must never interrupt an OpenClaw session.
  }
};

export default harvestOnSessionEnd;
