from django.http import JsonResponse
from tethys_sdk.routing import controller

from ..mrms_tiles import get_mrms_meta, value_at_latlon


@controller(
    name="mrms_value_at",
    url="/mrms/value_at/{gage_id}",
    login_required=False,
)
def mrms_value_at(request, gage_id):
    meta = get_mrms_meta(gage_id)
    nt = int(meta["nt"])

    try:
        t = int(request.GET.get("t", 0))
        lon = float(request.GET["lon"])
        lat = float(request.GET["lat"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error": "Required query params: t, lon, lat."},
            status=400,
        )

    t = min(max(t, 0), nt - 1)
    value = value_at_latlon(time_index=t, lon=lon, lat=lat, gage_id=gage_id)

    return JsonResponse(
        {
            "ok": True,
            "t": t,
            "lon": lon,
            "lat": lat,
            "value_mmph": value,
        }
    )
