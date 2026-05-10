"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { startPipeline, getStatus, sendApproval, type PipelineStatus, type LogEntry } from "@/lib/api"

const EXAMPLE_PROMPTS = [
  "build a REST API with auth",
  "create a data processing pipeline",
  "design a task management system",
]

// ─── Pipeline data ────────────────────────────────────────────────────────────

const STAGES = [
  { num: "01", name: "Intake" },
  { num: "02", name: "Clarify" },
  { num: "03", name: "Architect" },
  { num: "04", name: "Plan" },
  { num: "05", name: "TDD" },
  { num: "06", name: "Code" },
  { num: "07", name: "Review" },
  { num: "08", name: "Summary" },
]

// Map backend stage names to STAGES index
const STAGE_MAP: Record<string, number> = {
  intake: 0,
  clarification: 1,
  architecture: 2,
  planning: 3,
  human_plan_approval: 3,
  tdd: 4,
  code_gen: 5,
  diff_review: 6,
  validation: 6,
  security: 6,
  recovery: 6,
  complete: 7,
  aborted: 7,
}


// ─── Code texture background ─────────────────────────────────────────────────

const CODE_CHARS = [
  "const", "=>", "{}", "[];", "//", "import", "async", "await",
  "return", "function", "class", "def", "/*", "*/", "()", "::",
  "[]", "<>", ";", "=>", "/**/", "export", "if", "else",
]

type CodeParticle = { x: number; y: number; text: string; size: number; opacity: number }

function CodeBackground() {
  const particles: CodeParticle[] = []
  const cols = 14
  const rows = 10
  const seeds = [0.13, 0.72, 0.31, 0.87, 0.55, 0.19, 0.63, 0.44, 0.91, 0.07,
                 0.38, 0.76, 0.22, 0.59, 0.84, 0.03, 0.47, 0.68, 0.15, 0.93,
                 0.27, 0.51, 0.79, 0.34, 0.62, 0.08, 0.96, 0.41, 0.74, 0.17,
                 0.88, 0.53, 0.26, 0.69, 0.12, 0.45, 0.83, 0.36, 0.61, 0.99,
                 0.24, 0.57, 0.80, 0.04, 0.39, 0.72, 0.16, 0.49, 0.93, 0.28,
                 0.65, 0.11, 0.44, 0.77, 0.33, 0.66, 0.22, 0.55, 0.88, 0.10,
                 0.43, 0.76, 0.09, 0.52, 0.85, 0.18, 0.41, 0.74, 0.07, 0.60,
                 0.23, 0.56, 0.89, 0.02, 0.35, 0.68, 0.01, 0.34, 0.97, 0.30,
                 0.63, 0.96, 0.29, 0.62, 0.05, 0.38, 0.71, 0.14, 0.47, 0.80,
                 0.13, 0.46, 0.79, 0.12, 0.45, 0.78, 0.21, 0.54, 0.87, 0.20,
                 0.53, 0.86, 0.19, 0.52, 0.85, 0.18, 0.51, 0.84, 0.17, 0.50,
                 0.83, 0.16, 0.49, 0.82, 0.15, 0.48, 0.81, 0.14, 0.47, 0.80,
                 0.13, 0.46, 0.79, 0.12, 0.45, 0.78, 0.11, 0.44, 0.77, 0.10,
                 0.43, 0.76, 0.09, 0.42, 0.75, 0.08, 0.41, 0.74, 0.07, 0.40]

  let si = 0
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const jx = (seeds[si % seeds.length] - 0.5) * (100 / cols) * 0.7; si++
      const jy = (seeds[si % seeds.length] - 0.5) * (100 / rows) * 0.7; si++
      const charIdx = Math.floor(seeds[si % seeds.length] * CODE_CHARS.length); si++
      const sizeIdx = seeds[si % seeds.length]; si++
      const opIdx = seeds[si % seeds.length]; si++
      particles.push({
        x: (c / cols) * 100 + (100 / cols / 2) + jx,
        y: (r / rows) * 100 + (100 / rows / 2) + jy,
        text: CODE_CHARS[charIdx],
        size: 10 + Math.floor(sizeIdx * 4),
        opacity: 0.025 + opIdx * 0.015,
      })
    }
  }

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none select-none" aria-hidden>
      {particles.map((p, i) => (
        <span
          key={i}
          className="absolute font-mono text-white"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            fontSize: `${p.size}px`,
            opacity: p.opacity,
            transform: "translate(-50%, -50%)",
            whiteSpace: "nowrap",
          }}
        >
          {p.text}
        </span>
      ))}
    </div>
  )
}

