import argparse
import logging
import time

import requests

from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException, NoSuchWindowException, TimeoutException


def check_if_channel_is_live(channel_name: str) -> bool:
    # Check whether channel live
    channel_is_live = False
    try:
        logging.debug(f'Fetching live status for {channel_name}')
        response = requests.get('https://dfscjbhml47d4.cloudfront.net/',
                                params={'channel_name': channel_name})
        if response.status_code == 200:
            parsed = response.json()
            logging.debug(f'Live check ok, API returned: {parsed}')
            channel_is_live = parsed['isLive']
        else:
            logging.error(f'Live check API returned non-200 status ({response.status_code})')
    except Exception as e:
        logging.error(e)
        logging.error('Checking channel live status via API failed')

    return channel_is_live


def check_play_paused_status(desired_status: str, toggle_to_desired: bool = False) -> bool:
    global driver

    status = ''
    try:
        logging.debug('Trying to find play/pause button')
        play_pause_button = driver.find_element_by_css_selector('button[data-a-target="player-play-pause-button"]')
        status = str(play_pause_button.get_attribute('aria-label')).lower()
        if status.startswith(desired_status) and toggle_to_desired:
            logging.info(f'VOD/stream status should be "{desired_status}" but isn\'t, clicking to toggle')
            play_pause_button.click()
    except (NoSuchElementException, ElementNotInteractableException):
        logging.debug('Play/pause button not present')

    # Since the button is supposed to say the opposite! of the desired status, return whether the button does not!
    # reflect the desired status (button says "pause" means vod/stream is playing)
    return not status.startswith(desired_status)


def calc_earned_channel_points(watching_since: datetime, claimed_bonuses: int = 0,
                               multiplier: float = 1.0, buffer: int = 0) -> int:
    # Calculate points earned by watchtime
    # Calculate watchtime in minutes
    watchtime_in_minutes = int((datetime.now() - watching_since).seconds / 60)
    # Twitch awards 10 points for watching 5 minutes of a broadcast
    earned_points = int((watchtime_in_minutes - buffer) / 5) * POINTS_FOR_WATCHTIME

    # Add points earned by claiming bonuses (50 points each)
    earned_points += claimed_bonuses * POINTS_FOR_BONUS

    # Apply multiplier
    earned_points *= multiplier

    return int(earned_points)


parser = argparse.ArgumentParser(description='Auto-collect Twitch channel points using the Chrome webdriver')
parser.add_argument('--version', action='version', version='twitch-channel-point-collector v0.1.7')
parser.add_argument('--webdriver-path', help='Path to Chrome webdriver executable', type=str, required=True)
parser.add_argument('--login-name', help='Account name of your own account', type=str, required=True)
parser.add_argument('--login-pass', help='Password of your own account', type=str, required=True)
parser.add_argument('--channel-name', help='Names of channels to collect points on '
                                           '(multiple channels will required the browser to run in the foreground)',
                    nargs='+', type=str, required=True)
parser.add_argument('--max-concurrent', help='Maximum number of channels to collect points on', type=int,
                    choices=[1, 2], default=2)
parser.add_argument('--asap', help='Immediately switch to higher ranked channel if once is available, do not wait for '
                                   'lower ranked channel to get first points (do not wait for watch streak points)',
                    dest='asap', action='store_true')
parser.add_argument('--unranked', help='Do not prioritize channels based on their order in the channel list',
                    dest='ranked', action='store_false')
parser.add_argument('--min-quality', help='Watch stream in minimum quality', dest='min_quality', action='store_true')
parser.add_argument('--mute-audio', help='Mute audio for the webdriven Chrome instance', dest='mute_audio',
                    action='store_true')
parser.add_argument('--debug-log', help='Output tons of debugging information', dest='debug_log', action='store_true')
parser.set_defaults(ranked=True, asap=False, min_quality=False, mute_audio=False, debug_log=False)
args = parser.parse_args()

logging.basicConfig(level=logging.DEBUG if args.debug_log else logging.INFO, format='%(asctime)s %(levelname)-8s: %(message)s')

POINTS_FOR_WATCHTIME = 10
POINTS_FOR_BONUS = 50

