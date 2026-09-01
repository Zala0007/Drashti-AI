from __future__ import annotations

from app.models import Camera
from app.schemas.advanced import AdvancedCameraRead


def camera_read(camera: Camera) -> AdvancedCameraRead:
    return AdvancedCameraRead(
        id=camera.id,
        camera_code=camera.camera_code,
        camera_name=camera.camera_name,
        district=camera.district,
        city=camera.city,
        latitude=camera.latitude,
        longitude=camera.longitude,
        health=camera.health,
        status=camera.status,
        vendor=camera.vendor,
        vms=camera.vms,
        coverage_radius_m=camera.coverage_radius_m,
        bearing_degrees=camera.bearing_degrees,
        field_of_view_degrees=camera.field_of_view_degrees,
    )
