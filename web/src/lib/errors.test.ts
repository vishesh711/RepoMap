import { describe, expect, it } from "vitest";
import { friendlyError } from "./errors";
import { AuthNotConfiguredError } from "./supabase";

describe("friendlyError", () => {
  it("maps Supabase auth errors to plain explanations", () => {
    expect(friendlyError({ message: "Invalid login credentials", status: 400 }).kind).toBe("invalid_credentials");
    expect(friendlyError({ message: "Email not confirmed" }).kind).toBe("email_not_confirmed");
    expect(friendlyError({ message: "User already registered" }).kind).toBe("already_registered");
    expect(friendlyError({ code: "user_already_exists", message: "x" }).kind).toBe("already_registered");
    expect(friendlyError({ message: "Unsupported provider: provider is not enabled" }).kind).toBe("provider_disabled");
    expect(friendlyError({ message: "Email link is invalid or has expired", code: "otp_expired" }).kind).toBe("expired_link");
  });
  it("recognises rate limits by status or wording", () => {
    expect(friendlyError({ status: 429, message: "Too Many Requests" }).kind).toBe("rate_limited");
    expect(friendlyError({ message: "For security purposes, you can only request this after 42 seconds." }).kind).toBe("rate_limited");
  });
  it("recognises network failures", () => {
    expect(friendlyError(new TypeError("Failed to fetch")).kind).toBe("network");
  });
  it("explains the missing configuration", () => {
    expect(friendlyError(new AuthNotConfiguredError()).message).toMatch(/web\/.env.local/);
  });
  it("falls back to the original message, as a sentence", () => {
    expect(friendlyError({ message: "Something odd" }).message).toBe("Something odd.");
    expect(friendlyError(undefined).message).toBe("Something went wrong. Try again.");
  });
});
