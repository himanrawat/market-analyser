import * as React from "react"
import { cn } from "@/lib/utils"

interface SliderProps {
  min?: number
  max?: number
  step?: number
  value?: number[]
  defaultValue?: number[]
  onValueChange?: (value: number[]) => void
  className?: string
  disabled?: boolean
}

function Slider({
  min = 0,
  max = 100,
  step = 1,
  value,
  defaultValue,
  onValueChange,
  className,
  disabled,
}: Readonly<SliderProps>) {
  const current = value?.[0] ?? defaultValue?.[0] ?? min

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    onValueChange?.([Number(e.target.value)])
  }

  return (
    <div className={cn("relative flex w-full touch-none items-center", className)}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={current}
        onChange={handleChange}
        disabled={disabled}
        className="w-full h-1.5 appearance-none rounded-full bg-slate-700 cursor-pointer accent-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
      />
    </div>
  )
}

export { Slider }
