from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import save_image
from module.combat.assets import *
from module.logger import logger
from module.reward.assets import *
from module.ui.assets import MISSION_CHECK
from module.ui.navbar import Navbar
from module.ui.page import page_main, page_mission, page_reward
from module.ui.ui import UI
from module.ui_white.assets import MISSION_NOTICE_WHITE


class Reward(UI):
    def reward_receive(self, oil, coin, exp):
        """
        Args:
            oil (bool):
            coin (bool):
            exp (bool):

        Returns:
            bool: If rewarded.

        Pages:
            in: page_reward
            out: page_reward, with info_bar if received
        """
        if not oil and not coin and not exp:
            return False

        logger.hr('Reward receive')
        logger.info(f'oil={oil}, coin={coin}, exp={exp}')
        confirm_timer = Timer(1, count=3).start()
        # Set click interval to 0.3, because game can't respond that fast.
        click_timer = Timer(0.3)
        for _ in self.loop():
            if oil and click_timer.reached() and self.appear_then_click(OIL, offset=(20, 50), interval=60):
                confirm_timer.reset()
                click_timer.reset()
                continue
            if coin and click_timer.reached() and self.appear_then_click(COIN, offset=(25, 50), interval=60):
                confirm_timer.reset()
                click_timer.reset()
                continue
            if exp and click_timer.reached() and self.appear_then_click(EXP, offset=(30, 50), interval=60):
                confirm_timer.reset()
                click_timer.reset()
                continue

            # End
            if confirm_timer.reached():
                break

        logger.info('Reward receive end')
        return True

    def _reward_mission_collect(self, weekly=False, interval=1):
        """
        Streamline handling of mission rewards for both 'all' and 'weekly'
        pages, including the weekly page's separate phase-accumulation reward
        widget and ship rewards.

        Restored from a flat, patient loop (exit only after a period of no
        further progress, or an absolute timeout) that worked reliably before
        an upstream refactor (Oct 2025) replaced it with a strict step-by-step
        state machine. That state machine bailed out the moment a single
        screenshot didn't show the exact expected next state - which happens
        whenever a popup, ship reward, or phase reward takes even one extra
        frame to render - leaving genuinely-completed rewards uncollected, or
        (worse) re-clicking the same button with no pacing once its own exit
        condition fired prematurely, tripping ALAS's too-many-clicks guard.

        Args:
            weekly (bool): True when collecting on the weekly page, which has a
                separate phase-accumulation reward widget.
            interval (int, float): Interval for mission claim clicks. Weekly
                benefits from a shorter interval to avoid a premature exit.

        Returns:
            bool: If at least one reward was claimed.
        """
        self.interval_clear([GET_ITEMS_1, GET_ITEMS_2, MISSION_MULTI, MISSION_SINGLE, GET_SHIP])

        exit_timer = Timer(2).start()
        click_timer = Timer(interval)
        timeout = Timer(10).start()
        clicked_mission = False
        reward = False

        for _ in self.loop():
            for button in [GET_ITEMS_1, GET_ITEMS_2]:
                if self.appear_then_click(button, offset=(30, 30), interval=interval):
                    exit_timer.reset()
                    timeout.reset()
                    reward = True
                    # MISSION_SINGLE/PHASE -> GET_ITEMS_* means one reward received
                    if clicked_mission:
                        logger.info('Got items from mission')
                        self.device.click_record_clear()
                        clicked_mission = False
                    continue

            # Weekly page's separate point-accumulation phase reward (週次任務報酬),
            # not part of the per-task row list below. Can be claimed multiple
            # times in a row if enough points are banked. The box still shows the
            # same "受取/RECEIVE AWARD" text even when not yet actually claimable
            # (bar not full) - only its color changes, vivid blue when claimable vs
            # a desaturated gray otherwise (confirmed via live screenshot) - so use
            # match_template_color (shape then color) instead of plain appear(),
            # or blind-clicking the not-yet-ready box trips the too-many-click guard.
            if weekly and click_timer.reached() \
                    and self.match_template_color(MISSION_WEEKLY_PHASE, offset=(20, 20)):
                self.device.click(MISSION_WEEKLY_PHASE)
                clicked_mission = True
                exit_timer.reset()
                click_timer.reset()
                timeout.reset()
                continue

            if not weekly and self.appear(MISSION_UNFINISH, offset=(50, 200)):
                logger.info('Mission is not finished')
                break

            for button in [MISSION_MULTI, MISSION_SINGLE]:
                if not click_timer.reached():
                    continue
                # The row list's own "確認/MOVE FORWARD" (unfinished) button, and
                # on the weekly page the phase box above it too, share the exact
                # same diamond shape as this "受取/RECEIVE AWARD" (claimable)
                # button - only the color differs (vivid blue vs desaturated
                # gray). A big offset scan (needed since a row's claim button
                # isn't at a fixed position) can't tell them apart by shape alone,
                # so require the matching color too on weekly, where this
                # ambiguity actually occurs (confirmed live: shape-only matching
                # landed on both the unfinished row and the not-yet-ready phase
                # box, blind-clicking either into a too-many-click crash).
                matched = self.match_template_color(button, offset=(20, 200), interval=interval, similarity=0.7) \
                    if weekly else self.appear(button, offset=(20, 200), interval=interval, similarity=0.7)
                if matched:
                    self.device.click(button)
                    clicked_mission = True
                    exit_timer.reset()
                    click_timer.reset()
                    timeout.reset()
                    continue

            # Only look for a ship reward popup when we're not plainly on the
            # normal mission list (MISSION_CHECK == page_mission's own check
            # button), avoiding a wasted/false check on every single iteration.
            if not self.appear(MISSION_CHECK):
                if self.appear_then_click(GET_SHIP, interval=interval):
                    exit_timer.reset()
                    click_timer.reset()
                    timeout.reset()
                    continue

            if self.handle_mission_popup_ack():
                exit_timer.reset()
                click_timer.reset()
                timeout.reset()
                continue

            if self.handle_vote_popup():
                exit_timer.reset()
                click_timer.reset()
                timeout.reset()
                continue
            if self.handle_story_skip():
                exit_timer.reset()
                click_timer.reset()
                timeout.reset()
                continue

            if self.handle_popup_confirm('MISSION_REWARD'):
                exit_timer.reset()
                click_timer.reset()
                timeout.reset()
                continue

            # End
            if reward and exit_timer.reached():
                break
            if timeout.reached():
                logger.warning('Wait get items timeout.')
                break

        return reward

    def _reward_mission_all(self):
        """
        Collects all page mission rewards

        Returns:
            bool, if handled
        """
        self.reward_side_navbar_ensure(upper=1)

        if not self.appear(MISSION_MULTI, offset=(20, 200)) \
                and not self.match_template_color(MISSION_SINGLE, offset=(20, 200)):
            logger.info('No MISSION_MULTI or MISSION_SINGLE')
            return False

        return self._reward_mission_collect()

    def _reward_mission_weekly(self):
        """
        Collects weekly page mission rewards

        Returns:
            bool, if handled
        """
        if not self.image_color_count(MISSION_WEEKLY_RED_DOT, color=(206, 81, 66), threshold=30, count=20):
            logger.info('No MISSION_WEEKLY_RED_DOT')
            return False

        self.reward_side_navbar_ensure(upper=5)
        # Shorter interval than the all/daily page to avoid a premature exit
        return self._reward_mission_collect(weekly=True, interval=0.2)

    def reward_mission_notice(self):
        """
        Returns:
            bool: If notice appear

        Pages:
            in: page_main
        """
        if self.appear(MISSION_NOTICE):
            logger.info('Found mission notice MISSION_NOTICE')
            return True
        if self.image_color_count(MISSION_NOTICE_WHITE, color=(214, 117, 99), threshold=30, count=20):
            logger.info('Found mission notice MISSION_NOTICE_WHITE')
            return True

        return False

    def reward_mission(self, daily=True, weekly=True):
        """
        Collects mission rewards

        Args:
            daily (bool): If collect daily rewards
            weekly (bool): If collect weekly rewards

        Returns:
            bool: If rewarded.

        Pages:
            in: page_main
            out: page_mission
        """
        if not daily and not weekly:
            return False
        logger.hr('Mission reward')
        if not self.reward_mission_notice():
            return False

        self.ui_goto(page_mission, skip_first_screenshot=True)

        if daily:
            self._reward_mission_all()
        if weekly:
            self._reward_mission_weekly()

    @cached_property
    def _reward_side_navbar(self):
        """
        side_navbar options:
           all.
           main.
           side.
           daily.
           weekly.
           event.
        """
        reward_side_navbar = ButtonGrid(
            origin=(21, 118), delta=(0, 94.5),
            button_shape=(60, 75), grid_shape=(1, 6),
            name='REWARD_SIDE_NAVBAR')

        return Navbar(grids=reward_side_navbar,
                      active_color=(247, 255, 173),
                      inactive_color=(140, 162, 181))

    def reward_side_navbar_ensure(self, upper=None, bottom=None):
        """
        Ensure able to transition to page
        Whether page has completely loaded is handled
        separately and optionally

        Args:
            upper (int):
                1  for all.
                2  for main.
                3  for side.
                4  for daily.
                5  for weekly.
                6  for event.
            bottom (int):
                6  for all.
                5  for main.
                4  for side.
                3  for daily.
                2  for weekly.
                1  for event.

        Returns:
            bool: if side_navbar set ensured
        """
        if self._reward_side_navbar.set(self, upper=upper, bottom=bottom):
            return True
        return False

    def run(self):
        """
        Pages:
            in: Any page
            out: page_main or page_mission, may have info_bar
        """
        self.ui_ensure(page_reward)
        self.reward_receive(
            oil=self.config.Reward_CollectOil,
            coin=self.config.Reward_CollectCoin,
            exp=self.config.Reward_CollectExp)
        self.handle_info_bar()
        self.ui_goto(page_main)
        self.reward_mission(daily=self.config.Reward_CollectMission,
                            weekly=self.config.Reward_CollectWeeklyMission)
        self.config.task_delay(success=True)
