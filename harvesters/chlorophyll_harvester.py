"""
NASA ERDDAP Chlorophyll-a WMS Sync
Validates the WMS endpoint is responding and logs a sync entry.
Chlorophyll data is served as on-demand WMS tiles (no local storage).
This harvester confirms the upstream service is available.
"""

import urllib.request
import urllib.error
from harvesters.base import BaseHarvester


class ChlorophyllHarvester(BaseHarvester):

    WMS_URL = (
        'https://coastwatch.pfeg.noaa.gov/erddap/wms/erdMH1chla1day/request'
        '?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities'
    )
    TIMEOUT = 30  # seconds

    def __init__(self):
        super().__init__('nasa_erddap_chlorophyll')

    def sync(self, **kwargs):
        self.logger.info('Checking NASA ERDDAP Chlorophyll-a WMS availability')

        try:
            req = urllib.request.Request(self.WMS_URL, headers={
                'User-Agent': 'MarineFishing/1.0'
            })
            resp = urllib.request.urlopen(req, timeout=self.TIMEOUT)
            status = resp.getcode()
            content_length = len(resp.read())
            resp.close()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            self.logger.error(f'ERDDAP WMS unreachable: {e}')
            return {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        if status == 200 and content_length > 0:
            self.logger.info(
                f'ERDDAP WMS responding OK (HTTP {status}, '
                f'{content_length:,} bytes GetCapabilities)'
            )
        else:
            self.logger.warning(f'ERDDAP WMS returned HTTP {status}')

        return {'processed': 1, 'inserted': 0, 'updated': 0, 'skipped': 0}


if __name__ == '__main__':
    harvester = ChlorophyllHarvester()
    harvester.run(sync_type='wms')