logging.debug('Initializing webdriver')
options = webdriver.ChromeOptions()
if args.mute_audio:
    options.add_argument('--mute-audio')
driver = webdriver.Chrome(options=options, executable_path=args.webdriver_path)
driver.set_window_position(0, 0)
driver.set_window_size(1366, 768)
driver.implicitly_wait(3)

# Set up collect channels
collectChannels = []
for channelName in sorted(set(args.channel_name), key=args.channel_name.index):
    collectChannels.append({
        'channelName': channelName.strip(),
        'negativeLiveCheckCount': 0,
        'windowHandle': None,
        'earnedPoints': 0,
        'pointMultiplier': 0.0,
        'startedWatchingLiveAt': None,
        'claimedBonuses': 0
    })

if len(collectChannels) > 1:
    logging.warning('Running with multiple collect channels, '
                    'browser will be brought to the foreground when switching tabs')

logging.info('Opening (first) collect channel on Twitch')
driver.get(f'https://www.twitch.tv/{collectChannels[0]["channelName"]}')

# Store current window handle for first channel
collectChannels[0]['windowHandle'] = driver.current_window_handle

time.sleep(5)

# Login
logging.info('Logging in')
# Click login button
logging.debug('Clicking top right "login" button')
driver.find_element_by_css_selector('button[data-a-target="login-button"]').click()

# Fill in username and password
logging.debug('Entering username')
driver.find_element_by_id('login-username').send_keys(args.login_name)
logging.debug('Entering password')
driver.find_element_by_id('password-input').send_keys(args.login_pass)

# Click login button (on login dialogue)
logging.debug('Clicking modal "login" button')
driver.find_element_by_css_selector('button[data-a-target="passport-login-button"]').click()

# Wait for user to input validation code
logging.info('Waiting for auth modal to disappear')
authModalPresent = True
while authModalPresent:
    try:
        driver.find_element_by_id('modal-root-header')
        time.sleep(2)
    except NoSuchElementException:
        authModalPresent = False
    logging.debug(f'authModalPresent: {authModalPresent}')

# Accept privacy terms
logging.info('Clicking privacy terms "accept" button')
try:
    driver.find_element_by_css_selector('button[data-a-target="consent-banner-accept"').click()
except (NoSuchElementException, ElementNotInteractableException):
    logging.error('Failed to click privacy terms "accept" button')

# Collapse left sidebar if currently expanded
try:
    logging.debug('Checking whether left sidebar is collapsed')
    leftSidebarExpandToggleButton = driver.find_element_by_css_selector('button[data-a-target="side-nav-arrow"]')

    if 'collapse' in str(leftSidebarExpandToggleButton.get_attribute('aria-label')).lower():
        logging.info('Left sidebar is currently expanded, collapsing it')
        leftSidebarExpandToggleButton.click()
except (NoSuchElementException, ElementNotInteractableException):
    logging.error('Left sidebar expand button not present/interactable')

