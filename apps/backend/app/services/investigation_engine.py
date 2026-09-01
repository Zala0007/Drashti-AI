from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from app.models import Camera, CameraGraphEdge

CONFUSION_GROUPS = ({"0", "O", "Q", "D"}, {"1", "I", "L"}, {"2", "Z"}, {"5", "S"}, {"8", "B"})


def _substitution_cost(left: str, right: str) -> float:
    if left == right:
        return 0.0
    if any(left in group and right in group for group in CONFUSION_GROUPS):
        return 0.25
    return 1.0


def plate_similarity(target: str, observed: str) -> float:
    """Confusion-aware normalized edit similarity; never turns a weak OCR into certainty."""
    if not target or not observed:
        return 0.0
    previous = [float(index) for index in range(len(observed) + 1)]
    for row, left in enumerate(target, start=1):
        current = [float(row)]
        for column, right in enumerate(observed, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + _substitution_cost(left, right),
                )
            )
        previous = current
    return round(max(0.0, 1 - previous[-1] / max(len(target), len(observed))), 4)


def haversine_m(left: Camera, right: Camera) -> float:
    radius = 6_371_008.8
    phi_1, phi_2 = math.radians(left.latitude), math.radians(right.latitude)
    delta_phi = math.radians(right.latitude - left.latitude)
    delta_lambda = math.radians(right.longitude - left.longitude)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def bearing_degrees(left: Camera, right: Camera) -> float:
    phi_1, phi_2 = math.radians(left.latitude), math.radians(right.latitude)
    delta_lambda = math.radians(right.longitude - left.longitude)
    y = math.sin(delta_lambda) * math.cos(phi_2)
    x = math.cos(phi_1) * math.sin(phi_2) - math.sin(phi_1) * math.cos(phi_2) * math.cos(
        delta_lambda
    )
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass_direction(bearing: float | None) -> str | None:
    if bearing is None:
        return None
    labels = (
        "north",
        "north-east",
        "east",
        "south-east",
        "south",
        "south-west",
        "west",
        "north-west",
    )
    return labels[round(bearing / 45) % 8]


def angular_compatibility(expected: float | None, actual: float) -> float:
    if expected is None:
        return 0.6
    delta = abs((actual - expected + 180) % 360 - 180)
    return max(0.0, 1 - delta / 180)


@dataclass(slots=True)
class RankedCamera:
    camera: Camera
    distance_m: float
    travel_seconds: int
    score: float
    tier: int
    confidence: str
    reasons: list[str]
    graph_method: str


