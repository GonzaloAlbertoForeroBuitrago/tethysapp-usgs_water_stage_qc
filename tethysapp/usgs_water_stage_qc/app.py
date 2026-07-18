from tethys_sdk.base import TethysAppBase


class App(TethysAppBase):
    """
    Tethys app class for USGS-MRMS Flood Explorer.
    """
    name = 'USGS-Water Stage QC (8616 US basins)'
    description = 'Interactive visualization and quality-control tools'
    package = 'usgs_water_stage_qc'  # WARNING: Do not change this value
    index = 'home'
    icon = f'{package}/images/icon.gif'
    root_url = 'usgs-water-stage-qc'
    color = '#c23616'
    tags = ''
    enable_feedback = False
    feedback_emails = []
