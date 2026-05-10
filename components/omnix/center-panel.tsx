"use client"

import { cn } from "@/lib/utils"

interface Tab {
  name: string
  active: boolean
}

const STAGES = [
  "Intake",
  "Clarify",
  "Architect",
  "Plan",
  "TDD",
  "Code",
  "Review",
  "Summary",
]

interface DiffLine {
  type: "unchanged" | "added" | "removed"
  content: string
  lineNumLeft?: number
  lineNumRight?: number
}

const PLAN_TASKS = [
  {
    id: 1,
    title: "Set up project structure and entry point",
    bullets: [
      "Create src/ directory with __init__.py",
      "Add main.py with CLI argument parsing",
      "Configure logging and error handling",
    ],
  },
  {
    id: 2,
    title: "Implement data ingestion layer",
    bullets: [
      "Define InputSchema with pydantic validation",
      "Support JSON and CSV input formats",
      "Add file-not-found and malformed-data error paths",
    ],
  },
  {
    id: 3,
    title: "Build core processing pipeline",
    bullets: [
      "Implement process_data() with strip + normalize",
      "Add validate_input() with type checking",
      "Write unit tests for both functions (12 cases)",
    ],
  },
  {
    id: 4,
    title: "Add output formatting and serialization",
    bullets: [
      "Implement OutputFormatter class",
      "Support JSON, CSV, and plain text output",
      "Ensure deterministic ordering for diff stability",
    ],
  },
  {
    id: 5,
    title: "Integration tests and CI configuration",
    bullets: [
      "Write end-to-end test with fixture data",
      "Configure pytest and coverage thresholds",
      "Add GitHub Actions workflow for CI",
    ],
  },
  {
    id: 6,
    title: "Documentation and review artifacts",
    bullets: [
      "Generate architecture.md from system diagram",
      "Write summary.md with key decisions",
      "Produce review_report.md with lint results",
    ],
  },
]

interface CenterPanelProps {
  tabs: Tab[]
  activeTab: string | null
  onTabSelect: (tabName: string) => void
  onTabClose: (tabName: string) => void
  currentStage: string
  diffContent: {
    left: DiffLine[]
    right: DiffLine[]
  }
  view: "code" | "checkpoint"
  onViewChange: (view: "code" | "checkpoint") => void
  onApprove: () => void
  onRequestChanges: () => void
}

function TabBar({
  tabs,
  activeTab,
  onTabSelect,
  onTabClose,
  view,
  onViewChange,
}: {
  tabs: Tab[]
  activeTab: string | null
  onTabSelect: (tabName: string) => void
  onTabClose: (tabName: string) => void
  view: "code" | "checkpoint"
  onViewChange: (view: "code" | "checkpoint") => void
}) {
  return (
    <div className="flex items-stretch border-b border-[#1e1e1e] bg-[#0d0d0d] overflow-x-auto h-8">
      {tabs.map((tab) => {
        const isActive = tab.name === activeTab && view === "code"
        return (
          <div
            key={tab.name}
            className={cn(
              "flex items-center gap-1.5 px-3 border-r border-[#1e1e1e] cursor-pointer group shrink-0 relative",
              isActive ? "text-[#e0e0e0]" : "text-[#444] hover:text-[#888]"
            )}
            onClick={() => {
              onViewChange("code")
              onTabSelect(tab.name)
            }}
          >
            {isActive && (
              <div
                className="absolute bottom-0 left-0 right-0 h-[1px] omnix-gradient-bar"
              />
            )}
            <span className="text-[11px]">{tab.name}</span>
            <button
              className="text-[#333] hover:text-[#888] opacity-0 group-hover:opacity-100 transition-opacity text-sm leading-none"
              onClick={(e) => {
                e.stopPropagation()
                onTabClose(tab.name)
              }}
            >
              ×
            </button>
          </div>
        )
      })}

      {/* Checkpoint tab */}
      <div
        className={cn(
          "flex items-center px-3 border-r border-[#1e1e1e] cursor-pointer shrink-0 relative",
          view === "checkpoint" ? "text-[#e0e0e0]" : "text-[#444] hover:text-[#888]"
        )}
        onClick={() => onViewChange("checkpoint")}
      >
        {view === "checkpoint" && (
          <div className="absolute bottom-0 left-0 right-0 h-[1px] omnix-gradient-bar" />
        )}
        <span className="text-[11px]">Checkpoint</span>
      </div>
    </div>
  )
}

function StageProgressBar({ currentStage }: { currentStage: string }) {
  return (
    <div className="flex items-end gap-4 px-4 py-1.5 border-b border-[#1e1e1e] bg-[#0a0a0a]">
      {STAGES.map((stage) => {
        const isActive = currentStage === stage
        return (
          <div key={stage} className="flex flex-col items-center pb-px">
            <span
              className={cn(
                "text-[10px] leading-none pb-1",
                isActive ? "text-[#e0e0e0]" : "text-[#555]"
              )}
            >
              {stage}
            </span>
            {isActive && (
              <div className="w-full h-[2px] omnix-gradient-bar" />
            )}
          </div>
        )
      })}
    </div>
  )
}

