export const INTENT_META: Record<string, { label: string; family: string; icon: string }> = {
  contract_status: { label: "Contract Status", family: "contract", icon: "📝" },
  implementation_eta: { label: "Implementation ETA", family: "product", icon: "🚀" },
  open_tickets: { label: "Support Tickets", family: "support", icon: "🎫" },
  security_review: { label: "Security & Compliance", family: "security", icon: "🔒" },
  proposal_request: { label: "Proposal Request", family: "product", icon: "📄" },
  pricing: { label: "Pricing", family: "pricing", icon: "💰" },
  renewal: { label: "Renewal", family: "renewal", icon: "🔁" },
  product_capability: { label: "Product Capability", family: "product", icon: "🧩" },
  general: { label: "General", family: "general", icon: "💬" },
};

export function intentMeta(type: string) {
  return INTENT_META[type] ?? { label: type, family: "general", icon: "💬" };
}

export function confidenceColor(c: number): string {
  if (c >= 0.8) return "var(--green)";
  if (c >= 0.6) return "var(--amber)";
  return "var(--red)";
}

export const ACTION_ICON: Record<string, string> = {
  share_document: "📎",
  create_task: "✅",
  start_workflow: "⚙️",
  schedule_followup: "📅",
  send_email: "✉️",
  escalate: "🚨",
};
