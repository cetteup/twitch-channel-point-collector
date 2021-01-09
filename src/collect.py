import argparse
import logging
import time

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException, NoSuchWindowException

parser = argparse.ArgumentParser(description='Auto-collect Twitch channel points using the Chrome webdriver')
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

logging.basicConfig(level=logging.DEBUG if args.debug_log else logging.INFO, format='%(asctime)s %(message)s')

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
        'windowHandle': None
    })

if len(collectChannels) > 1:
    logging.info('PLEASE NOTE: Running with multiple collect channels, '
                 'browser will be brought to the foreground when switching tabs')

logging.info('Opening (first) collect channel on Twitch')
driver.get(f'https://www.twitch.tv/' + collectChannels[0]['channelName'])

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
        # Open tab if required
        if collectChannel['windowHandle'] is None:
            logging.info(f'Opening tab for {collectChannel["channelName"]}')
            # Open tab and navigate to channel
            driver.execute_script(f'window.open("https://www.twitch.tv/{collectChannel["channelName"]}", "_blank");')
            # Find and store window handle
            newHandles = [handle for handle in driver.window_handles if
                          handle not in [c['windowHandle'] for c in collectChannels]]
            collectChannel['windowHandle'] = newHandles[-1]

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
            driver.refresh()
            # Reset counter
            collectChannel['negativeLiveCheckCount'] = 0

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

            try:
                logging.debug('Trying to find "claim bonus" button')
                claimBonusButton = driver.find_element_by_css_selector('button.tw-button.tw-button--success')
                claimBonusButton.click()
                logging.info('Found button, claimed bonus')
            except (NoSuchElementException, ElementNotInteractableException):
                logging.debug('"Claim bonus" button not present')
        else:
            logging.debug('Channel is not live')
            collectChannel['negativeLiveCheckCount'] += 1
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

    # Wait 30 seconds before checking again
    time.sleep(30)
