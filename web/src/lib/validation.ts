export const PASSWORD_MIN = 8;

export function validateEmail(email: string): string | null {
  const v = email.trim();
  if (!v) return "Enter your email address.";
  // Deliberately simple: the confirmation email is the real check.
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)) return "That doesn't look like an email address.";
  return null;
}

export function validateName(name: string): string | null {
  const v = name.trim();
  if (!v) return "Enter your name.";
  if (v.length > 80) return "Keep your name under 80 characters.";
  return null;
}

export interface PasswordCheck {
  id: string;
  label: string;
  ok: boolean;
}

export function passwordChecks(pw: string): PasswordCheck[] {
  return [
    { id: "length", label: `At least ${PASSWORD_MIN} characters`, ok: pw.length >= PASSWORD_MIN },
    { id: "letter", label: "A letter", ok: /[A-Za-z]/.test(pw) },
    { id: "number", label: "A number", ok: /\d/.test(pw) },
  ];
}

/** 0 (empty) to 4 (strong). Rewards length and variety; the checks above are the hard requirement. */
export function passwordStrength(pw: string): 0 | 1 | 2 | 3 | 4 {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= PASSWORD_MIN) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/[A-Za-z]/.test(pw) && /\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (/^(.)\1+$/.test(pw) || /^(password|12345678|qwerty)/i.test(pw)) score = 1;
  return Math.max(1, Math.min(4, score)) as 1 | 2 | 3 | 4;
}

export const STRENGTH_LABEL = ["", "Weak", "Fair", "Good", "Strong"] as const;

export function validateNewPassword(pw: string): string | null {
  if (!pw) return "Choose a password.";
  const missing = passwordChecks(pw).filter((c) => !c.ok);
  if (missing.length) return `Your password needs ${missing.map((c) => c.label.toLowerCase()).join(", ")}.`;
  return null;
}

export function validateConfirm(pw: string, confirm: string): string | null {
  if (!confirm) return "Type your password again.";
  if (pw !== confirm) return "The passwords don't match.";
  return null;
}

/**
 * Where to go after signing in. Only same-site paths are allowed, so a crafted
 * link like /login?next=https://evil.example can't send people elsewhere.
 */
export function safeNext(next: string | null | undefined, fallback = "/app"): string {
  if (!next) return fallback;
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (/^\/(login|signup|auth\/callback)\b/.test(next)) return fallback;
  return next;
}
