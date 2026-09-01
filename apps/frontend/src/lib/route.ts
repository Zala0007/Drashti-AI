export interface CameraRoutePoint {
  cameraId: string;
  latitude: number;
  longitude: number;
  sequence: number;
  label?: string;
  observedAt?: string;
}

export const routeLatLngs = (points: CameraRoutePoint[]): Array<[number, number]> =>
  [...points]
    .filter((point) => Number.isFinite(point.latitude) && Number.isFinite(point.longitude))
    .sort((left, right) => left.sequence - right.sequence)
    .map((point) => [point.latitude, point.longitude]);
