import logging
import requests
from requests import HTTPError
import json
import os

import pwnagotchi
import pwnagotchi.ui.faces as faces
import pwnagotchi.plugins as plugins
from pwnagotchi.utils import save_config

# Installing:
# Move plugin file to /usr/local/pwnagotchi/plugins
# Add this to your pwnagotchi config (/etc/pnagotchi/config.yml):
# custom_plugins: /usr/local/pwnagotchi/plugins
# plugins:
#   discord:
#     enabled: true
#     webhook_url: 'YOUR_URL_HERE'

# Testing:
# You can trigger the webhook to rerun without a new session by deleting the session file:
# sudo rm /root/.pwnagotchi-last-session

# counter on screen how many blind epochs, internet conenctivity icon?

DATA_FILE = '/var/tmp/pwnagotchi/discord_webhooks_temp.json'

def read_json(filename):
    with open(filename, encoding='utf-8', mode="r") as f:
        data = json.load(f)
    return data

def save_json(filename, data):
    with open(filename, encoding='utf-8', mode="w") as f:
        json.dump(data, f, indent=4, sort_keys=True,
            separators=(',', ' : '))
    return data


class Discord(plugins.Plugin):
    __author__ = 'charagarlnad'
    __version__ = '1.1.0'
    __license__ = 'GPL3'
    __description__ = 'Sends Pwnagotchi status webhooks to Discord.'

    def __init__(self):
        self.ready = False

    def on_loaded(self):
        if not os.path.exists(DATA_FILE):
            # dict so we can add to it lateer if needed
            save_json(DATA_FILE, {'failed_webhooks': {}})

        logging.info('Discord plugin loaded.')

    def on_ready(self, agent):
        self._ensure_up_to_date_configs(agent.config())
        self.ready = True

    def _ensure_up_to_date_configs(self, config):
        """migrates old configs if needed"""

        discord = config['main']['plugins']['discord']

        # single -> multi-webhook upgrade
        if 'webhook_url' in discord:
            webhook = discord['webhook_url']

            new_field = []
            if webhook:
                new_field.append(webhook)
            
            discord['webhook_urls'] = new_field
            del discord['webhook_url']

            # updates self.options, so no need to restart
            save_config(config, '/etc/pwnagotchi/config.toml')
            logging.info('[discord] config upgraded to multi-webhooks')

    def on_internet_available(self, agent):
        if not self.ready:
            return

        display = agent.view()
        last_session = agent.last_session

        if last_session.is_new() and last_session.handshakes > 0:
            logging.info('Detected a new session and internet connectivity!')

            # NOT /root/pwnagotchi.png, as we want to send the screen as it is _before_ the sending status update is shown.
            picture = '/dev/shm/pwnagotchi.png'

            display.on_manual_mode(last_session)
            display.update(force=True)
            display.image().save(picture, 'png')

            logging.info('Sending Discord webhooks...')
            display.set('status', 'Sending Discord webhooks...')
            display.update(force=True)

            data = {
                'embeds': [
                    {
                        'title': 'Pwnagotchi Status',
                        'color': 3553599,
                        'description': 'New Pwnagotchi status update available! Here\'s some stats from the last session:',
                        'url': f'https://pwnagotchi.ai/pwnfile/#!{agent.fingerprint()}',
                        'fields': [
                            {
                                'name': 'Uptime',
                                'value': last_session.duration,
                                'inline': True
                            },
                            {
                                'name': 'Epochs',
                                'value': last_session.epochs,
                                'inline': True
                            },
                            {
                                'name': 'Average Reward',
                                'value': str(last_session.avg_reward),
                                'inline': True
                            },
                            {
                                'name': 'Deauths',
                                'value': last_session.deauthed,
                                'inline': True
                            },
                            {
                                'name': 'Associations',
                                'value': last_session.associated,
                                'inline': True
                            },
                            {
                                'name': 'Handshakes',
                                'value': last_session.handshakes,
                                'inline': True
                            }
                        ],
                        'footer': {
                            'text': f'Pwnagotchi v{pwnagotchi.version} - Discord Plugin v{self.__version__}'
                        },
                        'image': {
                            'url': 'attachment://pwnagotchi.png'
                        }
                    }
                ]
            }

            webhooks = set(self.options['webhook_urls'])

            # check for webhooks that didn't get sent
            temp_data = read_json(DATA_FILE)
            previously_failed_webhooks = temp_data['failed_webhooks']
            
            # remove webhooks no longer in config
            valid_failed_webhooks = set(previously_failed_webhooks) & webhooks

            # send failed ones only -- until they're all successful
            if valid_failed_webhooks:
                webhooks = valid_failed_webhooks

            failed = {}
            for webhook in webhooks:
                try:
                    with open(picture, 'rb') as image:
                        r = requests.post(webhook, files={'image': image, 'payload_json': (None, json.dumps(data))})
                    if not r.ok:
                        raise HTTPError(r.status_code)
                except Exception as e:
                    # count failures for later maybe
                    failed[webhook] = previously_failed_webhooks.get(webhook, 0) + 1
            
            temp_data['failed_webhooks'] = failed
            save_json(DATA_FILE, temp_data)

            if not failed:
                # This kinda sucks as the saved session ID is global for all plugins, and was added to core only for the twitter plugin
                # So the Discord plugin as of now is incompatable with the Twitter plugin
                # If the session saving could be modified to either be unique for every plugin or each plugin has to implement it itself it should be better
                # I might just implement it myself tbh if it doesn't get changed and someone wants to use twitter plugin at the same time
                last_session.save_session_id()

                logging.info(f'All {len(webhooks)} webhooks sent!')
                display.set('status', 'Webhooks sent!')
                display.update(force=True)
            else:
                logging.exception(f'{len(failed)} webhooks failed to send in the Discord plugin.')
                display.set('face', faces.BROKEN)
                display.set('status', 'An error occured in the Discord plugin.')
                display.update(force=True)