class CameraGraphService:
    """Ranks graph neighbors and exposes an honest geospatial fallback.

    Verified edges always win. When no verified edge leaves the anchor, the
    fallback ranks nearby operational cameras by distance, movement bearing,
    camera health and ANPR readiness. It does not claim road connectivity.
    """

    def rank_next_cameras(
        self,
        *,
        anchor: Camera,
        previous: Camera | None,
        cameras: list[Camera],
        edges: list[CameraGraphEdge],
        max_candidates: int = 12,
    ) -> list[RankedCamera]:
        expected_bearing = bearing_degrees(previous, anchor) if previous else anchor.bearing_degrees
        by_id = {camera.id: camera for camera in cameras}
        verified = [edge for edge in edges if edge.source_camera_id == anchor.id and edge.enabled]
        ranked: list[RankedCamera] = []
        if verified:
            for edge in verified:
                camera = by_id.get(edge.destination_camera_id)
                if not camera or camera.status != "active" or camera.health == "offline":
                    continue
                direction_score = angular_compatibility(
                    expected_bearing, bearing_degrees(anchor, camera)
                )
                score = (
                    0.55 * edge.confidence + 0.25 * direction_score + 0.20 * self._readiness(camera)
                )
                ranked.append(
                    RankedCamera(
                        camera=camera,
                        distance_m=edge.road_distance_m,
                        travel_seconds=edge.estimated_travel_seconds,
                        score=score,
                        tier=1,
                        confidence=self._confidence(score),
                        reasons=[
                            f"verified topology edge ({edge.topology_source})",
                            "movement direction compatible"
                            if direction_score >= 0.55
                            else "direction carries uncertainty",
                            "camera operational",
                        ],
                        graph_method="verified_camera_topology",
                    )
                )
        else:
            for camera in cameras:
                if (
                    camera.id == anchor.id
                    or camera.status != "active"
                    or camera.health == "offline"
                ):
                    continue
                distance = haversine_m(anchor, camera)
                if distance > 75_000:
                    continue
                direction_score = angular_compatibility(
                    expected_bearing, bearing_degrees(anchor, camera)
                )
                distance_score = math.exp(-distance / 18_000)
                readiness = self._readiness(camera)
                score = 0.45 * direction_score + 0.35 * distance_score + 0.20 * readiness
                reasons = [
                    "directionally compatible with the current trajectory"
                    if direction_score >= 0.6
                    else "retained as a bounded fallback direction",
                    "within the local surveillance cone",
                    "camera operational",
                ]
                if any(str(item).lower() == "anpr" for item in camera.ai_capabilities):
                    reasons.append("ANPR capability registered")
                ranked.append(
                    RankedCamera(
                        camera=camera,
                        distance_m=distance,
                        travel_seconds=max(30, round(distance / 9.72)),
                        score=score,
                        tier=1,
                        confidence=self._confidence(score),
                        reasons=reasons,
                        graph_method="geospatial_directional_fallback",
                    )
                )
        ranked.sort(key=lambda item: (-item.score, item.travel_seconds, item.camera.camera_code))
        selected = ranked[:max_candidates]
        for index, item in enumerate(selected):
            item.tier = 1 if index < 3 else 2 if index < 7 else 3
        return selected

    @staticmethod
    def _readiness(camera: Camera) -> float:
        health = {"online": 1.0, "degraded": 0.55, "unknown": 0.35}.get(camera.health, 0.0)
        anpr = 1.0 if any(str(item).lower() == "anpr" for item in camera.ai_capabilities) else 0.4
        return 0.65 * health + 0.35 * anpr

    @staticmethod
    def _confidence(score: float) -> str:
        return "high" if score >= 0.72 else "medium" if score >= 0.48 else "low"


def temporal_feasibility(
    previous_camera: Camera | None,
    current_camera: Camera,
    previous_time: datetime | None,
    current_time: datetime,
) -> tuple[float, str]:
    if previous_camera is None or previous_time is None:
        return 1.0, "first correlated observation"
    previous_time = (
        previous_time.replace(tzinfo=UTC)
        if previous_time.tzinfo is None
        else previous_time.astimezone(UTC)
    )
    current_time = (
        current_time.replace(tzinfo=UTC)
        if current_time.tzinfo is None
        else current_time.astimezone(UTC)
    )
    seconds = max(0.0, (current_time - previous_time).total_seconds())
    distance = haversine_m(previous_camera, current_camera)
    if seconds <= 0:
        return (
            (1.0, "same-camera multi-frame observation")
            if distance < 100
            else (0.0, "non-forward timestamp")
        )
    required_kph = distance / seconds * 3.6
    if required_kph > 160:
        return 0.0, f"physically implausible travel speed ({required_kph:.0f} km/h)"
    if required_kph > 110:
        return 0.35, f"travel time is weakly feasible ({required_kph:.0f} km/h implied)"
    return 1.0 if required_kph <= 80 else 0.72, "elapsed time is compatible with camera separation"


def correlation_score(
    *,
    plate: float,
    ocr_confidence: float,
    temporal: float,
    route: float,
    vehicle_similarity: float | None,
) -> float:
    # Conservative, documented baseline. Appearance contributes only when supplied.
    appearance = vehicle_similarity if vehicle_similarity is not None else 0.5
    score = (
        0.50 * plate + 0.15 * ocr_confidence + 0.15 * temporal + 0.10 * route + 0.10 * appearance
    )
    return round(max(0.0, min(1.0, score)), 4)
