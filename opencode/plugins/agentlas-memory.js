// Local OpenCode plugin: capture the current user prompt, then inject the
// bounded Agentlas ontology capsule into the next system prompt. It uses only
// Bun/Node built-ins and the installed local runtime; there are no npm or
// network dependencies.

/**
 * PRD §5.21 — 이 플러그인은 `Bun.spawn` 만 썼다. OpenCode 가 Node 로 도는 설치본에서는
 * 그 호출이 던지고, 아래 try/catch 가 조용히 삼켜서 **기억이 한 번도 저장되지 않았는데도**
 * 아무 표시가 없었다. 런타임을 확인하고, 없으면 Node 로 돌리며, 그래도 안 되면 말한다.
 */
function spawnLocal(command, args, options) {
  if (typeof Bun !== "undefined" && typeof Bun.spawn === "function") {
    return { kind: "bun", child: Bun.spawn([command, ...args], options) }
  }
  // Node 폴백. 같은 계약(stdin 으로 JSON 한 덩이, stdout 수집)을 지킨다.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { spawn } = require("node:child_process")
  const child = spawn(command, args, { env: options.env, stdio: ["pipe", options.stdout === "pipe" ? "pipe" : "ignore", "ignore"] })
  return { kind: "node", child }
}

async function writeStdin(handle, payload) {
  if (handle.kind === "bun") return
  await new Promise((resolve) => {
    handle.child.stdin.end(payload, resolve)
  })
}

function reportPluginFailure(where, error) {
  // 삼키지 않는다. 이 플러그인의 유일한 사용자 표면은 로그다.
  // eslint-disable-next-line no-console
  console.error(`agentlas-one opencode plugin: ${where} failed — ${error && error.message ? error.message : String(error)}`)
}

const latestBySession = new Map()
const assistantBySession = new Map()
const assistantMessageIDs = new Set()
// PRD §5.22 — 본 메시지 id 를 세션별로도 기억해, 세션이 끝나면 그 몫만 정확히 거둔다.
// (전역 집합만 있으면 프로세스가 사는 동안 무한히 커진다.)
const messageIdsBySession = new Map()

function rememberSessionMessageIds(sessionID, ids) {
  if (!sessionID || ids.length === 0) return
  const bucket = messageIdsBySession.get(sessionID) || new Set()
  for (const id of ids) bucket.add(id)
  messageIdsBySession.set(sessionID, bucket)
}

function forgetSessionMessageIds(sessionID) {
  const bucket = messageIdsBySession.get(sessionID)
  if (!bucket) return
  for (const id of bucket) assistantMessageIDs.delete(id)
  messageIdsBySession.delete(sessionID)
}
const RECALL_TIMEOUT_MS = 12_000
const HARVEST_TIMEOUT_MS = 15_000
const MEMORY_EVENTS_HEADING = "## Memory Events"
const MAX_TEXTS_PER_SESSION = 40

// Collect assistant text without assuming one event shape. OpenCode carries the
// role on the message and the text on its parts, so walk the node and take text
// only from assistant-owned subtrees. Never collect user prompts.
function collectAssistantText(node, out, assistant = false, depth = 0, assistantMessages = null) {
  if (!node || depth > 8 || out.length >= MAX_TEXTS_PER_SESSION) return
  if (Array.isArray(node)) {
    for (const item of node) collectAssistantText(item, out, assistant, depth + 1, assistantMessages)
    return
  }
  if (typeof node !== "object") return
  const role = node.role || node.info?.role
  const messageID = node.messageID || node.id || node.info?.id
  // A part event can arrive without its message, so remember which message ids
  // are assistant-owned and let later parts inherit that ownership.
  if (role === "assistant" && messageID) assistantMessages?.add(messageID)
  const inherited = Boolean(messageID && assistantMessages?.has(messageID))
  const owned = assistant || role === "assistant" || inherited
  if (role && role !== "assistant") return
  if (owned && typeof node.text === "string" && node.text.includes(MEMORY_EVENTS_HEADING)) {
    out.push(node.text.slice(0, 20000))
  }
  for (const value of Object.values(node)) {
    collectAssistantText(value, out, owned, depth + 1, assistantMessages)
  }
}

