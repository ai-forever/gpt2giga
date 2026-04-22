export type SetupPage =
  | "setup"
  | "setup-claim"
  | "setup-application"
  | "setup-gigachat"
  | "setup-security";

export type SetupSection = "claim" | "application" | "gigachat" | "security";

export interface SetupNextStep {
  href: string;
  label: string;
  note: string;
}
