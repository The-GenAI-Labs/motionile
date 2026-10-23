interface LevelMeterProps {
  level: number;
  label?: string;
}

export function LevelMeter({ level, label = "Microphone level" }: LevelMeterProps) {
  const value = Math.max(0, Math.min(100, Math.round(level)));
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-valuetext={`${String(value)} percent`}
      className="h-2 w-full overflow-hidden rounded-full bg-elevated"
    >
      <div
        aria-hidden="true"
        className="h-full bg-success transition-[width] duration-100 motion-reduce:transition-none"
        style={{ width: `${String(value)}%` }}
      />
    </div>
  );
}
