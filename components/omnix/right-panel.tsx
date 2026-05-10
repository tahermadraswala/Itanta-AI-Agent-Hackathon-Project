"use client"

interface LogEntry {
  timestamp: string
  agent: string
  action: string
}

interface RightPanelProps {
  logs: LogEntry[]
  isPipelineRunning: boolean
  selectedModel: string
  onModelChange: (model: string) => void
  view: "code" | "checkpoint"
  onApprove: () => void
  onRequestChanges: () => void
}

const MODELS = [
  "Claude Opus 4.6",
  "Claude Sonnet 4.0",
  "GPT-5 Mini",
  "Gemini 3 Flash",
]

export function RightPanel({
  logs,
  isPipelineRunning,
  selectedModel,
  onModelChange,
  view,
  onApprove,
  onRequestChanges,
}: RightPanelProps) {
  return (
    <div className="w-[380px] min-w-[380px] h-full border-l border-[#1e1e1e] flex flex-col bg-[#0d0d0d]">
      {/* Pipeline Activity Log */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-[#1e1e1e]">
          <span className="text-[11px] font-medium text-[#e0e0e0]">Pipeline</span>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-2">
          <div>
            {logs.map((log, idx) => (
              <div
                key={idx}
                className="text-[11px] leading-5 border-t border-[#1a1a1a] first:border-t-0 py-px"
              >
                <span className="text-[#555]">[{log.timestamp}]</span>{" "}
                <span className="text-[#e0e0e0]">{log.agent} → {log.action}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Divider */}
      <div className="h-px bg-[#1e1e1e]" />

      {/* Bottom section — varies by view */}
      {view === "checkpoint" ? (
        /* Checkpoint state: awaiting decision */
        <div className="px-3 py-4 flex flex-col gap-3">
          <span className="text-[11px] text-[#555] font-mono">Awaiting your decision</span>
          <div className="flex items-center gap-3">
            <button
              onClick={onRequestChanges}
              className="text-[11px] text-[#555] underline-offset-2 hover:underline transition-all font-mono"
            >
              Request Changes
            </button>
            <button
              onClick={onApprove}
              className="text-[11px] font-mono px-3 py-1 border border-[#333] text-[#888] rounded hover:border-[#6c4ef2] hover:text-[#e0e0e0] transition-colors"
            >
              Approve
            </button>
          </div>
        </div>
      ) : (
        /* Code generation state: input area */
        <div className="px-3 py-2">
          <div className="mb-1.5">
            <span className="omnix-gradient-text text-[11px] font-semibold">Omnix</span>
          </div>

          {/* Textarea */}
          <div className="relative">
            <textarea
              className="w-full h-20 bg-[#1a1a1a] border border-[#2a2a2a] rounded text-[11px] text-[#e0e0e0] p-2 resize-none focus:outline-none focus:border-[#3a3a3a] placeholder:text-[#555] disabled:cursor-not-allowed disabled:opacity-60 font-mono"
              placeholder={
                isPipelineRunning
                  ? "Pipeline running..."
                  : "Describe your project..."
              }
              disabled={isPipelineRunning}
            />
          </div>

          {/* Model Selector and Send Button */}
          <div className="flex items-center justify-between mt-2">
            <div className="relative">
              <select
                value={selectedModel}
                onChange={(e) => onModelChange(e.target.value)}
                disabled={isPipelineRunning}
                className="appearance-none bg-transparent border border-[#2a2a2a] rounded px-3 py-1.5 text-[11px] text-[#888] focus:outline-none focus:border-[#3a3a3a] disabled:cursor-not-allowed disabled:opacity-60 pr-6 font-mono"
              >
                {MODELS.map((model) => (
                  <option key={model} value={model} className="bg-[#1a1a1a]">
                    {model}
                  </option>
                ))}
              </select>
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[#555] text-[10px] pointer-events-none">
                ▾
              </span>
            </div>

            <button
              disabled={isPipelineRunning}
              className="px-4 py-1.5 text-[11px] border border-[#2a2a2a] rounded text-[#888] hover:text-[#e0e0e0] hover:border-[#6c4ef2] hover:bg-[#6c4ef2]/10 transition-colors disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-[#2a2a2a] disabled:hover:bg-transparent disabled:hover:text-[#888] font-mono"
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
