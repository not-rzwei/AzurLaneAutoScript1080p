import module.config.server as server

from module.base.base import ModuleBase
from module.base.button import *
from module.base.decorator import Config
from module.logger import logger
from module.ocr.ocr import Digit

COLOR_WHITE = (255, 255, 255)
COLOR_MASKED = (107, 105, 107)


class Level(ModuleBase):
    _lv = [-1, -1, -1, -1, -1, -1]
    _lv_before_battle = [-1, -1, -1, -1, -1, -1]

    @property
    def lv(self):
        """
        Returns:
            list[int]:
        """
        return self._lv

    @lv.setter
    def lv(self, value):
        """
        Args:
            value (list[int]):
        """
        self._lv = value

    def lv_reset(self):
        """
        Call this method after enter map.
        """
        self._lv = [-1] * 6
        self._lv_before_battle = [-1] * 6

    @Config.when(SERVER='en')
    def _lv_grid(self):
        return ButtonGrid(origin=(56, 113), delta=(0, 100), button_shape=(46, 19), grid_shape=(1, 6))

    @Config.when(SERVER='jp')
    def _lv_grid(self):
        # 3px higher than the 'LV.' area (digits are taller, LevelOcrMap.TOP) and wide enough to include
        # the card's right border (x=105), LevelOcrMap cuts both off.
        return ButtonGrid(origin=(34, 125), delta=(0, 100), button_shape=(74, 22), grid_shape=(1, 6))

    @Config.when(SERVER=None)
    def _lv_grid(self):
        return ButtonGrid(origin=(58, 128), delta=(0, 100), button_shape=(46, 19), grid_shape=(1, 6))

    def lv_get(self, after_battle=False):
        """
        Args:
            after_battle (bool): True if called after battle else False.

        Returns:
            list[int]:
        """
        if not self.config.StopCondition_ReachLevel and not self.config.STOP_IF_REACH_LV32:
            return [-1] * 6

        self._lv_before_battle = self.lv if after_battle else [-1] * 6

        ocr = LevelOcrMap(self._lv_grid().buttons, name='LevelOcr')
        self.lv = ocr.ocr(self.device.image)
        logger.attr('LEVEL', ', '.join(str(data) for data in self.lv))

        if after_battle:
            self.lv_triggered()
            self.lv32_triggered()

        return self.lv

    def lv_triggered(self):
        limit_config = self.config.StopCondition_ReachLevel
        limits = []

        if not limit_config:
            return False

        if isinstance(limit_config, (int, float)):
            limits.append(limit_config)
        else:
            for limit in limit_config.split(','):
                try:
                    limits.append(int(limit))
                except (ValueError, TypeError):
                    logger.warning('Limit configuration not correct, please check')
                    pass

        logger.info(f'Level limits: {limits}')

        if len(limits) == 0:
            return False

        for i in range(6):
            before, after = self._lv_before_battle[i], self.lv[i]
            for limit in limits:
                if after > before > 0:
                    logger.info(f'Position {i} LV.{before} -> LV.{after}')
                if after >= limit > before > 0:
                    if after - before == 1 or after < 35:
                        logger.info(f'Position {i} LV.{limit} Reached')
                        self.config.LV_TRIGGERED = True
                        return True
                    else:
                        logger.warning(f'Level gap between {before} and {after} is too large. '
                                       f'This will not be considered as a trigger')

        return False

    def lv32_triggered(self):
        if not self.config.STOP_IF_REACH_LV32:
            return False

        if self.lv[0] >= 32:
            logger.info(f'Position 0 LV.32 Reached')
            self.config.LV32_TRIGGERED = True
            return True

        return False


