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
parser.add_argument('--debug-log', dest='debug_log', action='store_true')
parser.set_defaults(debug_log=False)
args = parser.parse_args()

logging.basicConfig(level=logging.DEBUG if args.debug_log else logging.INFO, format='%(asctime)s %(message)s')

logging.debug('Initializing webdriver')
options = webdriver.ChromeOptions()
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
        authModal = driver.find_element_by_id('modal-root-header')
        authModalPresent = authModal.text == 'Verify login code' or authModal.text == 'Log in to Twitch'
        time.sleep(2)
    except NoSuchElementException:
        authModalPresent = False
    logging.debug(f'authModalPresent: {authModalPresent}')

while True:
    try:
        logging.debug('Trying to find "claim bonus" button')
        claimBonusButton = driver.find_element_by_css_selector('button.tw-button.tw-button--success')
        claimBonusButton.click()
        logging.info('Found button, claimed bonus')
    except NoSuchElementException:
        logging.debug('"Claim bonus" button not present')

    # Wait 30 seconds before checking again
    time.sleep(30)
