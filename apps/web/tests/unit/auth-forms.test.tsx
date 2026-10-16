import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { OtpInput } from "@/features/auth/components/otp-input";
import { authErrorMessage, authErrorMessages } from "@/features/auth/errors";
import {
  identifierSchema,
  registerSchema,
  resetPasswordSchema,
} from "@/features/auth/schemas/auth.schema";
import { ApiError } from "@/lib/api/api-error";

const error = (code: string, retryAfterSeconds?: number) =>
  new ApiError({
    kind: "http",
    code,
    status: 400,
    title: "Error",
    detail: null,
    requestId: "request-123",
    ...(retryAfterSeconds === undefined ? {} : { retryAfterSeconds }),
  });

describe("auth schemas and errors", () => {
  it.each([
    ["ASHA@example.com", "asha@example.com"],
    ["9876543210", "+919876543210"],
    ["+44 7911 123456", "+447911123456"],
  ])("normalizes %s", (input, output) => {
    expect(identifierSchema.parse(input)).toBe(output);
  });
  it.each(["invalid", "abc@", "+123", "12345678901234567890"])("rejects %s", (input) => {
    expect(identifierSchema.safeParse(input).success).toBe(false);
  });
  it("requires consent, matching passwords and the contract password bounds", () => {
    const valid = {
      name: "Asha",
      identifier: "asha@example.com",
      password: "safe-password-123",
      confirmPassword: "safe-password-123",
      terms: true,
    };
    expect(registerSchema.safeParse(valid).success).toBe(true);
    expect(registerSchema.safeParse({ ...valid, terms: false }).success).toBe(false);
    expect(registerSchema.safeParse({ ...valid, confirmPassword: "different" }).success).toBe(
      false,
    );
    for (const password of ["short", "a".repeat(129)])
      expect(
        registerSchema.safeParse({ ...valid, password, confirmPassword: password }).success,
      ).toBe(false);
    expect(
      resetPasswordSchema.safeParse({
        code: "123456",
        newPassword: "safe-password-123",
        confirmPassword: "different",
      }).success,
    ).toBe(false);
  });
  it.each(Object.keys(authErrorMessages))("maps %s to a non-revealing message", (code) => {
    expect(authErrorMessage(error(code))).toBe(authErrorMessages[code]);
  });
  it("reports cooldowns and gives a request ID for unknown errors", () => {
    expect(authErrorMessage(error("rate_limited", 42))).toContain("42 seconds");
    expect(authErrorMessage(error("otp_cooldown", 12))).toContain("12 seconds");
    expect(authErrorMessage(error("unexpected"))).toContain("Request ID: request-123");
  });
});

describe("OTP field", () => {
  const complete = vi.fn();
  function Harness() {
    const [value, setValue] = useState("");
    return <OtpInput value={value} onChange={setValue} onComplete={complete} />;
  }
  it("pastes a whole code, focuses the final box and submits once", () => {
    complete.mockClear();
    render(<Harness />);
    fireEvent.paste(screen.getByRole("textbox", { name: "Digit 1" }), {
      clipboardData: { getData: () => "123 456" },
    });
    expect(complete).toHaveBeenCalledExactlyOnceWith("123456");
    expect(screen.getByRole("textbox", { name: "Digit 6" })).toHaveFocus();
    expect(screen.getByRole("group", { name: "Verification code" })).toBeInTheDocument();
  });
  it("supports numeric typing, arrow keys and backwards deletion", () => {
    render(<Harness />);
    const first = screen.getByRole("textbox", { name: "Digit 1" });
    const second = screen.getByRole("textbox", { name: "Digit 2" });
    fireEvent.change(first, { target: { value: "1" } });
    expect(second).toHaveFocus();
    fireEvent.keyDown(second, { key: "ArrowLeft" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    fireEvent.keyDown(second, { key: "Backspace" });
    expect(first).toHaveValue("");
    expect(first).toHaveFocus();
    expect(first).toHaveAttribute("autocomplete", "one-time-code");
    expect(first).toHaveAttribute("inputmode", "numeric");
  });
});