class LevelOcr(Digit):
    @staticmethod
    def _grey(image, top=0):
        """
        Args:
            image (np.ndarray):
            top (int): Rows above the area the mask check is tuned on

        Returns:
            np.ndarray: Greyscale image, letters black on white
        """
        # Check the max value of red channel to find out whether the image is masked.
        # It would be no larger than COLOR_MASKED[0]=107 iff masked.
        # Crop before checking to cut off the "need repair" icon while preserving upper part of char 'V'.
        max_red = image[top:top + 8, :, 0].max()
        if max_red <= COLOR_MASKED[0]:
            # The mask on low hp ships turns COLOR_WHITE=(255, 255, 255) to COLOR_MASKED=(107, 105, 107),
            # so multiply all channels by a scalar can turn them back.
            scalar = np.mean(COLOR_WHITE) / np.mean(COLOR_MASKED)
            image = cv2.addWeighted(image, scalar, image, 0, 0)

        # Deal with the blue background of chars before converting to greyscale.
        # The background is semi-transparent. It turns (0, 0, 0) to (33, 65, 115), and (255, 255, 255)
        # to (107, 138, 189). We use the middle point (70, 102, 152).
        bg = (70, 102, 152)
        # BT.601
        luma_trans = (0.299, 0.587, 0.114)
        luma_bg = np.dot(bg, luma_trans)
        image = cv2.subtract(image, (*bg, 0)).dot(luma_trans).round().astype(np.uint8)
        image = cv2.subtract(255, cv2.multiply(image, 255 / (255 - luma_bg)))
        return image

    def pre_process(self, image):
        image = self._grey(image)
        # Find 'L' to strip 'LV.'.
        # Return an empty image if 'L' is not found.
        if server.server != 'jp':
            letter_l = np.nonzero(image[9:15, :].max(axis=0) < 127)[0]
            if len(letter_l):
                first_digit = letter_l[0] + 17
                if first_digit + 3 < 46:  # LV_GRID_MAIN.button_shape[0] = 46
                    return image[:, first_digit:]
        else:
            letter_l = np.nonzero(image[5:11, :].max(axis=0) < 63)[0]
            if len(letter_l):
                first_digit = letter_l[0] + 23  # maximal size in dock and minimal size in sea grid
                if first_digit + 3 < 70:  # LV_GRID_MAIN.button_shape[0] = 46
                    image = image[:, first_digit:]
                    image = cv2.copyMakeBorder(image, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))
                    return image
        return np.array([[255]], dtype=np.uint8)

    def after_process(self, result):
        result = result.replace('I', '1').replace('D', '0').replace('S', '5')
        result = result.replace('B', '8')

        # No correction log, cause levels are usually empty
        # Like: [23, 0, 0, 100, 0, 0]
        result = int(result) if result else 0

        return result


class LevelOcrMap(LevelOcr):
    """
    Level OCR of the fleet cards on the left of the sea map.

    On JP, the image LevelOcr feeds the model had three problems:
    - The digits are 2px taller than 'LV.' and start above the area, the top arc of 0 got cut,
      leaving two bars the model read as nothing: 109 -> 19.
    - The dot of 'LV.' stays in front of the digits: 121 -> 21, 12.
    - Once the area is wide enough for the last digit, the card's right border follows it: 113 -> 1131.
    So the JP grid starts TOP rows higher, 'L' is located on the rows LevelOcr uses,
    and the dot and the border are cut off.
    """
    # Extra rows above the area LevelOcr was tuned on
    TOP = 3

    def pre_process(self, image):
        if server.server != 'jp':
            return super().pre_process(image)
        grey = self._grey(image, top=self.TOP)
        base = grey[self.TOP:]
        # Find 'L' to strip 'LV.', same as LevelOcr
        letter_l = np.nonzero(base[5:11, :].max(axis=0) < 63)[0]
        if not len(letter_l):
            return np.array([[255]], dtype=np.uint8)
        first_digit = letter_l[0] + 23
        if first_digit + 3 >= grey.shape[1]:
            return np.array([[255]], dtype=np.uint8)
        image = grey[:, first_digit:]
        h = image.shape[0]
        # Card border is a vertical line longer than the digits, it still has ink below the digit baseline.
        # Require a line, other things below the digits (like a flashing icon) must not cut digits off.
        ink = image < 170
        border = np.nonzero((ink[h - 4:].sum(axis=0) >= 3) & (ink[self.TOP:h - 4].sum(axis=0) >= 10))[0]
        if len(border):
            image = image[:, :border[0]]
        # The dot only has ink in the lower half of 'LV.',
        # digits start at the first column with ink in its upper half.
        top = np.nonzero((image[self.TOP + 2:self.TOP + 7] < 128).any(axis=0))[0]
        if len(top):
            image = image[:, max(top[0] - 1, 0):]
        if not image.shape[1]:
            return np.array([[255]], dtype=np.uint8)
        # Drop the rows below the digits, where the border was
        image = image[:h - 4]
        return cv2.copyMakeBorder(image, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))
