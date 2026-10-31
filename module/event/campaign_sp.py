import os

import numpy as np

from module.base.utils import crop
from module.config.config import TaskEnd
from module.event.base import EventBase
from module.logger import logger
from module.ocr.ocr import DigitCounter


class StageRemainCounter(DigitCounter):
    def pre_process(self, image):
        # `0/1` is red when used up and white otherwise, both have R=255 while the map behind is blue-ish
        return 255 - image[:, :, 0]


class CampaignSP(EventBase):
    def is_stage_remain_exhausted(self):
        """
        Event SP can be cleared once a day, the stage page shows `残り回数：0/1` above-right of the entrance.
        Its x depends on the length of the stage name, so anchor on the rightmost text above the entrance.

        Returns:
            bool: If no remaining times today
        """
        entrance = getattr(self.campaign, 'ENTRANCE', None)
        if entrance is None:
            return False
        x1, y1, _, _ = entrance.button
        band = (x1, y1 - 48, x1 + 340, y1 - 18)
        image = crop(self.device.image, band, copy=False)
        cols = np.where(np.sum(image[:, :, 0] > 200, axis=0) >= 3)[0]
        if not len(cols):
            logger.info('Stage remain counter not found')
            return False
        right = band[0] + int(cols.max())
        ocr = StageRemainCounter((right - 34, band[1], right + 4, band[3]), name='SP_REMAIN')
        current, _, total = ocr.ocr(self.device.image)
        # Unreadable counter, enter as before
        return total > 0 and current == 0

    def run(self, *args, **kwargs):
        if not os.path.exists(f'./campaign/{self.config.Campaign_Event}/sp.py'):
            logger.info(f'./campaign/{self.config.Campaign_Event}/sp.py not exists')
            logger.info(f'This event do not have SP, skip')
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        try:
            super().run(name=self.config.Campaign_Name, folder=self.config.Campaign_Event, total=1)
        except TaskEnd:
            # Catch task switch
            pass
        if self.run_count > 0:
            self.config.task_delay(server_update=True)
        else:
            self.config.task_stop()
