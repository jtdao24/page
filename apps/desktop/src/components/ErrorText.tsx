import type { DesktopError } from "../core/types";

/** Safe, actionable wording for errors whose fixed API message needs context. */
function explain(error: DesktopError): string {
  switch (error.code) {
    case "storage_unavailable":
      return "Private metadata storage is unavailable for this vault. On Windows this is not supported yet; on macOS, check that the folder is private to your user.";
    case "vault_not_found":
      return "No Page vault was found there. It may have been moved or deleted; nothing was created.";
    case "vault_exists":
      return "A Page vault already exists in this folder. Use Open Vault instead; the existing vault was not changed.";
    case "vault_identity_conflict":
      return "Another open vault already has this vault's identity (for example, a copied vault). Close the other vault first.";
    case "invalid_vault":
      return "The vault manifest is invalid or unsupported. It was not changed.";
    case "unreadable_note":
      return "This note is not valid UTF-8, so Page cannot open it. Other notes still work.";
    case "note_exists":
      return "A file already exists at that path. Choose another path; nothing was overwritten.";
    case "validation_error":
      return "That path or value is not valid. Note paths are relative, use / between folders and end in lowercase .md.";
    case "backend_unavailable":
    case "backend_unreachable":
      return "Page Core is not running. Restart it to continue.";
    default:
      return error.message;
  }
}

export function ErrorText({ error, prefix }: { error: DesktopError; prefix?: string }) {
  return (
    <span className="break-words">
      {prefix ? `${prefix} ` : ""}
      {explain(error)} <span className="text-xs opacity-70">({error.code})</span>
    </span>
  );
}
