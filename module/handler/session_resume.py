from module.base.timer import Timer
from module.combat.assets import *
from module.logger import logger
from module.os_combat.combat import Combat
from module.os_handler.assets import AUTO_SEARCH_OS_MAP_OPTION_ON, AUTO_SEARCH_REWARD


class SessionResume(Combat):
    def is_session_busy(self):
        """
        Returns:
            str: What the game is doing, empty string if it is idle.
        """
        if self.is_combat_executing():
            return 'combat'
        if self.is_combat_loading():
            return 'combat loading'
        if self.is_auto_search_running():
            return 'auto search'
        if self.appear(AUTO_SEARCH_OS_MAP_OPTION_ON, offset=(5, 120)):
            return 'OpSi auto search'
        return ''

    def is_session_result(self):
        """
        Returns:
            bool: If a battle result screen is showing.
        """
        for button in [BATTLE_STATUS_S, BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D,
                       EXP_INFO_S, EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D]:
            if self.appear(button):
                return True
        for button in [GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3]:
            if self.appear(button, offset=5):
                return True
        if self.appear(GET_SHIP, offset=(20, 20)):
            return True
        return False

    def is_session_ended(self):
        """
        Returns:
            bool: If an auto search has finished and is waiting for a click to exit.
                  The normal UI flow will handle it.
        """
        return self.is_in_auto_search_menu() or self.appear(AUTO_SEARCH_REWARD, offset=(50, 50))

    def handle_session_result(self):
        """
        Returns:
            bool: If clicked
        """
        if self.handle_get_ship():
            return True
        if self.handle_get_items():
            return True
        if self.handle_battle_status():
            return True
        if self.handle_exp_info():
            return True
        return False

    def session_resume_wait(self, idle=5, timeout=10800):
        """
        Wait until the game finishes whatever combat or auto search that is already running,
        so the first task won't abort it.
        Never exits or withdraws anything.

        Args:
            idle (int, float): Seconds of being idle to consider the session finished.
            timeout (int, float): Give up after this many seconds.

        Returns:
            bool: If waited for a running session.
        """
        logger.hr('Resume running battle', level=1)
        if not self.device.app_is_running():
            logger.info('Game not running, nothing to resume')
            return False

        try:
            return self._session_resume_wait(idle=idle, timeout=timeout)
        finally:
            self.device.audio_restore()

    def _session_resume_wait(self, idle, timeout):
        idle_timer = Timer(idle, count=int(idle * 2)).start()
        timeout_timer = Timer(timeout).start()
        # Result screens between battles are advanced by the game itself in auto search,
        # give it some time before clicking, then click slowly.
        result_timer = Timer(10)
        result_click_timer = Timer(3)
        waited = False
        last = ''
        for _ in self.loop(skip_first=False):
            if timeout_timer.reached():
                logger.warning('Resume running battle timeout')
                break
            if self.is_session_ended():
                logger.info('Auto search ended, leave the exit to ui_additional')
                break

            busy = self.is_session_busy()
            result = False if busy else self.is_session_result()
            state = busy or ('battle result' if result else '')
            if state:
                if state != last:
                    logger.attr('State', state)
                    if not waited:
                        logger.info('Battle already running, wait until it ends')
                    last = state
                waited = True
                self.device.audio_mute()
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                idle_timer.reset()

                if result:
                    if not result_timer.started():
                        result_timer.start()
                    if result_timer.reached() and result_click_timer.reached():
                        self.handle_session_result()
                        result_click_timer.reset()
                else:
                    result_timer.clear()
                continue

            result_timer.clear()
            if idle_timer.reached():
                break

        logger.info(f'Resume running battle end, waited={waited}')
        return waited
