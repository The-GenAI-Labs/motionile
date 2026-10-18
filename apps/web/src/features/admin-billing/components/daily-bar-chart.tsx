import { useId } from "react";

export interface BarSeries {
  key: string;
  label: string;
  swatchClassName: string;
  barClassName: string;
  values: readonly number[];
}

interface DailyBarChartProps {
  title: string;
  days: readonly string[];
  series: readonly BarSeries[];
  formatValue: (value: number) => string;
}

const SLOT_WIDTH = 12;
const BAR_GAP = 1;
const CHART_HEIGHT = 120;

export const barHeight = (value: number, max: number): number =>
  max <= 0 || value <= 0 ? 0 : Math.max(1, Math.round((value / max) * CHART_HEIGHT));

export const chartSummary = (
  title: string,
  days: readonly string[],
  series: readonly BarSeries[],
  formatValue: (value: number) => string,
): string => {
  const first = days[0];
  const last = days.at(-1);
  const range = first !== undefined && last !== undefined ? `${first} to ${last}` : "no days";
  const totals = series
    .map(
      (item) => `${item.label} ${formatValue(item.values.reduce((sum, value) => sum + value, 0))}`,
    )
    .join(", ");
  return `${title}, ${range}. Totals: ${totals}.`;
};

export function DailyBarChart({ title, days, series, formatValue }: DailyBarChartProps) {
  const titleId = useId();
  const max = Math.max(0, ...series.flatMap((item) => item.values));
  const barWidth = Math.max(1, Math.floor((SLOT_WIDTH - BAR_GAP) / Math.max(series.length, 1)));
  return (
    <figure className="space-y-3">
      <svg
        role="img"
        aria-labelledby={titleId}
        viewBox={`0 0 ${String(Math.max(days.length, 1) * SLOT_WIDTH)} ${String(CHART_HEIGHT)}`}
        preserveAspectRatio="none"
        className="h-40 w-full"
      >
        <title id={titleId}>{chartSummary(title, days, series, formatValue)}</title>
        {days.map((day, dayIndex) =>
          series.map((item, seriesIndex) => {
            const value = item.values[dayIndex] ?? 0;
            const height = barHeight(value, max);
            return (
              <rect
                key={`${day}-${item.key}`}
                x={dayIndex * SLOT_WIDTH + seriesIndex * barWidth}
                y={CHART_HEIGHT - height}
                width={barWidth}
                height={height}
                className={item.barClassName}
              >
                <title>{`${day}: ${item.label} ${formatValue(value)}`}</title>
              </rect>
            );
          }),
        )}
      </svg>
      <figcaption>
        <ul className="flex flex-wrap gap-4 text-sm text-subtle-foreground">
          {series.map((item) => (
            <li key={item.key} className="flex items-center gap-2">
              <span aria-hidden="true" className={`size-3 rounded-sm ${item.swatchClassName}`} />
              {item.label}
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}
