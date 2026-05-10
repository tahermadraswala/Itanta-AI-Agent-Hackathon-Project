interface StatusBarProps {
  currentStage: string
  activeAgent: string
  lastCheckpoint: string
}

export function StatusBar({
  currentStage,
  activeAgent,
  lastCheckpoint,
}: StatusBarProps) {
  return (
    <div
      className="border-t border-[#1e1e1e] flex items-center px-3 gap-3 bg-[#111] shrink-0"
      style={{ height: "22px", fontSize: "11px" }}
    >
      {/* "Omnix" gradient via background-clip */}
      <span
        className="font-semibold"
        style={{
          background: "linear-gradient(90deg, #6c4ef2, #4f8ef7)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        Omnix
      </span>
      <span className="text-[#333]">|</span>
      <span className="text-[#555]">Stage:</span>
      <span className="text-[#aaa]">{currentStage}</span>
      <span className="text-[#333]">|</span>
      <span className="text-[#555]">Agent:</span>
      <span className="text-[#aaa]">{activeAgent}</span>
      <span className="text-[#333]">|</span>
      <span className="text-[#555]">Checkpoint:</span>
      <span className="text-[#aaa]">{lastCheckpoint}</span>
    </div>
  )
}
