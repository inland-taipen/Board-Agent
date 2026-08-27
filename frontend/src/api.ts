/**
 * API client.
 *
 * The session token lives in sessionStorage rather than localStorage: a
 * director's briefing session should not survive the browser being closed on a
 * shared or borrowed machine.
 */

const TOKEN_KEY = "boardlens.token";
const USER_KEY = "boardlens.user";

export type Role = "admin" | "secretary" | "director";

export interface SessionUser {
  email: string;
  role: Role;
  display_name: string;
}

export interface Board {
  id: string;
  name: string;
  created_at: string;
}

export interface PackDocument {
  id: string;
  filename: string;
  doc_kind: string;
  pages: number;
  chunk_count: number;
  size_bytes: number;
  ocr_pages: number[];
}

export interface Pack {
  id: string;
  client_id: string;
  meeting_label: string;
  meeting_date: string;
  classification: string;
  status: "draft" | "processing" | "ready" | "failed";
  progress: string;
  error: string;
  created_at: string;
  document_count?: number;
  briefing_id: string | null;
  documents?: PackDocument[];
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  document: string;
  document_kind: string;
  page: number;
  locator: string;
  citation: string;
  excerpt: string;
}

export interface VerificationIssue {
  section: string;
  item_index: number;
  item_label: string;
  kind: "invalid" | "uncited";
  detail: string;
}

export interface Verification {
  total_items: number;
  grounded_items: number;
  total_citations: number;
  resolved_citations: number;
  grounding_rate: number;
  citation_validity: number;
  passed: boolean;
  issues: VerificationIssue[];
  citation_map: Record<string, Citation>;
}

export interface BriefingContent {
  meeting_context: string;
  critical_risks: Array<{
    title: string;
    severity: string;
    why_now: string;
    exposure: string;
    management_position: string;
    gap: string;
    evidence: string[];
  }>;
  unresolved_actions: Array<{
    action: string;
    owner: string;
    raised_at: string;
    committed_date: string;
    status: string;
    status_basis: string;
    ageing_cycles: number;
    evidence: string[];
  }>;
  performance_changes: Array<{
    metric: string;
    movement: string;
    direction: string;
    materiality: string;
    explanation_given: string;
    evidence: string[];
  }>;
  management_questions: Array<{
    question: string;
    rationale: string;
    directed_to: string;
    priority: string;
    evidence: string[];
  }>;
  decisions_required: Array<{
    decision: string;
    proposed_by: string;
    financial_impact: string;
    approval_basis: string;
    readiness: string;
    considerations: string;
    evidence: string[];
  }>;
  coverage_note: string;
}

export interface Briefing {
  id: string;
  pack_id: string;
  company: string;
  meeting_label: string;
  meeting_date: string;
  classification: string;
  model: string;
  created_at: string;
  content: BriefingContent;
  verification: Verification;
}

export interface Member {
  id: string;
  email: string;
  role: Role;
  display_name: string;
  created_at: string;
}

export interface ActionItem {
  id: string;
  action: string;
  owner: string;
  raised_at: string;
  committed_date: string;
  status: string;
  status_basis: string;
  ageing_cycles: number;
  evidence: string[];
}

export interface UploadResult {
  accepted: Array<{
    id: string;
    filename: string;
    doc_kind: string;
    pages: number;
    segments: number;
    unreadable_pages: number[];
  }>;
  rejected: Array<{ filename: string; reason: string }>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export const session = {
  token: () => sessionStorage.getItem(TOKEN_KEY),
  user: (): SessionUser | null => {
    const raw = sessionStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as SessionUser) : null;
  },
  set(token: string, user: SessionUser) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  },
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = session.token();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`/api${path}`, { ...init, headers });

  // A 401 means "expired session" only if we actually presented a token. On the
  // sign-in call there is no token, so a 401 is a rejected credential and must
  // surface as a message - reloading there would wipe the form and leave the
  // user staring at the sign-in screen with no idea why.
  if (response.status === 401 && token) {
    session.clear();
    // A hard reload is the simplest correct response: every cached view in
    // memory belongs to a session that no longer exists.
    window.location.reload();
    throw new ApiError("Your session has expired.", 401);
  }

  if (!response.ok) {
    throw new ApiError(await describeError(response), response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function describeError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
    return JSON.stringify(detail ?? body);
  } catch {
    return `Request failed (${response.status})`;
  }
}

