export type SpatialFeature = "border_line" | "virtual_fence" | "night_movement" | "object_path";
export interface SpatialPoint { x: number; y: number }
export interface SpatialRule {
  feature: SpatialFeature;
  enabled: boolean;
  points: SpatialPoint[];
  direction: "both" | "A_TO_B" | "B_TO_A";
}
export interface SpatialStatus {
  rules: SpatialRule[];
  events: { id: number; event: string; observed_at: string; track_id: number | null; direction?: string }[];
  live: null | {
    observed_at: string;
    paths: { track_id: number; class_name: string; points: number[][] }[];
    motion_boxes: number[][];
    counts: Record<string, number>;
    inside: number;
    warming_up: boolean;
  };
}
