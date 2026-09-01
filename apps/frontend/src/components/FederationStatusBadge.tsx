import { CheckCircle2, CircleDashed, CircleHelp, OctagonAlert } from "lucide-react";
import { federationStatusTone } from "../lib/federation";
import { titleCase } from "../lib/format";

export function FederationStatusBadge({ value }: { value?: string | null }) {
  const tone = federationStatusTone(value);
  const Icon = tone === "reachable"
    ? CheckCircle2
    : tone === "attention"
      ? OctagonAlert
      : tone === "pending"
        ? CircleDashed
        : CircleHelp;
  return (
    <span className={`federation-status federation-status--${tone}`}>
      <Icon aria-hidden="true" size={14} />
      <span>{titleCase(value ?? "unverified")}</span>
    </span>
  );
}
