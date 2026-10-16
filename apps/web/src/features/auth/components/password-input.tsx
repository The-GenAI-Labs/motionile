"use client";
import type { ComponentProps } from "react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
export function PasswordInput({
  strength = false,
  ...props
}: ComponentProps<typeof Input> & { strength?: boolean }) {
  const [visible, setVisible] = useState(false);
  const [value, setValue] = useState("");
  const [score, setScore] = useState(0);
  useEffect(() => {
    if (!strength || !value) return;
    let active = true;
    void Promise.all([
      import("@zxcvbn-ts/core"),
      import("@zxcvbn-ts/language-common"),
      import("@zxcvbn-ts/language-en"),
    ]).then(([core, common, language]) => {
      const checker = new core.ZxcvbnFactory({
        dictionary: { ...common.dictionary, ...language.dictionary },
        graphs: common.adjacencyGraphs,
        translations: language.translations,
      });
      if (active) setScore(checker.check(value).score);
    });
    return () => {
      active = false;
    };
  }, [strength, value]);
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          {...props}
          type={visible ? "text" : "password"}
          onChange={(event) => {
            setValue(event.target.value);
            props.onChange?.(event);
          }}
        />
        <Button
          type="button"
          variant="outline"
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          onClick={() => {
            setVisible(!visible);
          }}
        >
          {visible ? "Hide" : "Show"}
        </Button>
      </div>
      {strength ? (
        <div className="text-sm text-muted-foreground">
          <meter
            aria-label="Password strength"
            min={0}
            max={4}
            value={value ? score : 0}
            className="w-full"
          />
          <p>{["Very weak", "Weak", "Fair", "Strong", "Very strong"][value ? score : 0]}</p>
          <ul>
            <li>Use 10–128 characters.</li>
            <li>A long, unique passphrase is easier to remember.</li>
          </ul>
        </div>
      ) : null}
    </div>
  );
}
