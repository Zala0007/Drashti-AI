export interface WatchlistEntry {
  id: string;
  plate_text: string;
  normalized_plate: string;
  subject_label: string;
  reason: string;
  severity: "critical" | "high" | "standard";
  status: "active" | "inactive";
  valid_from: string;
  valid_until: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WatchlistEntryList {
  items: WatchlistEntry[];
  total: number;
}

export interface WatchlistAlert {
  id: string;
  status: "new" | "acknowledged" | "resolved" | "false_positive";
  match_score: number;
  matched_plate: string;
  observed_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  created_at: string;
  entry: WatchlistEntry;
  anpr_event_id: string;
  camera_id: string;
  camera_code: string;
  camera_name: string;
  district: string;
  evidence_reference: string | null;
  ocr_confidence: number;
}

export interface WatchlistAlertList {
  items: WatchlistAlert[];
  total: number;
  unacknowledged: number;
}

export interface WatchlistDashboard {
  active_entries: number;
  total_entries: number;
  new_alerts: number;
  latest_alert_at: string | null;
}