async function harvest(directory, sessionID) {
  const texts = assistantBySession.get(sessionID)
  assistantBySession.delete(sessionID)
  if (!texts || texts.length === 0) return
  const home = process.env.HOME || ""
  const executable = `${home}/.agentlas/runtime/current/bin/agentlas-one`
  try {
    const payload = JSON.stringify({ cwd: directory, sessionID, assistant_texts: texts })
    const handle = spawnLocal(executable, ["stop-hook", "opencode"], {
      stdin: new Blob([payload]),
      stdout: "ignore",
      stderr: "ignore",
      env: process.env,
    })
    await writeStdin(handle, payload)
    const child = handle.child
    // The checkpoint must never block or outlive the turn that triggered it.
    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {
        // The child may have exited between the timeout and the kill.
      }
    }, HARVEST_TIMEOUT_MS)
    await child.exited
    clearTimeout(timer)
  } catch (error) {
    // 세션을 막지는 않는다. 그러나 조용히 삼키지도 않는다 — 예전에는 이 catch 때문에
    // 기억이 한 번도 저장되지 않는 설치본에서도 아무 표시가 없었다(PRD §5.21).
    reportPluginFailure("memory checkpoint", error)
  }
}

function promptText(parts) {
  return (parts || [])
    .filter((part) => part && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n")
    .slice(0, 12000)
}

async function recall(directory, sessionID, prompt) {
  const home = process.env.HOME || ""
  const executable = `${home}/.agentlas/runtime/current/bin/agentlas-memory-hook`
  try {
    const payload = JSON.stringify({ cwd: directory, sessionID, user_prompt: prompt })
    const handle = spawnLocal(
      executable,
      ["--host", "opencode", "--event", "UserPromptSubmit"],
      {
        stdin: new Blob([payload]),
        stdout: "pipe",
        stderr: "ignore",
        env: process.env,
      },
    )
    await writeStdin(handle, payload)
    const child = handle.child
    let timer
    const completed = (async () => {
      try {
        const [output, status] = await Promise.all([
          new Response(child.stdout).text(),
          child.exited,
        ])
        const trimmed = output.trim()
        return status === 0 && trimmed.startsWith("<agentlas-memory-context") ? trimmed : ""
      } catch {
        return ""
      }
    })()
    const timedOut = new Promise((resolve) => {
      timer = setTimeout(() => {
        try {
          child.kill()
        } catch {
          // The child may have exited between the race and the kill.
        }
        resolve("")
      }, RECALL_TIMEOUT_MS)
    })
    const result = await Promise.race([completed, timedOut])
    clearTimeout(timer)
    return result
  } catch (error) {
    reportPluginFailure("memory recall", error)
    return ""
  }
}

export const AgentlasMemoryPlugin = async ({ directory }) => ({
  event: async ({ event }) => {
    const properties = event?.properties || {}
    const sessionID =
      properties.sessionID ||
      properties.info?.sessionID ||
      properties.info?.id ||
      properties.part?.sessionID ||
      properties.id
    if (!sessionID) return

    if (event.type === "session.deleted") {
      latestBySession.delete(sessionID)
      assistantBySession.delete(sessionID)
      forgetSessionMessageIds(sessionID)
      return
    }

    // Session end is the checkpoint; every other event only accumulates.
    if (event.type === "session.idle") {
      await harvest(directory, sessionID)
      // PRD §5.22 — 본 메시지 id 집합이 정리되지 않아 프로세스가 사는 동안 계속 커졌다.
      // 세션이 끝나면 그 세션의 id 는 다시 볼 일이 없다.
      forgetSessionMessageIds(sessionID)
      return
    }

    const found = []
    const seenBefore = new Set(assistantMessageIDs)
    collectAssistantText(properties, found, false, 0, assistantMessageIDs)
    rememberSessionMessageIds(sessionID, [...assistantMessageIDs].filter((id) => !seenBefore.has(id)))
    if (found.length === 0) return
    const bucket = assistantBySession.get(sessionID) || []
    for (const text of found) {
      if (!bucket.includes(text)) bucket.push(text)
    }
    assistantBySession.set(sessionID, bucket.slice(-MAX_TEXTS_PER_SESSION))
  },

  "chat.message": async (input, output) => {
    const prompt = promptText(output.parts)
    if (!prompt) return
    const capsule = await recall(directory, input.sessionID, prompt)
    if (capsule) latestBySession.set(input.sessionID, capsule)
    else latestBySession.delete(input.sessionID)
  },

  "experimental.chat.system.transform": async (input, output) => {
    const capsule = input.sessionID ? latestBySession.get(input.sessionID) : ""
    if (capsule && !output.system.includes(capsule)) output.system.push(capsule)
  },

  "experimental.session.compacting": async (input, output) => {
    const capsule = latestBySession.get(input.sessionID)
    if (capsule && !output.context.includes(capsule)) output.context.push(capsule)
  },

  dispose: async () => {
    latestBySession.clear()
    assistantBySession.clear()
    assistantMessageIDs.clear()
    messageIdsBySession.clear()
  },
})
