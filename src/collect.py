import argparse
import logging
import time

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException

parser = argparse.ArgumentParser(description='Auto-collect Twitch channel points using the Chrome webdriver')
parser.add_argument('--webdriver-path', help='Path to Chrome webdriver executable', type=str, required=True)
parser.add_argument('--login-name', help='Account name of your own account', type=str, required=True)
parser.add_argument('--login-pass', help='Password of your own account', type=str, required=True)
parser.add_argument('--channel-name', help='Name of channel to collect points on', type=str, required=True)
parser.add_argument('--min-quality', help='Watch stream in minimum quality', dest='min_quality', action='store_true')
parser.add_argument('--mute-audio', help='Mute audio for the webdriven Chrome instance', dest='mute_audio', action='store_true')
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

logging.info('Opening collect channel on Twitch')
driver.get(f'https://www.twitch.tv/' + args.channel_name)

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

logging.info('Trying to collect points')
while True:
    # Check whether channel is currently live
    liveIndicators = driver.find_elements_by_css_selector(f'a[href="/{args.channel_name}"] div.tw-channel-status-text-indicator')
    channelIsLive = len(liveIndicators) > 0

    if channelIsLive:
        # Turn down quality to the lower available option if requested
        if args.min_quality:
            logging.info('Checking stream quality')
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
            except NoSuchElementException:
                logging.debug('Stream quality settings not present')

        try:
            logging.debug('Trying to find "claim bonus" button')
            claimBonusButton = driver.find_element_by_css_selector('button.tw-button.tw-button--success')
            claimBonusButton.click()
            logging.info('Found button, claimed bonus')
        except NoSuchElementException:
            logging.debug('"Claim bonus" button not present')

        # Wait 30 seconds before checking again
        time.sleep(30)
    else:
        logging.debug('Channel is not live')