export const api = {
  async login(email: string, password: string) {
    const result = await request<{
      token: string;
      email: string;
      role: Role;
      display_name: string;
    }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    session.set(result.token, {
      email: result.email,
      role: result.role,
      display_name: result.display_name,
    });
    return result;
  },

  boards: () => request<Board[]>("/clients"),

  createBoard: (name: string) =>
    request<{ id: string; name: string }>("/clients", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  packs: (clientId: string) => request<Pack[]>(`/clients/${clientId}/packs`),

  members: (clientId: string) => request<Member[]>(`/clients/${clientId}/members`),

  addMember: (
    clientId: string,
    payload: { email: string; role: Role; display_name: string; password: string },
  ) =>
    request<{ user_id: string; email: string; role: Role }>(`/clients/${clientId}/members`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  removeMember: (clientId: string, userId: string) =>
    request<void>(`/clients/${clientId}/members/${userId}`, { method: "DELETE" }),

  pack: (packId: string) => request<Pack>(`/packs/${packId}`),

  createPack: (
    clientId: string,
    payload: { meeting_label: string; meeting_date: string; classification: string },
  ) =>
    request<{ id: string }>(`/clients/${clientId}/packs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  uploadDocuments: (packId: string, files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<UploadResult>(`/packs/${packId}/documents`, {
      method: "POST",
      body: form,
    });
  },

  reclassifyDocument: (documentId: string, docKind: string) =>
    request<{ id: string; doc_kind: string }>(`/documents/${documentId}`, {
      method: "PATCH",
      body: JSON.stringify({ doc_kind: docKind }),
    }),

  deleteDocument: (documentId: string) =>
    request<void>(`/documents/${documentId}`, { method: "DELETE" }),

  startBriefing: (packId: string) =>
    request<{ status: string }>(`/packs/${packId}/briefing`, { method: "POST" }),

  briefing: (briefingId: string) => request<Briefing>(`/briefings/${briefingId}`),

  sourcePassage: (packId: string, chunkId: string) =>
    request<Citation & { text: string; heading: string | null }>(
      `/packs/${packId}/source/${chunkId}`,
    ),

  actions: (clientId: string) => request<ActionItem[]>(`/clients/${clientId}/actions`),

  updateAction: (clientId: string, actionId: string, status: string, basis: string) =>
    request<{ id: string; status: string }>(`/clients/${clientId}/actions/${actionId}`, {
      method: "PATCH",
      body: JSON.stringify({ status, status_basis: basis }),
    }),

  /**
   * Exports need the Authorization header, so they cannot be a plain link -
   * fetch the bytes and hand the browser a blob.
   */
  async downloadExport(briefingId: string, format: "pdf" | "docx", filename: string) {
    const response = await fetch(`/api/briefings/${briefingId}/export?format=${format}`, {
      headers: { Authorization: `Bearer ${session.token()}` },
    });
    if (!response.ok) throw new ApiError(await describeError(response), response.status);

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
};

export const DOC_KINDS: Array<{ value: string; label: string }> = [
  { value: "prior_minutes", label: "Prior minutes" },
  { value: "board_deck", label: "Board deck" },
  { value: "financial_pack", label: "Financial pack / MIS" },
  { value: "risk_report", label: "Risk report" },
  { value: "internal_audit", label: "Internal audit" },
  { value: "business_update", label: "Business update" },
  { value: "other", label: "Other" },
];

export const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  completed: "Completed",
  superseded: "Superseded",
  unclear: "Not addressed in this pack",
};
