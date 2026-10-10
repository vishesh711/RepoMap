import { describe, expect, it } from "vitest";
import {
  passwordChecks, passwordStrength, safeNext, validateConfirm, validateEmail, validateName, validateNewPassword,
} from "./validation";

describe("validateEmail", () => {
  it("accepts normal addresses and trims spaces", () => {
    expect(validateEmail("dev@example.com")).toBeNull();
    expect(validateEmail("  dev.vishesh+repomap@mail.co.uk ")).toBeNull();
  });
  it("explains what's wrong", () => {
    expect(validateEmail("")).toBe("Enter your email address.");
    expect(validateEmail("dev@")).toMatch(/doesn't look like/);
    expect(validateEmail("dev example.com")).toMatch(/doesn't look like/);
  });
});

describe("passwords", () => {
  it("lists exactly the missing requirements", () => {
    expect(validateNewPassword("")).toBe("Choose a password.");
    expect(validateNewPassword("abcdefgh")).toBe("Your password needs a number.");
    expect(validateNewPassword("12")).toMatch(/at least 8 characters, a letter/);
    expect(validateNewPassword("repomap2026")).toBeNull();
    expect(passwordChecks("abc12345").every((c) => c.ok)).toBe(true);
  });
  it("scores strength by length and variety", () => {
    expect(passwordStrength("")).toBe(0);
    expect(passwordStrength("aaaaaaaa")).toBe(1);
    expect(passwordStrength("password123")).toBe(1);
    expect(passwordStrength("repomap2026")).toBe(2);
    expect(passwordStrength("Repomap-2026-Maps")).toBe(4);
  });
  it("checks the confirmation", () => {
    expect(validateConfirm("abc12345", "")).toBe("Type your password again.");
    expect(validateConfirm("abc12345", "abc1234")).toBe("The passwords don't match.");
    expect(validateConfirm("abc12345", "abc12345")).toBeNull();
  });
});

describe("validateName", () => {
  it("requires a reasonable name", () => {
    expect(validateName("  ")).toBe("Enter your name.");
    expect(validateName("Vishesh")).toBeNull();
    expect(validateName("x".repeat(81))).toMatch(/under 80/);
  });
});

describe("safeNext", () => {
  it("keeps same-site paths", () => {
    expect(safeNext("/app/repos?tab=2")).toBe("/app/repos?tab=2");
  });
  it("blocks redirects to other sites", () => {
    expect(safeNext("https://evil.example")).toBe("/app");
    expect(safeNext("//evil.example/path")).toBe("/app");
    expect(safeNext("/\\evil.example")).toBe("/app");
    expect(safeNext("javascript:alert(1)")).toBe("/app");
  });
  it("doesn't loop back into the auth pages", () => {
    expect(safeNext("/login")).toBe("/app");
    expect(safeNext("/auth/callback?code=x")).toBe("/app");
    expect(safeNext(null)).toBe("/app");
  });
});
