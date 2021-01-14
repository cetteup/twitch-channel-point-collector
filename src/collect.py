import argparse
import logging
import time

from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException, NoSuchWindowException, TimeoutException


def check_play_paused_status(desired_status: str, toggle_to_desired: bool = False) -> bool:
    global driver

    status = ''
    try:
        logging.debug('Trying to find play/pause button')
        play_pause_button = driver.find_element_by_css_selector('button[data-a-target="player-play-pause-button"]')
        status = str(play_pause_button.get_attribute('aria-label')).lower()
        if status.startswith(desired_status) and toggle_to_desired:
            logging.info(f'VOD/stream is {status}, but should be {desired_status}, clicking to toggle')
            play_pause_button.click()
    except (NoSuchElementException, ElementNotInteractableException):
        logging.debug('Play/pause button not present')

    # Since the button is supposed to say the opposite! of the desired status, return whether the button does not!
    # reflect the desired status (button says "pause" means vod/stream is playing)
    return not status.startswith(desired_status)


def calc_earned_channel_points(watching_since: datetime, claimed_bonuses: int, multiplier: float = 1.0) -> int:
    # Calculate points earned by watchtime
    # Calculate watchtime in minutes
    watchtime_in_minutes = int((datetime.now() - watching_since).seconds / 60)
    # Twitch awards 10 points for watching 5 minutes of a broadcast
    earned_points = int(watchtime_in_minutes / 5) * POINTS_FOR_WATCHTIME

    # Add points earned by claiming bonuses (50 points each)
    earned_points += claimed_bonuses * POINTS_FOR_BONUS

    # Apply multiplier
    earned_points *= multiplier

    return int(earned_points)


parser = argparse.ArgumentParser(description='Auto-collect Twitch channel points using the Chrome webdriver')
parser.add_argument('--version', action='version', version='twitch-channel-point-collector v0.1.5')
parser.add_argument('--webdriver-path', help='Path to Chrome webdriver executable', type=str, required=True)
parser.add_argument('--login-name', help='Account name of your own account', type=str, required=True)
parser.add_argument('--login-pass', help='Password of your own account', type=str, required=True)
parser.add_argument('--channel-name', help='Names of channels to collect points on '
                                           '(multiple channels will required the browser to run in the foreground)',
                    nargs='+', type=str, required=True)
parser.add_argument('--min-quality', help='Watch stream in minimum quality', dest='min_quality', action='store_true')
parser.add_argument('--mute-audio', help='Mute audio for the webdriven Chrome instance', dest='mute_audio',
                    action='store_true')
parser.add_argument('--debug-log', help='Output tons of debugging information', dest='debug_log', action='store_true')
parser.set_defaults(min_quality=False, mute_audio=False, debug_log=False)
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

