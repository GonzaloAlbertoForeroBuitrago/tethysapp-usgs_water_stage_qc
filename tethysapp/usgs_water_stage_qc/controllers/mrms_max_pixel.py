from django.http import JsonResponse
from tethys_sdk.routing import controller

from ..mrms_tiles import get_mrms_meta, max_pixel_at_time


@controller(
    name="mrms_max_pixel",
    url="/mrms/max_pixel/{gage_id}",
    login_required=False,
)
def mrms_max_pixel(request, gage_id):
    meta = get_mrms_meta(gage_id)
    nt = int(meta["nt"])

    try:
        t = int(request.GET.get("t", 0))
    except (TypeError, ValueError):
        t = 0

    t = min(max(t, 0), nt - 1)
    lon, lat, value = max_pixel_at_time(gage_id=gage_id, time_index=t)

    return JsonResponse(
        {
            "ok": True,
            "t": t,
            "lon": lon,
            "lat": lat,
            "value_mmph": value,
        }
    )