function DiffView({ diffContent }: { diffContent: { left: DiffLine[]; right: DiffLine[] } }) {
  return (
    <div className="flex-1 overflow-auto flex flex-col">
      {/* File path headers */}
      <div className="flex shrink-0 border-b border-[#1e1e1e]">
        <div className="flex-1 border-r border-[#1e1e1e] bg-[#111] px-3 py-1">
          <span className="text-[11px] text-[#666] font-mono">src/main.py</span>
        </div>
        <div className="flex-1 bg-[#111] px-3 py-1">
          <span className="text-[11px] text-[#666] font-mono">src/main.py (modified)</span>
        </div>
      </div>
      <div className="flex flex-1 overflow-auto">
        {/* Left side - removed */}
        <div className="flex-1 border-r border-[#1e1e1e] overflow-auto">
          <div className="text-xs">
            {diffContent.left.map((line, idx) => (
              <div
                key={idx}
                className={cn(
                  "flex",
                  line.type === "removed" && "bg-[rgba(239,68,68,0.08)]"
                )}
              >
                <span className="w-8 text-right pr-2 text-[#444] select-none shrink-0 leading-5">
                  {line.lineNumLeft ?? ""}
                </span>
                <span
                  className={cn(
                    "flex-1 leading-5 pl-2 pr-4",
                    line.type === "removed" ? "text-[#ef4444]" : "text-[#888]"
                  )}
                >
                  {line.type === "removed" && (
                    <span className="mr-2 text-[#ef4444]">-</span>
                  )}
                  {line.content}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Right side - added */}
        <div className="flex-1 overflow-auto">
          <div className="text-xs">
            {diffContent.right.map((line, idx) => (
              <div
                key={idx}
                className={cn(
                  "flex",
                  line.type === "added" && "bg-[rgba(34,197,94,0.08)]"
                )}
              >
                <span className="w-8 text-right pr-2 text-[#444] select-none shrink-0 leading-5">
                  {line.lineNumRight ?? ""}
                </span>
                <span
                  className={cn(
                    "flex-1 leading-5 pl-2 pr-4",
                    line.type === "added" ? "text-[#22c55e]" : "text-[#888]"
                  )}
                >
                  {line.type === "added" && (
                    <span className="mr-2 text-[#22c55e]">+</span>
                  )}
                  {line.content}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function CheckpointView({
  onApprove,
  onRequestChanges,
}: {
  onApprove: () => void
  onRequestChanges: () => void
}) {
  return (
    <div className="flex-1 overflow-auto flex flex-col">
      <div className="px-8 pt-8 pb-4">
        {/* Header — no card, no border */}
        <p className="text-[13px] text-[#e0e0e0] mb-6">
          Checkpoint&nbsp;&nbsp;·&nbsp;&nbsp;Plan Approval
        </p>

        {/* Rendered plan */}
        <div className="font-mono text-[11px] leading-6 text-[#aaa] space-y-5">
          {PLAN_TASKS.map((task) => (
            <div key={task.id}>
              <p className="text-[#e0e0e0]">
                {task.id}. {task.title}
              </p>
              <ul className="mt-1 space-y-0.5 pl-5">
                {task.bullets.map((bullet, bidx) => (
                  <li key={bidx} className="before:content-['-'] before:mr-2 before:text-[#444]">
                    {bullet}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {/* Action buttons — bottom right */}
      <div className="flex-1" />
      <div className="flex justify-end gap-4 px-8 py-6 border-t border-[#1e1e1e]">
        <button
          onClick={onRequestChanges}
          className="text-[11px] text-[#555] underline-offset-2 hover:underline transition-all font-mono"
        >
          Request Changes
        </button>
        <button
          onClick={onApprove}
          className="text-[11px] font-mono px-4 py-1.5 border border-[#333] text-[#888] rounded hover:border-[#6c4ef2] hover:text-[#e0e0e0] transition-colors"
        >
          Approve
        </button>
      </div>
    </div>
  )
}

export function CenterPanel({
  tabs,
  activeTab,
  onTabSelect,
  onTabClose,
  currentStage,
  diffContent,
  view,
  onViewChange,
  onApprove,
  onRequestChanges,
}: CenterPanelProps) {
  return (
    <div className="flex-1 flex flex-col h-full bg-[#0d0d0d]">
      {/* Tab Bar */}
      <TabBar
        tabs={tabs}
        activeTab={activeTab}
        onTabSelect={onTabSelect}
        onTabClose={onTabClose}
        view={view}
        onViewChange={onViewChange}
      />

      {/* Stage Progress Bar */}
      <StageProgressBar currentStage={currentStage} />

      {/* Content */}
      {view === "code" ? (
        <DiffView diffContent={diffContent} />
      ) : (
        <CheckpointView onApprove={onApprove} onRequestChanges={onRequestChanges} />
      )}
    </div>
  )
}