// ─── Launch Screen ────────────────────────────────────────────────────────────

function LaunchScreen({ onSubmit }: { onSubmit: (prompt: string) => void }) {
  const [prompt, setPrompt] = useState("")
  const [focused, setFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleRun = () => {
    if (prompt.trim()) onSubmit(prompt.trim())
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleRun()
    }
  }

  return (
    <div className="relative h-screen w-screen flex flex-col items-center justify-center bg-[#0d0d0d] overflow-hidden">
      <CodeBackground />
      <div className="relative z-10 flex flex-col items-center">
        <div className="flex flex-col items-center mb-10">
          <span
            className="text-white font-mono font-medium select-none mb-1"
            style={{ fontSize: "18px", letterSpacing: "0.15em" }}
          >
            Omnix
          </span>
          <span className="font-mono text-[#555]" style={{ fontSize: "12px", letterSpacing: "0.08em" }}>
            multi-agent pipeline
          </span>
        </div>

        <div className="flex flex-col" style={{ width: "560px" }}>
          <div
            className="flex items-center bg-[#111] transition-shadow duration-200"
            style={{
              borderRadius: "6px",
              boxShadow: focused
                ? "inset 0 0 0 1px #4f8ef7, 0 0 12px rgba(79, 142, 247, 0.15)"
                : "inset 0 0 0 1px #2a2a2a",
            }}
          >
            <input
              ref={inputRef}
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              placeholder="Describe your project..."
              className="flex-1 bg-transparent font-mono text-[#aaa] outline-none placeholder:text-[#444] px-4 py-3"
              style={{ fontSize: "13px" }}
            />
            <button
              onClick={handleRun}
              disabled={!prompt.trim()}
              className="font-mono text-[#aaa] bg-[#1e1e1e] hover:bg-[#2a2a2a] hover:text-[#e0e0e0] transition-colors disabled:opacity-40 disabled:cursor-not-allowed mr-2 px-3 py-1"
              style={{ fontSize: "11px", borderRadius: "4px", border: "1px solid #2a2a2a" }}
            >
              Run
            </button>
          </div>

          <div className="flex items-center justify-center gap-3 mt-5 flex-wrap">
            {EXAMPLE_PROMPTS.map((p) => (
              <button
                key={p}
                onClick={() => setPrompt(p)}
                className="chip font-mono transition-colors"
                style={{ fontSize: "11px" }}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Blinking cursor ──────────────────────────────────────────────────────────

function BlinkCursor() {
  const [visible, setVisible] = useState(true)
  useEffect(() => {
    const id = setInterval(() => setVisible((v) => !v), 530)
    return () => clearInterval(id)
  }, [])
  return (
    <span style={{ color: "#6c4ef2", opacity: visible ? 1 : 0 }}>_</span>
  )
}

// ─── Left Column ──────────────────────────────────────────────────────────────

function LeftColumn({
  projectBrief,
  view,
  activeStageIndex,
  logs,
  checkpointLabel,
}: {
  projectBrief: string
  view: "running" | "checkpoint"
  activeStageIndex: number
  logs: LogEntry[]
  checkpointLabel: string
}) {
  return (
    <div
      className="flex flex-col h-full shrink-0 overflow-hidden"
      style={{ width: "320px", background: "#0d0d0d", borderRight: "1px solid #1e1e1e" }}
    >
      {/* Project info */}
      <div className="px-5 pt-5 pb-4" style={{ borderBottom: "1px solid #1e1e1e" }}>
        <div
          className="font-mono font-medium text-white select-none mb-2"
          style={{ fontSize: "14px", letterSpacing: "0.15em" }}
        >
          Omnix
        </div>
        <p
          className="font-mono text-[#555] leading-snug"
          style={{
            fontSize: "11px",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {projectBrief}
        </p>
      </div>

      {/* Pipeline stages */}
      <div className="flex-1 overflow-y-auto">
        {STAGES.map((stage, idx) => {
          const isDone = idx < activeStageIndex
          const isActive = idx === activeStageIndex
          const isPending = idx > activeStageIndex

          // In checkpoint view, the active stage name changes
          const displayName =
            isActive && view === "checkpoint"
              ? "Plan  ·  awaiting approval"
              : stage.name

          return (
            <div
              key={stage.num}
              className="flex items-center px-5 py-2.5"
              style={{
                borderLeft: isActive ? "2px solid #6c4ef2" : "2px solid transparent",
                background: isActive ? "#0f0f0f" : "transparent",
                borderBottom: "1px solid #111",
              }}
            >
              {/* Stage number */}
              <span
                className="font-mono shrink-0 mr-3"
                style={{ fontSize: "10px", color: "#333", width: "18px" }}
              >
                {stage.num}
              </span>

              {/* Stage name */}
              <span
                className="font-mono flex-1"
                style={{
                  fontSize: "12px",
                  color: isDone ? "#555" : isActive ? "#aaa" : "#333",
                }}
              >
                {displayName}
              </span>

              {/* Status indicator */}
              <span style={{ fontSize: "12px", minWidth: "12px", textAlign: "right" }}>
                {isDone && (
                  <span className="font-mono" style={{ color: "#4f8ef7" }}>✓</span>
                )}
                {isActive && <BlinkCursor />}
              </span>
            </div>
          )
        })}
      </div>

      {/* Agent activity */}
      <div className="px-5 py-3" style={{ borderTop: "1px solid #1e1e1e" }}>
        <div
          className="font-mono mb-2"
          style={{ fontSize: "10px", color: "#333", letterSpacing: "0.08em" }}
        >
          AGENTS
        </div>
        <div className="space-y-1">
          {logs.slice(-6).map((log, idx, arr) => {
            const isNewest = idx === arr.length - 1
            return (
              <div
                key={idx}
                className="font-mono"
                style={{ fontSize: "10px", color: isNewest ? "#aaa" : "#555" }}
              >
                {log.time}&nbsp;&nbsp;{log.agent}&nbsp;&nbsp;{log.action}
              </div>
            )
          })}
          {logs.length === 0 && (
            <div className="font-mono" style={{ fontSize: "10px", color: "#333" }}>
              Waiting for pipeline…
            </div>
          )}
        </div>
      </div>

      {/* Checkpoint status */}
      <div
        className="px-5 py-3"
        style={{ borderTop: "1px solid #1e1e1e" }}
      >
        <div
          className="font-mono mb-1"
          style={{ fontSize: "10px", color: "#333", letterSpacing: "0.08em" }}
        >
          CHECKPOINT
        </div>
        <div className="font-mono" style={{ fontSize: "11px", color: "#aaa" }}>
          {checkpointLabel}
        </div>
      </div>
    </div>
  )
}

// ─── Right Column: Running view ───────────────────────────────────────────────

function RunningView({
  stage,
  agent,
  logs,
  pipelineStatus,
  output,
}: {
  stage: string
  agent: string
  logs: LogEntry[]
  pipelineStatus: string
  output: string | null
}) {
  const stageName = stage.replace(/_/g, " ")
  const stageNum = STAGE_MAP[stage] ?? 0
  const lastLog = logs.length > 0 ? logs[logs.length - 1] : null

  // Status-specific colors
  const statusColor =
    pipelineStatus === "complete"
      ? "#4ade80"
      : pipelineStatus === "failed"
      ? "#f87171"
      : "#4f8ef7"

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      {/* Breadcrumb */}
      <div
        className="font-mono mb-5"
        style={{ fontSize: "11px", color: "#555" }}
      >
        {String(stageNum + 1).padStart(2, "0")}&nbsp;&nbsp;{stageName}
      </div>

      {/* Output card */}
      <div
        style={{
          background: "#0f0f0f",
          border: "1px solid #1e1e1e",
          borderRadius: "4px",
          padding: "24px",
        }}
      >
        {/* Card header */}
        <div className="mb-1">
          <span className="font-mono" style={{ fontSize: "13px", color: "#e0e0e0" }}>
            {stageName}
          </span>
        </div>
        <div className="mb-5">
          <span className="font-mono" style={{ fontSize: "11px", color: "#555" }}>
            {lastLog ? `${agent}: ${lastLog.action}` : `${agent} agent is working…`}
          </span>
        </div>

        {/* Status indicator */}
        <div
          className="font-mono mb-5"
          style={{ fontSize: "12px", color: statusColor }}
        >
          {pipelineStatus === "running" && (
            <>Processing&nbsp;&nbsp;[<AnimatedBar />&nbsp;]</>
          )}
          {pipelineStatus === "complete" && "✓  Pipeline complete"}
          {pipelineStatus === "failed" && "✗  Pipeline failed"}
        </div>

        {/* Live log stream */}
        <div
          style={{
            background: "#0a0a0a",
            borderLeft: `2px solid ${statusColor}22`,
            padding: "16px",
            overflowX: "auto",
            maxHeight: "360px",
            overflowY: "auto",
          }}
        >
          {logs.length === 0 ? (
            <div className="font-mono" style={{ fontSize: "11px", color: "#333" }}>
              Waiting for agent activity…
            </div>
          ) : (
            logs.slice(-20).map((log, idx) => {
              const isLast = idx === Math.min(logs.length, 20) - 1
              return (
                <div
                  key={idx}
                  className="font-mono leading-6"
                  style={{ fontSize: "11px" }}
                >
                  <span style={{ color: "#333" }}>{log.time}</span>
                  &nbsp;&nbsp;
                  <span style={{ color: "#6c4ef2" }}>{log.agent}</span>
                  &nbsp;&nbsp;
                  <span style={{ color: isLast ? "#aaa" : "#555" }}>{log.action}</span>
                </div>
              )
            })
          )}
        </div>

        {/* Output (shown on complete / failed) */}
        {output && (pipelineStatus === "complete" || pipelineStatus === "failed") && (
          <div className="mt-4">
            <div className="font-mono mb-2" style={{ fontSize: "10px", color: "#333", letterSpacing: "0.08em" }}>
              OUTPUT
            </div>
            <pre
              className="font-mono whitespace-pre-wrap"
              style={{
                fontSize: "11px",
                color: "#aaa",
                maxHeight: "200px",
                overflowY: "auto",
                background: "#0a0a0a",
                padding: "12px",
                borderRadius: "3px",
              }}
            >
              {output.slice(0, 3000)}
            </pre>
          </div>
        )}

        {/* Footer */}
        <div className="mt-4">
          <span className="font-mono" style={{ fontSize: "11px", color: "#555" }}>
            {logs.length} events logged
          </span>
        </div>
      </div>
    </div>
  )
}

// ─── Animated progress bar ────────────────────────────────────────────────────

function AnimatedBar() {
  const [frame, setFrame] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % 4), 400)
    return () => clearInterval(id)
  }, [])
  const bars = ["==>     ", "===>    ", "====>   ", "=====>  "]
  return <span className="font-mono">{bars[frame]}</span>
}

// ─── Right Column: Checkpoint view ───────────────────────────────────────────

function CheckpointView({
  onApprove,
  onReject,
  checkpointType,
  checkpointContent,
}: {
  onApprove: () => void
  onReject: () => void
  checkpointType: string
  checkpointContent: string
}) {
  // Try to parse the content as JSON to extract a plan task list
  let planItems: string[] = []
  try {
    const parsed = JSON.parse(checkpointContent)
    if (parsed.tasks && Array.isArray(parsed.tasks)) {
      planItems = parsed.tasks.map(
        (t: { title?: string; description?: string }, i: number) =>
          t.title || t.description || `Task ${i + 1}`
      )
    }
  } catch {
    // Not JSON — show raw content below
  }

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      {/* Breadcrumb */}
      <div
        className="font-mono mb-5"
        style={{ fontSize: "11px", color: "#555" }}
      >
        Checkpoint&nbsp;&nbsp;·&nbsp;&nbsp;{checkpointType.replace(/_/g, " ")}
      </div>

      {/* Approval card */}
      <div
        style={{
          background: "#0f0f0f",
          border: "1px solid #1e1e1e",
          borderRadius: "4px",
          padding: "24px",
        }}
      >
        <div className="mb-1">
          <span className="font-mono" style={{ fontSize: "13px", color: "#e0e0e0" }}>
            Your review is required
          </span>
        </div>
        <div className="mb-6">
          <span className="font-mono" style={{ fontSize: "11px", color: "#555" }}>
            The system needs your approval to continue. Review the details below.
          </span>
        </div>

        {/* Plan list (if parsed) or raw content */}
        <div className="mb-8">
          {planItems.length > 0 ? (
            planItems.map((item, idx) => (
              <div
                key={idx}
                className="font-mono leading-7"
                style={{ fontSize: "12px", color: "#aaa" }}
              >
                {idx + 1}.&nbsp;&nbsp;{item}
              </div>
            ))
          ) : (
            <pre
              className="font-mono whitespace-pre-wrap"
              style={{ fontSize: "11px", color: "#aaa", maxHeight: "400px", overflowY: "auto" }}
            >
              {checkpointContent.slice(0, 3000)}
            </pre>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={onApprove}
            className="font-mono text-white transition-opacity hover:opacity-80"
            style={{
              background: "#6c4ef2",
              padding: "8px 20px",
              borderRadius: "3px",
              fontSize: "12px",
              border: "none",
            }}
          >
            Approve and Continue
          </button>
          <button
            onClick={onReject}
            className="font-mono transition-colors hover:text-[#e0e0e0]"
            style={{
              background: "transparent",
              color: "#aaa",
              border: "1px solid #2a2a2a",
              padding: "8px 20px",
              borderRadius: "3px",
              fontSize: "12px",
            }}
          >
            Request Changes
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Status Bar ───────────────────────────────────────────────────────────────

function StatusBar({ stage, agent, pipelineStatus }: { stage: string; agent: string; pipelineStatus: string }) {
  return (
    <div
      className="flex items-center gap-3 px-4 shrink-0"
      style={{
        height: "22px",
        background: "#111",
        borderTop: "1px solid #1e1e1e",
        fontSize: "11px",
      }}
    >
      <span className="font-mono" style={{ color: "#6c4ef2" }}>Omnix</span>
      <span className="font-mono" style={{ color: "#222" }}>|</span>
      <span className="font-mono" style={{ color: "#555" }}>Stage:</span>
      <span className="font-mono" style={{ color: "#555" }}>{stage}</span>
      <span className="font-mono" style={{ color: "#222" }}>|</span>
      <span className="font-mono" style={{ color: "#555" }}>Agent:</span>
      <span className="font-mono" style={{ color: "#555" }}>{agent}</span>
      <span className="font-mono" style={{ color: "#222" }}>|</span>
      <span className="font-mono" style={{ color: "#555" }}>Status:</span>
      <span className="font-mono" style={{ color: "#555" }}>{pipelineStatus}</span>
    </div>
  )
}

// ─── Pipeline Dashboard (Active state) ───────────────────────────────────────

function PipelineDashboard({
  projectBrief,
  view,
  onApprove,
  onReject,
  activeStageIndex,
  logs,
  stage,
  agent,
  pipelineStatus,
  checkpointType,
  checkpointContent,
  checkpointLabel,
  output,
}: {
  projectBrief: string
  view: "running" | "checkpoint"
  onApprove: () => void
  onReject: () => void
  activeStageIndex: number
  logs: LogEntry[]
  stage: string
  agent: string
  pipelineStatus: string
  checkpointType: string
  checkpointContent: string
  checkpointLabel: string
  output: string | null
}) {
  return (
    <div className="h-full w-full flex flex-col overflow-hidden" style={{ background: "#080808" }}>
      <div className="flex flex-1 overflow-hidden">
        {/* Left column */}
        <LeftColumn
          projectBrief={projectBrief}
          view={view}
          activeStageIndex={activeStageIndex}
          logs={logs}
          checkpointLabel={checkpointLabel}
        />

        {/* Right column */}
        <div className="flex flex-1 flex-col overflow-hidden" style={{ background: "#080808" }}>
          {view === "running" ? (
            <RunningView
              stage={stage}
              agent={agent}
              logs={logs}
              pipelineStatus={pipelineStatus}
              output={output}
            />
          ) : (
            <CheckpointView
              onApprove={onApprove}
              onReject={onReject}
              checkpointType={checkpointType}
              checkpointContent={checkpointContent}
            />
          )}
        </div>
      </div>

      {/* Status bar */}
      <StatusBar stage={stage} agent={agent} pipelineStatus={pipelineStatus} />
    </div>
  )
}

// ─── Root ─────────────────────────────────────────────────────────────────────

type AppState = "launch" | "active"
type PipelineView = "running" | "checkpoint"

export default function OmnixPage() {
  const [appState, setAppState] = useState<AppState>("launch")
  const [isFading, setIsFading] = useState(false)
  const [projectBrief, setProjectBrief] = useState("")
  const [pipelineView, setPipelineView] = useState<PipelineView>("running")

  // Live pipeline state
  const [runId, setRunId] = useState<string | null>(null)
  const [pipelineStatusData, setPipelineStatusData] = useState<PipelineStatus | null>(null)

  // Derived values from live status
  const liveLogs: LogEntry[] = pipelineStatusData?.logs ?? []
  const liveStage = pipelineStatusData?.stage ?? "intake"
  const liveAgent = pipelineStatusData?.agent ?? "System"
  const liveStatus = pipelineStatusData?.status ?? "running"
  const activeStageIndex = STAGE_MAP[liveStage] ?? 0
  const checkpointType = pipelineStatusData?.checkpoint?.type ?? ""
  const checkpointContent = pipelineStatusData?.checkpoint?.content ?? ""

  // Determine the checkpoint label for the sidebar
  const checkpointLabel = liveStatus === "checkpoint"
    ? `Awaiting: ${checkpointType.replace(/_/g, " ")}`
    : liveStatus === "complete"
    ? "Pipeline complete"
    : liveStatus === "failed"
    ? "Pipeline failed"
    : "Running…"

  // ── Poll status every 2 seconds ────────────────────────────
  useEffect(() => {
    if (!runId) return
    let active = true

    const poll = async () => {
      try {
        const status = await getStatus(runId)
        if (!active) return
        setPipelineStatusData(status)

        // Switch view based on status
        if (status.status === "checkpoint") {
          setPipelineView("checkpoint")
        } else {
          setPipelineView("running")
        }
      } catch {
        // Silently retry on network errors
      }
    }

    poll() // initial fetch
    const interval = setInterval(poll, 2000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [runId])

  // ── Handlers ───────────────────────────────────────────────
  const handleLaunchSubmit = useCallback(async (prompt: string) => {
    setProjectBrief(prompt)
    setIsFading(true)

    try {
      const { run_id } = await startPipeline(prompt, prompt)
      setRunId(run_id)
    } catch (err) {
      console.error("Failed to start pipeline:", err)
    }

    setTimeout(() => {
      setAppState("active")
      setIsFading(false)
    }, 400)
  }, [])

  const handleApprove = useCallback(async () => {
    if (!runId) return
    try {
      await sendApproval(runId, "approve", "")
    } catch (err) {
      console.error("Failed to send approval:", err)
    }
  }, [runId])

  const handleReject = useCallback(async () => {
    if (!runId) return
    try {
      await sendApproval(runId, "reject", "User requested changes.")
    } catch (err) {
      console.error("Failed to send rejection:", err)
    }
  }, [runId])

  return (
    <div className="h-screen w-screen bg-[#0d0d0d] overflow-hidden relative">
      {/* Launch screen */}
      <div
        className="absolute inset-0 transition-opacity duration-[400ms]"
        style={{
          opacity: appState === "launch" ? (isFading ? 0 : 1) : 0,
          pointerEvents: appState === "launch" && !isFading ? "auto" : "none",
        }}
      >
        <LaunchScreen onSubmit={handleLaunchSubmit} />
      </div>

      {/* Active pipeline dashboard */}
      <div
        className="absolute inset-0 transition-opacity duration-[400ms]"
        style={{
          opacity: appState === "active" ? 1 : 0,
          pointerEvents: appState === "active" ? "auto" : "none",
        }}
      >
        <PipelineDashboard
          projectBrief={projectBrief}
          view={pipelineView}
          onApprove={handleApprove}
          onReject={handleReject}
          activeStageIndex={activeStageIndex}
          logs={liveLogs}
          stage={liveStage}
          agent={liveAgent}
          pipelineStatus={liveStatus}
          checkpointType={checkpointType}
          checkpointContent={checkpointContent}
          checkpointLabel={checkpointLabel}
          output={pipelineStatusData?.output ?? null}
        />
      </div>
    </div>
  )
}
