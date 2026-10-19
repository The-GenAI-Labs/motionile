"use client";

import { XIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { titleCase } from "@/lib/utils/format";

export interface FilterOption {
  value: string;
  label: string;
}

export const optionsFromValues = (
  values: readonly string[],
  labels: Readonly<Record<string, string>> = {},
): FilterOption[] => values.map((value) => ({ value, label: labels[value] ?? titleCase(value) }));

export const BOOLEAN_OPTIONS: readonly FilterOption[] = [
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
];

export const booleanFromValue = (value: string): boolean | null => {
  if (value === "true") {
    return true;
  }
  return value === "false" ? false : null;
};

export const valueFromBoolean = (value: boolean | null): string =>
  value === null ? "" : String(value);

interface FilterPanelProps {
  label: string;
  onClear: () => void;
  children: ReactNode;
}

export function FilterPanel({ label, onClear, children }: FilterPanelProps) {
  return (
    <section
      aria-label={label}
      className="grid gap-3 rounded-xl border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      {children}
      <div className="flex items-end">
        <Button type="button" variant="outline" onClick={onClear}>
          <XIcon aria-hidden="true" /> Clear filters
        </Button>
      </div>
    </section>
  );
}

interface SelectFilterProps {
  id: string;
  label: string;
  value: string;
  options: readonly FilterOption[];
  onChange: (value: string) => void;
  anyLabel?: string;
}

export function SelectFilter({
  id,
  label,
  value,
  options,
  onChange,
  anyLabel = "Any",
}: SelectFilterProps) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <NativeSelect
        id={id}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        <option value="">{anyLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}

interface TextFilterProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "date" | "search";
  placeholder?: string;
}

export function TextFilter({
  id,
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: TextFilterProps) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        {...(placeholder ? { placeholder } : {})}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
    </div>
  );
}
