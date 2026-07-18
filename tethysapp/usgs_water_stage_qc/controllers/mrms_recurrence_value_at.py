from django.http import JsonResponse
from tethys_sdk.routing import controller

from ..mrms_tiles import recurrence_at_latlon


@controller(
    name="mrms_recurrence_value_at",
    url="/mrms/recurrence/value_at/{gage_id}",
    login_required=False,
)
def mrms_recurrence_value_at(request, gage_id):
    try:
        lon = float(request.GET["lon"])
        lat = float(request.GET["lat"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error": "Required query params: lon, lat."},
            status=400,
        )

    count = recurrence_at_latlon(lon=lon, lat=lat, gage_id=gage_id)

    return JsonResponse(
        {
            "ok": True,
            "lon": lon,
            "lat": lat,
            "count": count,
        }
    )