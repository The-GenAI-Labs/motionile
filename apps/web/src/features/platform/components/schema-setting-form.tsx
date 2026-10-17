"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  jsonSchemaDefinitionSchema,
  validateSettingValue,
} from "@/features/platform/schemas/settings.schema";

export interface EditableSetting {
  key: string;
  description: string;
  value: SettingFormValue;
  schema: unknown;
  version: number;
}

interface SchemaSettingFormProps {
  setting: EditableSetting;
  onSave: (value: SettingFormValue, version: number) => Promise<void>;
  conflict?: boolean;
}

export type SettingFormValue = string | number | boolean | string[];

export function SchemaSettingForm({ setting, onSave, conflict = false }: SchemaSettingFormProps) {
  const schema = jsonSchemaDefinitionSchema.parse(setting.schema);
  const [value, setValue] = useState(setting.value);
  const [submitting, setSubmitting] = useState(false);
  const valid = validateSettingValue(schema, value);
  const inputId = `setting-${setting.key}`;
  const submit = async () => {
    if (!valid || submitting) {
      return;
    }
    setSubmitting(true);
    try {
      await onSave(value, setting.version);
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
      className="space-y-4 rounded-xl border bg-surface p-5"
    >
      <div>
        <Label htmlFor={inputId} className="font-mono">
          {setting.key}
        </Label>
        <p className="mt-1 text-sm text-muted-foreground">{setting.description}</p>
      </div>
      {schema.type === "boolean" ? (
        <div className="flex items-center gap-3">
          <Switch id={inputId} checked={value === true} onCheckedChange={setValue} />
          <Label htmlFor={inputId}>{value === true ? "Enabled" : "Disabled"}</Label>
        </div>
      ) : schema.type === "array" ? (
        <Textarea
          id={inputId}
          value={Array.isArray(value) ? value.join("\n") : ""}
          onChange={(event) => {
            setValue(
              event.target.value
                .split("\n")
                .map((item) => item.trim())
                .filter(Boolean),
            );
          }}
        />
      ) : schema.enum ? (
        <select
          id={inputId}
          value={String(value)}
          onChange={(event) => {
            setValue(event.target.value);
          }}
          className="h-9 w-full rounded-md border bg-surface px-3 text-sm focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {schema.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      ) : (
        <Input
          id={inputId}
          type={schema.type === "number" || schema.type === "integer" ? "number" : "text"}
          value={typeof value === "string" || typeof value === "number" ? value : ""}
          min={schema.minimum}
          max={schema.maximum}
          onChange={(event) => {
            setValue(
              schema.type === "number" || schema.type === "integer"
                ? event.target.valueAsNumber
                : event.target.value,
            );
          }}
        />
      )}
      {!valid ? (
        <p role="alert" className="text-sm text-destructive">
          Enter a value allowed by this setting.
        </p>
      ) : null}
      {conflict ? (
        <p role="alert" className="text-sm text-destructive">
          This setting changed elsewhere. Reload its latest value before saving again.
        </p>
      ) : null}
      <Button type="submit" disabled={!valid || submitting || conflict}>
        {submitting ? "Saving…" : "Save setting"}
      </Button>
    </form>
  );
}
