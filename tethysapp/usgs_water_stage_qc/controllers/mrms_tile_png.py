from django.http import HttpResponse, HttpResponseBadRequest
from tethys_sdk.routing import controller

from ..mrms_tiles import render_tile_png


@controller(
    name="mrms_tile_png",
    url="mrms/tiles/{gage_id}/{t}/{z}/{x}/{y}",
    login_required=False,
)
def mrms_tile_png(request, gage_id, t, z, x, y):
    try:
        time_index = int(t)
        zoom = int(z)
        tile_x = int(x)
        tile_y = int(y)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("t, z, x, and y must be integers.")

    png_bytes = render_tile_png(gage_id=gage_id, time_index=time_index, z=zoom, x=tile_x, y=tile_y)

    response = HttpResponse(png_bytes, content_type="image/png")
    response["Cache-Control"] = "public, max-age=3600"
    return response