# Parse collect channels
collectChannels = []
for channelName in args.channel_name:
    collectChannels.append({
        'channelName': channelName.strip(),
        'negativeLiveCheckCount': 0,
        'windowHandle': None,
        'earnedPoints': 0,
        'subscribed': False,
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
    # Loop over collect channels and try to collect points for each one
    for collectChannel in collectChannels:
        # Filter collect channel list down to ones that are currently active
        activeChannels = [c for c in collectChannels if c['windowHandle'] is not None
                          and c['startedWatchingLiveAt'] is not None]
        # Open tab if required
        if len(activeChannels) < 2 and collectChannel['windowHandle'] is None:
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
                # Iterate over all existing window handles, close those windows/tabs that are not a) active or
                # b) the one we just opened
                for handle in driver.window_handles:
                    if handle != collectChannel['windowHandle'] and handle not in activeChannelWindowHandles:
                        try:
                            logging.debug('Trying to close obsolete window')
                            driver.switch_to.window(handle)
                            driver.close()
                        except NoSuchWindowException:
                            logging.warning('Window/tab to close is already gone')
                        finally:
                            # No matter how, window is now gone => unset window handle
                            channelWindowHandles = [c['windowHandle'] for c in collectChannels]
                            index = channelWindowHandles.index(handle)
                            logging.debug(f'Obsolete window belonged to {collectChannels[index]["channelName"]}, '
                                          f'unsetting window handle')
                            collectChannels[index]['windowHandle'] = None
        elif len(activeChannels) >= 2 and collectChannel not in activeChannels:
            logging.debug(f'Already have two active tabs open, not opening one for {collectChannel["channelName"]}')
            continue

        # Switch to tab for current channel if there are multiple collect channels or tabs
        if len(collectChannels) > 1 or len(driver.window_handles) > 1:
            try:
                logging.info(f'Switching to tab for {collectChannel["channelName"]}')
                driver.switch_to.window(collectChannel['windowHandle'])
            except NoSuchWindowException:
                logging.error(f'Failed to switch to tab for {collectChannel["channelName"]}')
                # Unset window handle so a new tab will be opened next iteration
                collectChannel['windowHandle'] = None
                continue

        # Refresh page after 10 negative live checks
        if collectChannel['negativeLiveCheckCount'] > 10:
            logging.info('Refreshing page')
            # Use get instead of refresh to navigate back to collect channel after host/raid
            try:
                driver.get(f'https://www.twitch.tv/{collectChannel["channelName"]}')
            except TimeoutException:
                logging.error('Failed to refresh page, will retry next iteration')
                continue
            # Reset counter
            collectChannel['negativeLiveCheckCount'] = 0

        # Check whether channel is currently live
        liveIndicators = driver.find_elements_by_css_selector(f'a[href="/{collectChannel["channelName"]}"] '
                                                              f'div.tw-channel-status-text-indicator')
        channelIsLive = len(liveIndicators) > 0

        # Check whether user subscribed to channel
        collectChannel['subscribed'] = len(driver.find_elements_by_css_selector('button[data-a-target='
                                                                                '"subscribed-button"]')) > 0

        # Check whether channel recently went live and "watch now" link is present
        watchNowLinkPresent = False
        try:
            watchNowLink = driver.find_element_by_css_selector('a[data-a-target="home-live-overlay-button"]')
            if 'watch now' in str(watchNowLink.text).lower():
                logging.info('Clicking "watch now" link')
                watchNowLink.click()
        except (NoSuchElementException, ElementNotInteractableException):
            watchNowLinkPresent = False

        # Click "start watching" button if mature content warning is present
        try:
            startWatchingButton = driver.find_element_by_css_selector('button[data-a-target='
                                                                      '"player-overlay-mature-accept"]')
            if 'start watching' in str(startWatchingButton.text).lower():
                logging.info('Clicking "start watching" mature content')
                startWatchingButton.click()
        except (NoSuchElementException, ElementNotInteractableException):
            logging.debug('"Start watching" button not present/interactable')

        if channelIsLive:
            # Store time at which we started watching a live broadcast
            if collectChannel['startedWatchingLiveAt'] is None:
                collectChannel['startedWatchingLiveAt'] = datetime.now()

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

            # Stay for a few seconds
            time.sleep(5)
        else:
            logging.debug('Channel is not live')
            collectChannel['negativeLiveCheckCount'] += 1

            if collectChannel['startedWatchingLiveAt'] is not None:
                # Update earned points
                collectChannel['earnedPoints'] = calc_earned_channel_points(collectChannel['startedWatchingLiveAt'],
                                                                            collectChannel['claimedBonuses'],
                                                                            collectChannel['pointMultiplier'])
                # Unset start timestamp
                collectChannel['startedWatchingLiveAt'] = None

            # Check for and VOD playing
            logging.debug('Checking for VOD player')
            vodPlayerPresent = len(driver.find_elements_by_css_selector('div[data-a-player-type='
                                                                        '"channel_home_carousel"]')) > 0
            # Pause VOD is player is present
            if vodPlayerPresent:
                try:
                    logging.debug('Trying to find play/pause button')
                    playPauseButton = driver.find_element_by_css_selector('button[data-a-target='
                                                                          '"player-play-pause-button"]')
                    if 'pause' in str(playPauseButton.get_attribute('aria-label')).lower():
                        logging.info('Pausing VOD playback')
                        playPauseButton.click()
                except (NoSuchElementException, ElementNotInteractableException):
                    logging.debug('Play/pause button not present')

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
