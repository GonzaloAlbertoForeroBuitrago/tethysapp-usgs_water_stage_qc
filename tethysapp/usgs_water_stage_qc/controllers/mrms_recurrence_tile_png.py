from django.http import HttpResponse, HttpResponseBadRequest
from tethys_sdk.routing import controller

from ..mrms_tiles import render_recurrence_tile_png


@controller(
    name="mrms_recurrence_tile_png",
    url="/mrms/recurrence/tiles/{gage_id}/{z}/{x}/{y}",
    login_required=False,
)
def mrms_recurrence_tile_png(request, gage_id, z, x, y):
    try:
        zoom = int(z)
        tile_x = int(x)
        tile_y = int(y)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("z, x, and y must be integers.")

    png_bytes = render_recurrence_tile_png(z=zoom, x=tile_x, y=tile_y, gage_id=gage_id)

    response = HttpResponse(png_bytes, content_type="image/png")
    response["Cache-Control"] = "public, max-age=3600"
    return response