logging.info('Trying to collect points')
while True:
    if len(collectChannels) > 1:
        # Determine which channels are live
        liveChannels = [c for c in collectChannels if check_if_channel_is_live(c['channelName'])]
        # Determine which channels we want to watch
        if args.ranked and args.asap:
            # Ranked mode enabled with asap => always strive to watch to highest channel(s) asap
            watchChannels = liveChannels[:args.max_concurrent]
        elif args.ranked:
            # Ranked mode enabled without asap => keep watching lower ranked channels until
            # first points have been awarded (watch streak points are awarded with first time-based points)
            watchChannels = [c for c in collectChannels if c in liveChannels and c['windowHandle'] is not None and
                             c['startedWatchingLiveAt'] is not None and
                             calc_earned_channel_points(c['startedWatchingLiveAt'], buffer=1) < POINTS_FOR_WATCHTIME]
            """
            Determine which live channels are candidates to watch now because
            a) there are open "slots"/fewer watch channel that the max
            b) the channels has a higher rank than at least one watch channel
            """
            candidateChannels = [c for c in liveChannels if c not in watchChannels]
            watchChannels += candidateChannels[:args.max_concurrent - len(watchChannels)]
        else:
            # Ranked mode disabled => only fill free slots with live channels
            # Take over any already active channels that are still live
            watchChannels = [c for c in collectChannels if c in liveChannels and
                             c['windowHandle'] is not None and c['startedWatchingLiveAt'] is not None]
            # Fill any free slots
            candidateChannels = [c for c in liveChannels if c not in watchChannels]
            watchChannels += candidateChannels[:args.max_concurrent - len(watchChannels)]
    else:
        watchChannels = collectChannels

    # Determine idle channels
    idleChannels = [c for c in collectChannels if c not in watchChannels]

    # Check whether any idle channels are still marked as being watched
    for collectChannel in idleChannels:
        if collectChannel['startedWatchingLiveAt'] is not None:
            # Update earned points
            collectChannel['earnedPoints'] = calc_earned_channel_points(collectChannel['startedWatchingLiveAt'],
                                                                        collectChannel['claimedBonuses'],
                                                                        collectChannel['pointMultiplier'])
            # Unset start timestamp
            collectChannel['startedWatchingLiveAt'] = None

    # Loop over live channels and try to collect points for each one
    for rank, collectChannel in enumerate(watchChannels):
        # Filter collect channel list down to ones that are currently active
        activeChannels = [c for c in collectChannels if c['windowHandle'] is not None
                          and c['startedWatchingLiveAt'] is not None]

        """
        Open new tab for current channel if there no open tab for this channel AND
        a) fewer than the max two active tabs are open OR
        b) ranked mode is enabled and the current channel has a higher rank than at least one active channel
        """
        obsoleteWindowHandles = []
        if collectChannel['windowHandle'] is None:
            logging.info(f'Opening tab for {collectChannel["channelName"]}')
            # Open tab and navigate to channel
            driver.execute_script(f'window.open("https://www.twitch.tv/{collectChannel["channelName"]}", "_blank");')
            # Find and store window handle
            newHandles = [handle for handle in driver.window_handles if
                          handle not in [c['windowHandle'] for c in collectChannels]]
            collectChannel['windowHandle'] = newHandles[-1]

            # Close any obsolete old tabs
            if len(driver.window_handles) > len(activeChannels):
                activeChannelWindowHandles = [c['windowHandle'] for c in activeChannels]
                # Iterate over all existing window handles, prepare to close those windows/tabs that are not
                # a) active or b) the one we just opened
                obsoleteWindowHandles = [h for h in driver.window_handles if
                                         h != collectChannel['windowHandle'] and
                                         h not in activeChannelWindowHandles]
        elif len(activeChannels) > args.max_concurrent:
            # More than two active tabs/windows are open, prepare to close the lowest ranked one
            obsoleteWindowHandles.append(activeChannels[-1]['windowHandle'])

        # Close any obsolete windows
        for obsoleteWindowHandle in obsoleteWindowHandles:
            try:
                logging.debug('Trying to close obsolete window')
                driver.switch_to.window(obsoleteWindowHandle)
                driver.close()
            except NoSuchWindowException:
                logging.warning('Window/tab to close is already gone')
            finally:
                # No matter how, window is now gone => unset window handle
                channelWindowHandles = [c['windowHandle'] for c in collectChannels]
                index = channelWindowHandles.index(obsoleteWindowHandle)
                logging.debug(f'Obsolete window belonged to {collectChannels[index]["channelName"]}, '
                              f'unsetting window handle')
                collectChannels[index]['windowHandle'] = None
                # Switch to an open tab to avoid running any actions on tabs we just closed
                driver.switch_to.window(driver.window_handles[-1])

        # Switch to tab for current channel if there is one and it is not open already
        if collectChannel['windowHandle'] is not None and \
                collectChannel['windowHandle'] != driver.current_window_handle:
            try:
                logging.info(f'Switching to tab for {collectChannel["channelName"]}')
                driver.switch_to.window(collectChannel['windowHandle'])
            except NoSuchWindowException:
                logging.error(f'Failed to switch to tab for {collectChannel["channelName"]}')
                # Unset window handle so a new tab will be opened next iteration
                collectChannel['windowHandle'] = None

        # Check whether channel is currently live
        liveIndicators = driver.find_elements_by_css_selector(f'a[href="/{collectChannel["channelName"]}"] '
                                                              f'div.tw-channel-status-text-indicator')
        channelIsLive = len(liveIndicators) > 0

        # Check whether channel recently went live and "watch now" link is present
        watchNowLinkPresent = False
        try:
            watchNowLink = driver.find_element_by_css_selector('a[data-a-target="home-live-overlay-button"]')
            if 'watch now' in str(watchNowLink.text).lower():
                logging.info('Clicking "watch now" link')
                watchNowLink.click()
        except (NoSuchElementException, ElementNotInteractableException):
            watchNowLinkPresent = False

        if channelIsLive:
            # Store time at which we started watching a live broadcast
            if collectChannel['startedWatchingLiveAt'] is None:
                logging.info(f'Started watching {collectChannel["channelName"]}')
                collectChannel['startedWatchingLiveAt'] = datetime.now()

            # Click "start watching" button if mature content warning is present
            try:
                startWatchingButton = driver.find_element_by_css_selector('button[data-a-target='
                                                                          '"player-overlay-mature-accept"]')
                if 'start watching' in str(startWatchingButton.text).lower():
                    logging.info('Clicking "start watching" mature content')
                    startWatchingButton.click()
            except (NoSuchElementException, ElementNotInteractableException):
                logging.debug('"Start watching" button not present/interactable')

            # Check if stream is paused
            # When a streaming channel goes offline, the stream still shows as "live" but the stream is "paused"
            if not check_play_paused_status('play'):
                logging.info('Channel should be live but stream seems paused, refreshing page')
                # Use get instead of refresh to navigate back to collect channel after host/raid
                try:
                    driver.get(f'https://www.twitch.tv/{collectChannel["channelName"]}')
                except TimeoutException:
                    logging.error('Failed to refresh page, will retry next iteration')
                finally:
                    continue

            # Turn down quality to the lower available option if requested
            if args.min_quality:
                logging.debug('Checking stream quality')
                try:
                    # Open stream settings
                    logging.debug('Opening stream settings')
                    driver.find_element_by_css_selector('button[aria-label="Settings"]').click()
                    # Click quality
                    logging.debug('Opening quality settings')
                    driver.find_element_by_css_selector('button[data-a-target="player-settings-menu-item-quality"]').click()
                    # Select lowest available option
                    logging.debug('Getting available quality options')
                    qualityOptions = driver.find_elements_by_css_selector('div[data-a-target='
                                                                          '"player-settings-submenu-quality-option"]')
                    if not qualityOptions[-1].find_element_by_tag_name('input').is_selected():
                        logging.info('Turning down stream quality')
                        qualityOptions[-1].click()

                    else:
                        logging.debug('Lowest quality is already selected, closing stream settings')
                        # Click again to close settings
                        driver.find_element_by_css_selector('button[aria-label="Settings"]').click()
                except (NoSuchElementException, ElementNotInteractableException):
                    logging.debug('Stream quality settings not present')

            # Make sure chat is expanded
            try:
                logging.debug('Checking whether chat is collapsed')
                chatExpandToggleButton = driver.find_element_by_css_selector('button[data-a-target='
                                                                             '"right-column__toggle-collapse-btn"]')
                if 'expand' in str(chatExpandToggleButton.get_attribute('aria-label')).lower():
                    logging.info('Chat is currently collapsed, expanding it')
                    chatExpandToggleButton.click()
            except (NoSuchElementException, ElementNotInteractableException):
                logging.error('Chat expand button not present/interactable')

            # Make sure channel uses channel points
            try:
                logging.debug('Trying to find channel point button/indicator')
                driver.find_element_by_css_selector('div[data-test-selector="community-points-summary"] button')
            except NoSuchElementException:
                logging.warning(f'{collectChannel["channelName"]} is not using channel points, skipping')
                continue

            # Get channel point multiplier if not set yet
            if collectChannel['pointMultiplier'] == 0.0:
                try:
                    logging.debug('Opening channel point dialog')
                    driver.find_element_by_css_selector('div[data-test-selector="community-points-summary"] button').click()

                    # Click initial "Get Started" button if present
                    getStartedButtons = driver.find_elements_by_css_selector('div.reward-center-body '
                                                                             'button.tw-core-button--primary')
                    if len(getStartedButtons) > 0:
                        getStartedButtons[0].click()

                    # Check whether multiplier heading is present
                    multiplierHeadings = driver.find_elements_by_css_selector('div#channel-points-reward-center-header h6')
                    # Get multiplier value if heading is present, else use default (1.0)
                    if len(multiplierHeadings) > 0:
                        # Try to split heading and cast to float
                        collectChannel['pointMultiplier'] = float(str(multiplierHeadings[0].text).lower().split('x')[0])
                    else:
                        collectChannel['pointMultiplier'] = 1.0

                    logging.debug('Closing channel point dialog')
                    driver.find_element_by_css_selector('div[data-test-selector="community-points-summary"] button').click()
                except (NoSuchElementException, ElementNotInteractableException):
                    logging.error('Failed to get channel point multiplier')
                    # Use default multiplier
                    collectChannel['pointMultiplier'] = 1.0
                except ValueError:
                    logging.error('Failed to parse channel point multiplier')
                    # Use default multiplier
                    collectChannel['pointMultiplier'] = 1.0

            try:
                logging.debug('Trying to find "claim bonus" button')
                claimBonusButton = driver.find_element_by_css_selector('button.tw-button.tw-button--success')
                claimBonusButton.click()
                logging.info('Found button, claimed bonus')
                # Update bonus counter
                collectChannel['claimedBonuses'] += 1
            except (NoSuchElementException, ElementNotInteractableException):
                logging.debug('"Claim bonus" button not present')

            # If we are currently watching the desired number of channels, stay for a while
            if len(activeChannels) == args.max_concurrent and len(driver.window_handles) == args.max_concurrent:
                time.sleep(60 / args.max_concurrent)
        else:
            logging.debug('Channel is not live')

            if len(collectChannels) == 1 and collectChannel['negativeLiveCheckCount'] < 10:
                # With only one collect channel, timestamp cannot be unset using the above idleChannels loop
                # (the single channel is never considered idle in that sense)
                if collectChannel['startedWatchingLiveAt'] is not None:
                    # Update earned points
                    collectChannel['earnedPoints'] = calc_earned_channel_points(collectChannel['startedWatchingLiveAt'],
                                                                                collectChannel['claimedBonuses'],
                                                                                collectChannel['pointMultiplier'])
                    # Unset start timestamp
                    collectChannel['startedWatchingLiveAt'] = None

                # Only use check counter for single-channel mode
                collectChannel['negativeLiveCheckCount'] += 1
            elif len(collectChannels) == 1:
                # Refresh page after 10 negative live checks
                logging.info('Refreshing page')
                # Use get instead of refresh to navigate back to collect channel after host/raid
                try:
                    driver.get(f'https://www.twitch.tv/{collectChannel["channelName"]}')
                except TimeoutException:
                    logging.error('Failed to refresh page, will retry next iteration')
                    continue
                # Reset counter
                collectChannel['negativeLiveCheckCount'] = 0

            # Check if VOD player is present
            logging.debug('Checking for VOD player')
            vodPlayerPresent = len(driver.find_elements_by_css_selector('div[data-a-player-type='
                                                                        '"channel_home_carousel"]')) > 0
            # Make sure VOD is paused if player is present
            if vodPlayerPresent:
                check_play_paused_status('pause', True)

        # Calculate current broadcast session points
        if collectChannel['startedWatchingLiveAt'] is not None:
            currentBroadcastPoints = calc_earned_channel_points(collectChannel['startedWatchingLiveAt'],
                                                                collectChannel['claimedBonuses'],
                                                                collectChannel['pointMultiplier'])
        else:
            currentBroadcastPoints = 0

        # If we earned any points, log point estimate
        if (collectChannel['earnedPoints'] + currentBroadcastPoints) > 0:
            logging.info(f'Channel points earned for {collectChannel["channelName"]}: '
                         f'{collectChannel["earnedPoints"] + currentBroadcastPoints} (estimate)')

    # If collecting on a single channel, wait 30 seconds before checking again
    if len(collectChannels) == 1:
        time.sleep(30)
