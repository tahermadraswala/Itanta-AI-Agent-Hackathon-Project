"use client"

import { cn } from "@/lib/utils"

interface FileItem {
  name: string
  type: "file" | "folder"
  children?: FileItem[]
  active?: boolean
}

interface LeftPanelProps {
  files: FileItem[]
  activeFile: string | null
  onFileSelect: (fileName: string) => void
  currentStage: string
}

function FileTreeItem({
  item,
  depth = 0,
  activeFile,
  onFileSelect,
}: {
  item: FileItem
  depth?: number
  activeFile: string | null
  onFileSelect: (fileName: string) => void
}) {
  const isActive = item.name === activeFile

  if (item.type === "folder") {
    return (
      <div>
        <div
          className="flex items-center py-0.5 text-[#555] hover:text-[#888] cursor-pointer"
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          <span className="mr-1.5 text-[10px]">▾</span>
          <span className="text-[11px]">{item.name}/</span>
        </div>
        {item.children?.map((child) => (
          <FileTreeItem
            key={child.name}
            item={child}
            depth={depth + 1}
            activeFile={activeFile}
            onFileSelect={onFileSelect}
          />
        ))}
      </div>
    )
  }

  return (
    <div
      className={cn(
        "flex items-center py-0.5 cursor-pointer text-[11px] transition-colors",
        isActive
          ? "text-[#e0e0e0] bg-[#1e3a5f]"
          : "text-[#555] hover:text-[#888] hover:bg-[#1a1a1a]"
      )}
      style={{ paddingLeft: `${depth * 12 + 20}px` }}
      onClick={() => onFileSelect(item.name)}
    >
      <span>{item.name}</span>
    </div>
  )
}

export function LeftPanel({
  files,
  activeFile,
  onFileSelect,
  currentStage,
}: LeftPanelProps) {
  return (
    <div className="w-[220px] min-w-[220px] h-full border-r border-[#1e1e1e] flex flex-col bg-[#0d0d0d]">
      {/* Logo / Wordmark */}
      <div className="px-4 py-4 border-b border-[#1e1e1e]">
        <div className="flex items-center gap-1.5">
          {/* ">>" chevron in gradient */}
          <span
            className="omnix-gradient-text font-bold text-sm leading-none"
            aria-hidden="true"
          >
            {">>"}
          </span>
          {/* Omnix wordmark in white, letter-spaced */}
          <span
            className="text-[13px] font-semibold text-[#e0e0e0]"
            style={{ letterSpacing: "0.15em" }}
          >
            Omnix
          </span>
        </div>
        <p className="text-[11px] text-[#555] mt-1">multi-agent-demo</p>
      </div>

      {/* File Tree */}
      <div className="flex-1 overflow-y-auto">
        {/* Workspace Section */}
        <div className="pt-3">
          <div className="px-4 pb-2">
            <span className="text-[10px] font-medium text-[#555] tracking-wider uppercase">
              Workspace
            </span>
          </div>
          <div>
            {files.map((file) => (
              <FileTreeItem
                key={file.name}
                item={file}
                activeFile={activeFile}
                onFileSelect={onFileSelect}
              />
            ))}
          </div>
        </div>

        {/* Artifacts Section */}
        <div className="pt-4">
          <div className="px-4 pb-2">
            <span className="text-[10px] font-medium text-[#555] tracking-wider uppercase">
              Artifacts
            </span>
          </div>
          <div className="px-4 py-1">
            <span className="text-[10px] text-[#444]">6 generated</span>
          </div>
        </div>

        {/* Logs Section */}
        <div className="pt-4">
          <div className="px-4 pb-2">
            <span className="text-[10px] font-medium text-[#555] tracking-wider uppercase">
              Logs
            </span>
          </div>
          <div className="px-4 py-1">
            <span className="text-[10px] text-[#444]">pipeline.log</span>
          </div>
        </div>
      </div>

      {/* Pipeline Stage Indicator — gradient left border */}
      <div className="border-t border-[#1e1e1e] px-4 py-3">
        <div className="flex items-center">
          {/* Gradient vertical bar */}
          <div
            className="w-0.5 h-4 mr-3 shrink-0"
            style={{ background: "linear-gradient(180deg, #6c4ef2, #4f8ef7)" }}
          />
          <div>
            <span className="text-[10px] text-[#555] uppercase tracking-wider block">
              Stage
            </span>
            <span className="text-[11px] text-[#e0e0e0]">{currentStage}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
