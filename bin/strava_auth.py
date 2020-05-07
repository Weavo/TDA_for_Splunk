#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import splunk
from splunk import rest
from random import choice
import re
from re import search
import time
import logging
import xml.dom.minidom
import xml.sax.saxutils
import os
import json
import requests
from requests import get
import socket
import csv
from csv import writer
import xml.etree.ElementTree as ET

# read in SPLUNK_HOME environment variable or default to /opt/splunk
if 'SPLUNK_HOME' in os.environ:
    splunk_home = os.environ['SPLUNK_HOME']
else:
    splunk_home = '/opt/splunk'


# Set up logging to custom file, strava_auth.log
logging.root
logging.root.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)s  %(module)s - %(message)s')
handler = logging.handlers.RotatingFileHandler(splunk_home + '/var/log/splunk/strava_auth.log', maxBytes=5242880, backupCount=5)
handler.setFormatter(formatter)
logging.root.addHandler(handler)


class auth_handler(splunk.rest.BaseRestHandler):

    # Function definitions

    def isvalidtoken(self, access_token):
        """
        Checks to see if access token exists under the [strava://activities]
        stanza in inputs.conf.
        Returns True if access token is valid.
        Returns False if access token is not valid.

        Arguments:
        ----------------------------------------------------------------
         - access_token : ( string ) used to authenicate to Strava's API
        ----------------------------------------------------------------
        """

        logging.debug("checking to see if token value is valid.")
        if access_token is not None:
            try:
                # Strava auth token regex: [a-zA-Z0-9]{40}
                m = re.search('[a-zA-Z0-9]{40}', access_token)
                if m.group(0):
                    logging.debug("Token is valid: " + str(m.group(0)))
                    return True
                else:
                    logging.debug("The token is not valid:" + str(m.group(0)))
                    return False
            except Exception as e:
                logging.warn("Unable to validate access_token: " + str(e))
                return False
        else:
            return False


    def strava_auth_redirect_url(self, client_id):
        """
        Builds a URL which is used to connect to Strava's authorization
        website and then redirect back to Splunk web.

        Arguments:
        --------------------------------------------------------------
         - client_id : ( integer ) user's client id provided by Strava
        --------------------------------------------------------------
        """

        logging.debug("Attempting to build redirect URL for Strava authorization.")
        try:
            # obtain Splunk host's public IP
            host_public_ip = get('https://api.ipify.org').text
            if host_public_ip:
                domain_tuple = socket.gethostbyaddr(host_public_ip)
                # resolve public IP
                host_domain_name = domain_tuple[0]
                # build redirect URI
                redirect_uri = "https://" + host_domain_name + "/en-US/app/TDA_for_Splunk/strava_config"
                # build Strava authorization URL
                strava_auth_url = "https://www.strava.com/oauth/authorize?response_type=code&approval_prompt=auto&client_id=" + client_id + "&redirect_uri=" + redirect_uri + "&scope=activity:read_all"
                return strava_auth_url
            else:
                raise Exception("Unable to obtain public IP of Splunk host.")
        except Exception as e:
            logging.error("Unable to generate redirect URL: " + str(e))


    def get_strava_token(self, client_id, client_secret, code):
        """
        Executes http POST request to ( https://www.strava.com/oauth/token ).
        Response will return a JSON object containing the access_token,
        token expiration date ( epoch ) and refresh_token.
        Returns dictionary if request is successful.
        Returns None if request is not successful.

        Arguments:
        ---------------------------------------------------------------------
         - client_id     : ( integer ) user's client id provided by Strava

         - client_secret : ( string ) user's client secret provided by Strava

         - code          : ( string ) value to be exchanged for access token
        ----------------------------------------------------------------------
        """

        logging.debug("Attempting to obtain access token from Strava.")
        token_args = {'client_id': client_id, 'client_secret': client_secret, 'code': code, 'grant_type': 'authorization_code'}
        # http POST request to Strava authorization endpoint
        strava_response = requests.post('https://www.strava.com/oauth/token', data=token_args)
        if strava_response:
            # convert JSON response object to a dictionary
            strava_token_dict = strava_response.json()
            logging.info("Strava access token dictionary obtained: " + str(strava_token_dict))
            return strava_token_dict
        else:
            logging.error("Failed to obtain access token from Strava.")
            return None


    def change_default_dash(self):
        """
        Changes the default dashboard from strava_config(Setup) 
        to the overview(Overview) dashboard in default.xml.
        """

        logging.debug("Attempting to modify default.xml...")
        try:
            # open default.xml
            file_path = splunk_home + '/etc/apps/TDA_for_Splunk/local/data/ui/nav/default.xml'
            tree = ET.parse(file_path)
            root = tree.getroot()
            # remove default="true" from element
            old_default = root.find("*[@default='true']")
            logging.debug
            old_default.clear()
            old_default.set('name', 'strava_config')
            # append default="true" to element
            new_default = root.find("*[@name='overview']")
            new_default.set('default', 'true')
            # write changes to default.xml
            tree.write(file_path)
            logging.debug("Successfully modified default.xml.")
            # reload navigation files for app
            endpoint = '/servicesNS/-/-/admin//nav/_reload'
            reload_nav = splunk.rest.simpleRequest(endpoint, method="GET", raiseAllErrors=True, sessionKey=self.sessionKey)
        except Exception as e:
            logging.error("Unable to modify default.xml: %s" % e)


    def write_to_csv(self, strava_token_dict, client_id):
        """
        Writes Strava user's account information to a file ( strava_users.csv ).

        Arguments:
        -----------------------------------------------------------------------------------
        - strava_token_dict : ( dictionary ) contains the user's Strava account information

        - client_id         : ( integer ) user's client id provided by Strava
        -----------------------------------------------------------------------------------
        """

        # extract values into a list
        firstname = strava_token_dict['athlete']['firstname']
        lastname = strava_token_dict['athlete']['lastname']
        city = strava_token_dict['athlete']['city']
        state = strava_token_dict['athlete']['state']
        country = strava_token_dict['athlete']['country']
        user_info = [client_id, firstname, lastname, city, state, country]

        logging.debug("Attempting to write Strava user information to file.")
        try:
            # open and write list to strava_users.csv
            file_path = splunk_home + '/etc/apps/TDA_for_Splunk/lookups/strava_users.csv'
            with open(file_path, 'a+') as strava_users:
                csv_writer = writer(strava_users)
                csv_writer.writerow(user_info)
                logging.debug("Strava user information was successfully written to file.")
        except Exception as e:
            logging.error("Failed to write Strava user information to file: " + str(e))


    def write_token_to_config(self, strava_token_dict):
        """
        Writes contents of a dictionary to the Strava modular input config.

        Arguments:
        -----------------------------------------------------------------------------
         - strava_token_dict : ( dictionary ) contains the user's account information
        -----------------------------------------------------------------------------
        """

        logging.debug("Attempting to write token dictionary to [strava://activities] stanza in inputs.conf")
        if self.write_config('access_token', strava_token_dict['access_token']):
            if self.write_config('expires_at', strava_token_dict['expires_at']):
                if self.write_config('refresh_token', strava_token_dict['refresh_token']):
                    logging.debug("access token value: " + str(strava_token_dict['access_token']))
                    logging.debug("expires_at value: " + str(strava_token_dict['expires_at']))
                    logging.debug("refresh_token value: " + str(strava_token_dict['refresh_token']))
                    self.return_success('Strava access token fields successfully updated to Strava modular input config.')
                else:
                    logging.error("Unable to write refresh_token to [strava://activities] stanza in inputs.conf")
                    self.return_error('Unable to write refresh token.')
            else:
                logging.error("Unable to write expires_at to [strava://activities] stanza in inputs.conf")
                self.return_error('Unable to write token expiration.')
        else:
            logging.error("Unable to write access_token to [strava://activities] stanza in inputs.conf")
            self.return_error('Unable to write access token.')

        # reload inputs configuration file
        endpoint = '/servicesNS/nobody/TDA_for_Splunk/admin/strava/_reload'
        reload_endpoint = splunk.rest.simpleRequest(endpoint, method="GET", raiseAllErrors=True, sessionKey=self.sessionKey)


    def parse_config(self):
        """
        Parses attributes under the [strava://activities] stanza in inputs.conf.
        """

        logging.debug("Attempting to parse Strava modular input config.")
        splunk_config = {}
        splunk_config['client_id'] = self.read_config('client_id')
        splunk_config['client_secret'] = self.read_config('client_secret')
        splunk_config['access_token'] = self.read_config('access_token')
        splunk_config['expires_at'] = self.read_config('expires_at')
        splunk_config['refresh_token'] = self.read_config('refresh_token')
        logging.debug("Config contents: " + str(splunk_config))
        return splunk_config


    def return_success(self, success_message):
        """
        Prints a message to the user stating the access token exists.

        Arguments:
        -------------------------------------------------------
         - success_message : ( string ) message to be displayed
        -------------------------------------------------------
        """

        logging.info("Success message: " + str(success_message))
        print("<success><message>%s</message></success>" % xml.sax.saxutils.escape(success_message))


    def return_error(self, error_message):
        """
        Prints a message to the user stating the
        client id and client secret are not available.

        Arguments:
        -----------------------------------------------------
         - error_message : ( string ) message to be displayed
        -----------------------------------------------------
        """

        logging.error("Error message: " + str(error_message))
        print("<error><message>%s</message></error>" % xml.sax.saxutils.escape(error_message))


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
                logging.error("Unable to validate successful write of " + str(key_name) + " value of '" + str(value) + "' to the Strava modular input config. Current value = '" + str(new_value) + "'")
                return False
        except Exception as e:
            logging.error("Unable to write " + str(key_name) + " value of '" + str(value) + "' to the Strava modular input config: " + str(e))
            return False


    def read_config(self, key_name):
        """
        Executes REST call to Splunk API.
        Response returns the value ( if any ) associated with key_name.
        Returns value if response contains a value.
        Returns None if repsonse does not contain a value.

        Arguments:
        -----------------------------------------------------
         - key_name : ( string ) key name to be passed to API
        -----------------------------------------------------
        """

        logging.debug("Verifying script is able to read modular input config from rest api.")
        endpoint = '/servicesNS/nobody/TDA_for_Splunk/data/inputs/strava/activities'
        endpoint_args = {'output_mode': 'json'}
        # GET request to data inputs endpoint
        config_response = splunk.rest.simpleRequest(endpoint, method="GET", getargs=endpoint_args, raiseAllErrors=True, sessionKey=self.sessionKey)
        try:
            config_content = config_response[1]
            config = json.loads(config_content)
            logging.debug('Parsing ' + str(key_name) + ' from content...')
            value = config['entry'][0]['content'][key_name]
            logging.debug("Value read from modular input config: " + str(key_name) + "=" + str(value))
            return value
        except Exception as e:
            logging.warn("Unable to read %s config value for modular input: " + str(e) % key_name)
            return None


    def handle_POST(self):
        """
        Handles POST requests to the strava/auth endpoint.

        Required URL parameters:
        ---------------------------------------------------------------------
         - client_id     : ( integer ) user's client id provided by Strava

         - client_secret : ( string ) user's client secret provided by Strava

         - code          : ( string ) value to be exchanged for access token
        ----------------------------------------------------------------------
        """

        logging.info("Enter Strava authorization endpoint POST handler...")
        sessionKey = self.sessionKey
        # make sure client_id AND client_secret are passed from POST request
        if 'client_id' and 'client_secret' in self.request['form']:
            try:
                logging.debug("client_id: " + str(self.request['form']['client_id']))
                logging.debug("client_secret: " + str(self.request['form']['client_secret']))
                # write client_id and client_secret to inputs config endpoint
                if self.write_config('client_id', self.request['form']['client_id']) and self.write_config('client_secret', self.request['form']['client_secret']):
                    logging.debug("client_id and client_secret have been saved to inputs config file.")
                    # build redirect url
                    redirect_url = self.strava_auth_redirect_url(self.request['form']['client_id'])
                    logging.debug("redirect url: " + str(redirect_url))
                    self.response.setHeader('content-type', 'text/plain-text')
                    # send redirect url back to user's browser
                    self.response.write(redirect_url)
                else:
                    logging.error("Unable to write client ID and client secret to inputs config file. ")
                    self.return_error("Unable to write client ID and client secret to inputs config file.")
            except Exception as e:
                logging.error("Strava auth endpoint failed to receive valid client id and/or client secret from dashboard: " + str(e))
        # make sure code is passed from user's web browser
        elif 'code' in self.request['form']:
            try:
                logging.debug("code: " + str(self.request['form']['code']))
                splunk_config = None
                splunk_config = self.parse_config()
                if splunk_config:
                    # exchange code for authorized token from Strava
                    strava_token_dict = self.get_strava_token(splunk_config['client_id'], splunk_config['client_secret'], self.request['form']['code'])
                    if strava_token_dict:
                        # write access token, refresh token, and expiration date to input configs endpoint
                        self.write_token_to_config(strava_token_dict)
                        # write Strava user information to csv
                        self.write_to_csv(strava_token_dict, splunk_config['client_id'])
                        logging.info("Obtained authorized token from Strava.")
                        self.return_success("Obtained authorized token from Strava.")
                        self.change_default_dash()
                        self.response.write(strava_token_dict.response_status)
                    elif self.isvalidtoken(splunk_config['access_token']):
                        logging.info("Token already exists. Nothing to do.")
                        self.return_success("Token already exists. Nothing to do.")
                    else:
                        self.return_success(self.strava_auth_redirect_url(splunk_config['client_id']))
                else:
                    logging.error("Error parsing config file before attempting to obtain Strava token.")
            except Exception as e:
                logging.error("Failed to obtain authorized token from Strava: " + str(e))
        else:
            logging.error("POST call to Strava auth endpoint missing 'code' URL parameter. ")

    #  handle verbs, otherwise Splunk will throw an error
    handle_GET = handle_POST
