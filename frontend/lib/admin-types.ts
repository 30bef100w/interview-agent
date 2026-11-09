export type AdminPage<T> = { items: T[]; total: number; limit: number; offset: number };
export type AdminSession = {
  id: number; user_id: number; username: string; status: string; mode: string; type: string;
  target_role: string; target_company: string; started_at: string; finished_at: string | null;
  question_count: number; answer_count: number; rounds_used: number; billing_source: string;
  quota_state: string; llm_calls: number; cost_yuan: number;
};
export type AdminUsage = {
  id: number; user_id: number; session_id: number | null; provider: string; model: string;
  input_tokens: number; output_tokens: number; cost_yuan: number; created_at: string;
};

export type AnalyticsMetric = {
  key: string; label: string; unit: "count" | "ratio" | "yuan"; better: "up" | "down";
  current: number | null; previous: number | null; definition: string;
  change: { kind: "pp" | "percent" | "unchanged" | "new" | "unavailable"; value: number | null };
};
export type AnalyticsDay = {
  date: string; new_users: number; created_sessions: number; answer_users: number;
  answered_sessions: number; platform_cost_yuan: number;
};
export type AdminAnalytics = {
  period: { start_date: string; end_date: string; days: number; previous_start_date: string;
    previous_end_date: string; start_time: string; end_time: string };
  timezone: string; as_of: string; observation_hours: number;
  metrics: AnalyticsMetric[]; trend: AnalyticsDay[]; previous_trend: AnalyticsDay[];
  funnel: { key: string; label: string; count: number; conversion: number | null; lost: number }[];
  quality: { created: number; mature: number; pending: number; completed: number;
    report_success: number; report_fallback: number; report_unknown: number; cost_recorded_sessions: number };
  types: { type: string; mode: string; created: number; mature: number; answered: number;
    completed: number; abandoned: number; failed: number; previous_created: number;
    delta: number; completion_rate: number | null; abandon_rate: number | null }[];
  cost: { total_yuan: number; unassigned_yuan: number; models: { provider: string; model: string;
    records: number; input_tokens: number; output_tokens: number; cost_yuan: number; share: number | null }[] };
  retention: { day: number; eligible: number; retained: number; pending: number; rate: number | null }[];
  insights: { tone: string; text: string }[];
};
