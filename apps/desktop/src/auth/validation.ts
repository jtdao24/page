export type FieldErrors = Partial<Record<"name" | "email" | "password" | "confirmPassword", string>>;

function emailError(email: string): string | undefined {
  if (!email.trim()) return "Enter your email address.";
  if (email.trim().length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return "Enter a valid email address.";
}

export function validateLogin(input: { email: string; password: string }): FieldErrors {
  const errors: FieldErrors = {};
  const email = emailError(input.email);
  if (email) errors.email = email;
  if (!input.password) errors.password = "Enter your password.";
  return errors;
}

export function validateSignup(input: { name: string; email: string; password: string; confirmPassword: string }): FieldErrors {
  const errors = validateLogin(input);
  if (!input.name.trim()) errors.name = "Enter your name.";
  else if (input.name.trim().length > 100) errors.name = "Keep your name to 100 characters or fewer.";
  if (input.password && input.password.length < 12) errors.password = "Use at least 12 characters.";
  if (input.password.length > 128) errors.password = "Use 128 characters or fewer.";
  if (!input.confirmPassword) errors.confirmPassword = "Confirm your password.";
  else if (input.password !== input.confirmPassword) errors.confirmPassword = "Your passwords don’t match.";
  return errors;
}

export function validatePasswordReset(email: string): FieldErrors {
  const error = emailError(email);
  return error ? { email: error } : {};
}
