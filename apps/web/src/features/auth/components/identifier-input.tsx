"use client";

import { parsePhoneNumberFromString } from "libphonenumber-js";
import { type ComponentProps, useState } from "react";

import { Input } from "@/components/ui/input";

export function IdentifierInput(props: ComponentProps<typeof Input>) {
  const [phone, setPhone] = useState(false);
  const [country, setCountry] = useState("+91");
  return (
    <div className="space-y-2">
      <Input
        {...props}
        autoComplete="username"
        onChange={(event) => {
          setPhone(/^[+\d\s()-]+$/.test(event.target.value));
          const parsed = parsePhoneNumberFromString(event.target.value, "IN");
          if (parsed) setCountry(`+${parsed.countryCallingCode}`);
          props.onChange?.(event);
        }}
      />
      {phone ? (
        <label className="block text-sm text-muted-foreground">
          Country code
          <select
            aria-label="Country code"
            value={country}
            className="ml-2 rounded border bg-surface p-2"
            onChange={(event) => {
              const input = document.getElementById(props.id ?? "identifier");
              const selected = event.target.value;
              setCountry(selected);
              if (input instanceof HTMLInputElement) {
                const national =
                  parsePhoneNumberFromString(input.value, "IN")?.nationalNumber ??
                  input.value.replace(/\D/g, "");
                input.value = selected + national;
                props.onChange?.({ ...event, target: input, currentTarget: input });
              }
            }}
          >
            <option value="+91">India (+91)</option>
            <option value="+1">US / Canada (+1)</option>
            <option value="+44">UK (+44)</option>
            <option value="+61">Australia (+61)</option>
            {!["+91", "+1", "+44", "+61"].includes(country) ? (
              <option value={country}>{country}</option>
            ) : null}
          </select>
        </label>
      ) : null}
    </div>
  );
}
