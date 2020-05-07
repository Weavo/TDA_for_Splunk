#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import splunk
from splunk import rest
import logging
import os
import json
import requests


# read in SPLUNK_HOME environment variable or default to /opt/splunk
if 'SPLUNK_HOME' in os.environ:
    splunk_home = os.environ['SPLUNK_HOME']
else:
    splunk_home = '/opt/splunk'


# Set up logging to custom file, strava_refresh.log
logging.root
logging.root.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)s  %(module)s - %(message)s')
handler = logging.handlers.RotatingFileHandler(splunk_home + '/var/log/splunk/strava_refresh.log', maxBytes=5242880, backupCount=5)
handler.setFormatter(formatter)
logging.root.addHandler(handler)


class refresh_handler(splunk.rest.BaseRestHandler):

    # Function definitions

    def write_config(self, key_name, value):
        """
        Updates Strava modular input config with specified key/value pair.
        Returns True if key/value pair was successfully written to file.
        Returns False if an error occurd writing key/value pair to file.

        Arguments:
        --------------------------------------------------------------
         - key_name : ( string ) key name to be written to inputs.conf

         - value    : ( string ) value to be written to inputs.conf
        --------------------------------------------------------------
        """

        logging.debug("Writing new value to modular input config.")
        try:
            endpoint = '/servicesNS/nobody/TDA_for_Splunk/configs/inputs/strava%3A%252F%252Factivities'
            endpoint_args = {'output_mode': 'json', key_name: value}
            # POST request to configs endpoint
            write_config_response = splunk.rest.simpleRequest(endpoint, method="POST", postargs=endpoint_args, raiseAllErrors=True, sessionKey=self.sessionKey)
            write_config_content = write_config_response[1]
            config = json.loads(write_config_content)
            new_value = config['entry'][0]['content'][key_name]
            if str(value) == str(new_value):
                logging.debug("The following new value was written to modular input config: " + str(key_name) + "=" + str(new_value))
                return True
            else:
                logging.warn("Unable to validate successful write of " + str(key_name) + " value of '" + str(value) + "' to the Strava modular input config. Current value = '" + str(new_value) + "'")
                return False
        except Exception as e:
            logging.error("Unable to write " + str(key_name) + " value of '" + str(value) + "' to the Strava modular input config: " + str(e))
            return False


    def refresh_token(self, client_id, client_secret, refresh_token):
        """
        Executes REST call to ( https://www.strava.com/oauth/token ).
        Response returns a JSON object containing the access token,
        expiration date(epoch) and refresh token.
        The new values will be written to the input configs endpoint.

        Arguments:
        ---------------------------------------------------------------------
         - client_id     : ( integer ) user's client id provided by Strava

         - client_secret : ( string ) user's client secret provided by Strava

         - refresh_token : ( string ) used to obtain a new access token
        ---------------------------------------------------------------------
        """

        try:
            logging.debug("Attempting to refresh access token.")
            refresh_args = {'client_id': client_id, 'client_secret': client_secret, 'refresh_token': refresh_token, 'grant_type': 'refresh_token'}
            # POST request to Strava token refresh endpoint
            strava_response = requests.post('https://www.strava.com/oauth/token', data=refresh_args)
            logging.debug("Strava API response code: %s" % strava_response.status_code)
            if strava_response:
                # convert JSON object to a dictionary
                refresh_token_dict = strava_response.json()
                logging.debug("refresh_token_dict: " + str(refresh_token_dict))
                return refresh_token_dict['access_token']
                logging.debug("Attempting to write refresh token dictionary to the strava stanza in inputs.conf")
                if self.write_config('access_token', refresh_token_dict['access_token']):
                    logging.debug("access token value: " + str(refresh_token_dict['access_token']))
                    if self.write_config('expires_at', refresh_token_dict['expires_at']):
                        logging.debug("expires_at value: " + str(refresh_token_dict['expires_at']))
                        if self.write_config('refresh_token', refresh_token_dict['refresh_token']):
                            logging.debug("refresh_token value: " + str(refresh_token_dict['refresh_token']))
                        else:
                            logging.error("Unable to write refresh_token to the [strava://activities] stanza in inputs.conf")
                    else:
                        logging.error("Unable to write expires_at to the [strava://activities] stanza in inputs.conf")
                else:
                    logging.error("Unable to write access_token to the [strava://activities] stanza in inputs.conf")
            else:
                logging.error("Failed to receive response from Strava API.")
        except Exception as e:
            logging.error("Failed to refresh access token: " + str(e))


    def handle_POST(self):
        """
        Handles POST requests to strava/refresh Splunk endpoint.

        Required URL parameters:
        ---------------------------------------------------------------------
         - client_id     : ( integer ) user's client id provided by Strava

         - client_secret : ( string ) user's client secret provided by Strava

         - refresh_token : ( string ) used to obtain a new access token
        ---------------------------------------------------------------------
        """

        logging.debug("Enter Strava refresh endpoint POST handler...")

        sessionKey = self.sessionKey
        # make sure client_id, client_secret and refresh_token are passed from modular input script
        if 'client_id' and 'client_secret' and 'refresh_token' in self.request['form']:
            try:
                logging.debug("client ID: " + str(self.request['form']['client_id']))
                logging.debug("client secret: " + str(self.request['form']['client_secret']))
                logging.debug("refresh token: " + str(self.request['form']['refresh_token']))
                # refresh access token
                new_access_token = self.refresh_token(self.request['form']['client_id'], self.request['form']['client_secret'], self.request['form']['refresh_token'])
                logging.debug("new_access_token: " + str(new_access_token))
                self.response.setHeader('content-type', 'text/plain-text')
                # send new access token back to modular input script
                self.response.write(new_access_token)
            except Exception as e:
                logging.error("Strava refresh endpoint failed to refesh access token: " + str(e))
        else:
            logging.error("POST call to Strava refresh endpoint missing required URL parameter(s).")


    #  handle verbs, otherwise Splunk will throw an error
    handle_GET = handle_POST
