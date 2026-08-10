// Local OpenCode plugin: capture the current user prompt, then inject the
// bounded Agentlas ontology capsule into the next system prompt. It uses only
// Bun/Node built-ins and the installed local runtime; there are no npm or
// network dependencies.

const latestBySession = new Map()
const assistantBySession = new Map()
const assistantMessageIDs = new Set()
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
    const child = Bun.spawn([executable, "stop-hook", "opencode"], {
      stdin: new Blob([JSON.stringify({ cwd: directory, sessionID, assistant_texts: texts })]),
      stdout: "ignore",
      stderr: "ignore",
      env: process.env,
    })
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
  } catch {
    // A missing runtime must not surface as a session error.
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
    const child = Bun.spawn(
      [executable, "--host", "opencode", "--event", "UserPromptSubmit"],
      {
        stdin: new Blob([JSON.stringify({ cwd: directory, sessionID, user_prompt: prompt })]),
        stdout: "pipe",
        stderr: "ignore",
        env: process.env,
      },
    )
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
  } catch {
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
      return
    }

    // Session end is the checkpoint; every other event only accumulates.
    if (event.type === "session.idle") {
      await harvest(directory, sessionID)
      return
    }

    const found = []
    collectAssistantText(properties, found, false, 0, assistantMessageIDs)
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
  },
})
