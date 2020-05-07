#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import json
import logging
import logging.handlers
from logging.handlers import RotatingFileHandler
import os
import xml
import xml.dom.minidom
import time
import datetime
from datetime import datetime
import requests
import splunk
from splunk import rest
import csv
from csv import writer


# read in SPLUNK_HOME environment variable or default to /opt/splunk
if 'SPLUNK_HOME' in os.environ:
    splunk_home = os.environ['SPLUNK_HOME']
else:
    splunk_home = '/opt/splunk'


# import geopy libraries from specified path
lib_path = splunk_home + '/etc/apps/TDA_for_Splunk/lib'
sys.path.insert(1, lib_path)
import geopy
from geopy.geocoders import Nominatim
from geopy.point import Point


# Set up logging to custom file, strava.log
logging.root
logging.root.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)s  %(module)s - %(message)s')
handler = logging.handlers.RotatingFileHandler(splunk_home + '/var/log/splunk/strava.log', maxBytes=5242880, backupCount=5)
handler.setFormatter(formatter)
logging.root.addHandler(handler)


# introspection scheme
SCHEME = """<scheme>
    <title>Strava Modular Input</title>
    <description>Modular Input to retrieve event data from Strava's v3 API.</description>
    <use_external_validation>false</use_external_validation>
    <streaming_mode>simple</streaming_mode>

    <endpoint>
        <args>
            <arg name="expires_at">
                <validation>is_pos_int(expires_at)</validation>
                <title>Access Token Expiration</title>
                <description>Strava access token expiration date in epoch format</description>
            </arg>

            <arg name="access_token">
                <validation>validate(match('access_token', '[a-z0-9]{40}'), "Access token must not be null.")</validation>
                <title>Access Token</title>
                <description>Strava access token</description>
            </arg>
        </args>
    </endpoint>
</scheme>
"""


# function definitions
def do_scheme():
    """
    Prints introspection scheme to stdout
    """

    print(SCHEME)


def write_geo_info(geo_list):
    """
    Writes the contents of a list to a file ( geo_cache.csv ).

    Arguments:
    ---------------------------------------------------------------------
     - geo_list : ( list ) contains latitude, longitude
                  and location information about the lat/long coordinates
    ---------------------------------------------------------------------
    """

    logging.debug("Attempting to write geo lookup information to file.")
    try:
        # open and write list to geo_cache.csv
        file_path = splunk_home + '/etc/apps/TDA_for_Splunk/lookups/geo_cache.csv'
        with open(file_path, 'a+') as geo_cache:
            csv_writer = writer(geo_cache)
            # writes list to file
            csv_writer.writerow(geo_list)
            logging.debug("Geo lookup information was successfully written to file.")
    except Exception as e:
        logging.debug("Failed to write geo lookup information to file: " + str(e))


def geo_info_exists(latitude, longitude):
    """
    Compares a coordinate pair ( latitude, longitude ) against
    other coordinate pairs contained in a file ( geo_cache.csv ).
    Returns True if the coordinate pair exists in the file.
    Returns False if the coordinate pair does not exist in the file.

    Arguments:
    ---------------------------------------------
     - latitude  : ( float ) value to be compared

     - longitude : ( float ) value to be compared
     --------------------------------------------
    """

    file_path = splunk_home + '/etc/apps/TDA_for_Splunk/lookups/geo_cache.csv'
    matches = 0
    with open(file_path) as geofile:
        geo_reader = csv.DictReader(geofile)
        for row in geo_reader:
            lat_cached = float(row['start_latitude'])
            long_cached = float(row['start_longitude'])
            if lat_cached == float(latitude) and long_cached == float(longitude):
                matches += 1
                return True

    if matches == 0:
        return False


def reverse_geo_lookup(latitude, longitude):
    """
    Executes REST call to Nominatim API.
    Converts coordinate ( lat/long ) pair into a string containing
    information about the location.
    Returns True if a REST call to Nominatum was waranted AND successful.
    Returns False if a REST call to Nominatum was not waranted OR unsuccessful.

    Arguments:
    ----------------------------------------------
     - latitude  : ( float ) value to be converted

     - longitude : ( float ) value to be converted
     ---------------------------------------------
    """

    logging.debug("latitude value: " + str(latitude) + " " + "type: " + str(type(latitude)))
    logging.debug("longitude value: " + str(longitude) + " " + "type: " + str(type(longitude)))

    if type(latitude) and type(longitude) is float:
        if not geo_info_exists(latitude, longitude):
            logging.debug("Attempting to covert coordinates to location.")
            try:
                # Nominatim requires AT LEAST one second bewteen queries
                time.sleep(1.0)
                normalized_address = None
                geolocator = Nominatim(user_agent="TDA_for_Splunk")
                coordinates = Point(latitude, longitude)
                # rest call to Nominatim
                location = geolocator.reverse(coordinates)
                # extract values from response
                address_name = location.raw['display_name']
                address_items = address_name.split(",")
                # parse values from address_items
                if (len(address_items) - 5) >= 0:
                    start = (len(address_items) - 5)
                else:
                    start = 0
                for x in range(start, len(address_items)):
                    if normalized_address:
                        normalized_address += "," + str(address_items[x])
                    else:
                        normalized_address = str(address_items[x]).lstrip()
                logging.debug("Successfully converted coordinates to location.")
                geo_list = [latitude, longitude, normalized_address]
                # write geo information to file
                write_geo_info(geo_list)
                return True
            except Exception as e:
                logging.error("Unable to convert coordinates to location: " + str(e))
                return False
        else:
            logging.debug("Coordinates exist. Nothing to do.")
            return False
    else:
        logging.debug("Invalid coordinates. Nominatim will not be queried.")


def get_strava_activities(config, access_token, after_date):
    """
    Executes REST call to Strava's API to retrieve user's activities data.
    Prints one JSON object per activity to stdout.
    Returns True if retreival of activitites data was successful.
    Returns False if there was a problem retreiving activities data.

    Arguments:
    ----------------------------------------------------------------------
     - config       : ( dictionary ) contains modular input configuration
                      provided by Splunkd

     - access_token : ( string ) token used to authenicate to Strava's API

     - after_date   : ( integer ) epoch timestamp of the most recent
                      activity indexed by Splunk
     ---------------------------------------------------------------------
    """

    # dictionary to store activites data
    strava_activities = {}
    # handles pagination for Strava API (200 records/page)
    page_num = 0
    checkpoint = 0
    while True:
        page_num += 1
        try:
            strava_args = {'after': after_date, 'access_token': access_token, 'page': page_num, 'per_page': 200}
            # http GET request to Strava's athlete/activites endpoint
            strava_response = requests.get('https://www.strava.com/api/v3/athlete/activities', data=strava_args)
            logging.debug("Strava API response code: %s" % strava_response.status_code)
            if strava_response:
                # convert JSON response object to a dictionary
                strava_activities = strava_response.json()
                logging.info("Number of activities returned: %s" % len(strava_activities))
                if len(strava_activities) == 0:
                    logging.info("Detected last page -- no activites returned")
                    if page_num == 1:
                        logging.debug("No new activities to retrieve from Strava.")
                    break
                else:
                    # parse strava_activities dictionary for desired key/value pairs.
                    for strava_activity in strava_activities:
                        # dictionary to store desired key/value pairs from strava_activities dictionary
                        output = {}
                        if 'start_date' in strava_activity:
                            output['start_date'] = datetime.strftime(datetime.strptime(strava_activity['start_date'], '%Y-%m-%dT%H:%M:%SZ'), '%Y-%m-%d %H:%M:%S %z')
                            # convert start_date value to an epoch value and  write to output{}
                            epoch = datetime.strftime(datetime.strptime(strava_activity['start_date'], '%Y-%m-%dT%H:%M:%SZ'), '%s')
                            if epoch > checkpoint:
                                # update checkpoint value
                                checkpoint = epoch
                        # field extractions
                        if 'name' in strava_activity:
                            output['name'] = strava_activity['name']
                        if 'distance' in strava_activity:
                            output['distance'] = strava_activity['distance']
                        if 'moving_time' in strava_activity:
                            output['moving_time'] = strava_activity['moving_time']
                        if 'total_elevation_gain' in strava_activity:
                            output['total_elevation_gain'] = strava_activity['total_elevation_gain']
                        if 'type' in strava_activity:
                            output['type'] = strava_activity['type']
                        if 'start_latitude' and 'start_longitude' in strava_activity:
                            output['start_latitude'] = strava_activity['start_latitude']
                            output['start_longitude'] = strava_activity['start_longitude']
                            logging.debug("latitude: " + str(output['start_latitude']))
                            logging.debug("longitude: " + str(output['start_longitude']))
                            if reverse_geo_lookup(output['start_latitude'], output['start_longitude']):
                                logging.debug("Coordinates were successfully converted to location.")
                        if 'average_speed' in strava_activity:
                            output['average_speed'] = strava_activity['average_speed']
                        if 'max_speed' in strava_activity:
                            output['max_speed'] = strava_activity['max_speed']
                        if 'average_cadence' in strava_activity:
                            output['average_cadence'] = strava_activity['average_cadence']
                        if 'kilojoules' in strava_activity:
                            output['kilojoules'] = strava_activity['kilojoules']
                        if 'average_heartrate' in strava_activity:
                            output['average_heartrate'] = strava_activity['average_heartrate']
                        if 'max_heartrate' in strava_activity:
                            output['max_heartrate'] = strava_activity['max_heartrate']
                        output['client_id'] = config['client_id']
                        # convert output dictionary to a JSON object and write it to the strava index.
                        print(json.dumps(output))
            else:
                logging.error("Strava API did not return a response when requesting activities.")
                return False
        except Exception as e:
            logging.error("Unable to retrieve activities data from Strava API: %s" % str(e))
            print_error(e)
            return False
    if checkpoint != 0:
        # save checkpoint value with the latest activity indexed.
        save_checkpoint(config, 'activities', checkpoint)
    return True


def print_error(s):
    """
    Prints XML error data to be consumed by Splunk.

     Arguments:
    ------------------------------------
      - s : ( string ) the error message
    ------------------------------------
    """

    print("<error><message>%s</message></error>" % xml.sax.saxutils.escape(s))
    logging.error("%s" % str(s))


def token_is_expired(expires_at):
    """
    Check to see if access token is expired.
    Returns True if access token is expired.
    Returns False if access token is not expired.

    Arguments:
    ----------------------------------------------------------------------------
     - expires_at : ( integer ) epoch timestamp of when the access token expires
    ----------------------------------------------------------------------------
    """

    logging.debug("Checking token expiration date.")
    if expires_at:
        now_date = time.gmtime(time.time())
        logging.debug("now_date: " + str(now_date))
        expires_at_int = int(expires_at)
        expire_date = time.gmtime(expires_at_int)
        logging.debug("expire_date: " + str(expire_date))
        if expire_date > now_date:
            logging.debug("token is not expired.")
            return False
        else:
            logging.debug("token is expired.")
            return True
    else:
        return True


def refresh_token(client_id, client_secret, refresh_token, session_key):

    """
    Executes REST call to the strava/refresh Splunk endpoint.
    The endpoint responds with a tuple containing the new access token.
    Returns the new access token ( string ).

    Arguments:
    ----------------------------------------------------------------------------------
     - client_id     : ( integer ) user's client id provided by Strava

     - client_secret : ( string ) user's client secret provided by Strava

     - refresh_token : ( string ) used for authentication to obtain a new access token

     - session_key   : ( string ) key to authenticate to Splunk REST API
    ----------------------------------------------------------------------------------
    """

    try:
        logging.debug("Attempting to refresh access token.")
        endpoint = '/services/strava/refresh'
        refresh_args = {'client_id': client_id, 'client_secret': client_secret, 'refresh_token': refresh_token}
        # http POST request to strava/refresh endpoint
        new_access_token_tuple = splunk.rest.simpleRequest(endpoint, method="POST", postargs=refresh_args, raiseAllErrors=True, sessionKey=session_key)
        token_from_tuple = new_access_token_tuple[1]
        return token_from_tuple
    except Exception as e:
        logging.error("Unable to refresh access token: " + str(e))
        print_error(e)


def validate_conf(config, key):
    """
    Checks to see if required key names are present in the config dictionary.

    Arguments:
    ---------------------------------------------------------------
     - config : ( dictionary ) contains modular input configuration
                provided by Splunkd

     - key    : ( string ) the key name being validated
    ---------------------------------------------------------------
    """

    if key not in config:
        print_error("Invalid configuration received from Splunk: key '%s' is missing." % key)


def get_config():
    """
    Parses XML modular input configuration provided
    by Splunkd into a dictionary.
    Based on example provided at:
    https://docs.splunk.com/Documentation/Splunk/latest/
    AdvancedDev/ModInputsExample#S3_example
    """

    config = {}
    try:
        # store XML modular input configuration provided by Splunkd via stdin
        config_str = sys.stdin.read()

        # use XML DOM to parse modular input configuration
        doc = xml.dom.minidom.parseString(config_str)
        root = doc.documentElement
        # store session key value from DOM object in config dictionary
        node_list = root.getElementsByTagName('session_key')
        sk_node = node_list[0]
        child = sk_node.firstChild
        session_key = child.data
        config['session_key'] = session_key
        # store modular input configuration values from DOM object to config dictionary
        conf_node = root.getElementsByTagName("configuration")[0]
        if conf_node:
            logging.debug("XML: found configuration")
            stanza = conf_node.getElementsByTagName("stanza")[0]
            if stanza:
                stanza_name = stanza.getAttribute("name")
                if stanza_name:
                    logging.debug("XML: found stanza " + stanza_name)
                    config["name"] = stanza_name
                    params = stanza.getElementsByTagName("param")
                    for param in params:
                        param_name = param.getAttribute("name")
                        logging.debug("XML: found param '%s'" % param_name)
                        if param_name and param.firstChild and \
                           param.firstChild.nodeType == param.firstChild.TEXT_NODE:
                            data = param.firstChild.data
                            config[param_name] = data
                            logging.debug("XML: '%s' -> '%s'" % (param_name, data))
        # store checkpoint file directory value from DOM object in config dictionary
        checkpnt_node = root.getElementsByTagName("checkpoint_dir")[0]
        if checkpnt_node and checkpnt_node.firstChild and \
           checkpnt_node.firstChild.nodeType == checkpnt_node.firstChild.TEXT_NODE:
            config["checkpoint_dir"] = checkpnt_node.firstChild.data
        # raise exception if config was not provided
        if not config:
            raise Exception("Invalid configuration received from Splunk.")

        # validate that required configuration values were successfully stored in config dictionary
        validate_conf(config, "access_token")
        validate_conf(config, "expires_at")
        validate_conf(config, "checkpoint_dir")

    # raise exception if error occurs when attempting to read modular input config from stdin
    except Exception as e:
        raise Exception("Error getting Splunk configuration via STDIN: %s" % str(e))
    return config


def checkpoint_exists(config, name):
    """
    Checks to see if checkpoint file exists.
    Returns True if the checkpoint file exists.
    Returns False if the checkpoint file does not exist.

    Arguments:
    ---------------------------------------------------------------
     - config : ( dictionary ) contains modular input configuration
                provided by Splunkd

     - name   : ( string ) name of strava checkpoint file
                ( will be prefixed with 'strava' )
    ---------------------------------------------------------------
    """

    # build absolute path to checkpoint file
    chk_file_path = os.path.join(config["checkpoint_dir"], 'strava_' + name)
    # try to open this file
    try:
        open(chk_file_path, "r").close()
        return True
    except Exception as e:
        logging.error("Exception occured when attempting to open checkpoint file to validate it exists: " + str(e))
        return False


def read_checkpoint(config, name):
    """
    Reads epoch value of last activity indexed from checkpoint file.
    Returns the checkpoint value if it exists.
    Returns 0 if checkpoint value does not exist
    or an error occurs.

    Arguments:
    ---------------------------------------------------------------
     - config : ( dictionary ) contains modular input configuration
                provided by Splunkd

     - name   : ( string ) name of strava checkpoint file
                ( will be prefixed with 'strava' )
    ---------------------------------------------------------------
    """

    # build absolute path to checkpoint file
    chk_file_path = os.path.join(config["checkpoint_dir"], 'strava_' + name)

    # attempt read value from checkpoint file
    if checkpoint_exists(config, name):
        try:
            checkpoint = open(chk_file_path, "r").readline()
            if checkpoint:
                logging.debug("Value read from checkpoint file: " + str(checkpoint))
                return checkpoint
            else:
                logging.warn("Checkpoint value read from file is null.")
                # return 0 if unable to read checkpoint file
                return 0
        except Exception as e:
            logging.error("Error reading from checkpoint file: " + str(e))
            # return 0 if unable to read checkpoint file
            return 0
    else:
        logging.warn('Checkpoint file does not exist: ' + str(chk_file_path))
        # return 0 if unable to read checkpoint file
        return 0


def save_checkpoint(config, name, value):
    """
    Updates checkpoint file with new epoch value.
    Returns True if checkpoint file was successfully updated.
    Returns False if an error occured updating checkpoint file.

    Arguments:
    ---------------------------------------------------------------
     - config : ( dictionary ) contains modular input configuration
                provided by Splunkd

     - name   : ( string ) name of strava checkpoint file
                ( will be prefixed with 'strava' )

     - value  : ( integer ) epoch timestamp to be written to file
    ---------------------------------------------------------------
    """

    logging.debug("Saving epoch value to checkpoint file: " + str(value))
    try:
        # build absolute path to checkpoint file
        chk_file_path = os.path.join(config["checkpoint_dir"], 'strava_' + name)
        f = open(chk_file_path, "w")
        # convert epoch value to a string ( required or an error is thrown )
        str_value = str(value)
        # write new epoch value to checkpoint file
        f.write(str_value)
        f.close()
        logging.debug("Successfully updated checkpoint file: " + str(chk_file_path))
        return True
    except Exception as e:
        logging.error("Error writing to checkpoint file: " + str(e))
        return False


def run():
    """
    Run modular input.

    Unless a --scheme argument is provided, this will be the
    first method to be called when this script is executed.
    """

    logging.info("Running Strava activities modular input.")
    # parse modular input configuration (inputs.conf)
    config = get_config()
    logging.debug("config: " + str(config))

    # if configuration was successfully parsed, read value from checkpoint file
    if config:
        prev_checkpoint = read_checkpoint(config, 'activities')
        logging.debug("prev_checkpoint: " + str(prev_checkpoint))
        access_token = config['access_token']
    else:
        logging.error("Failed to load config.")

    # check to see if access token is expired
    if token_is_expired(config['expires_at']):
        try:
            new_access_token = None
            # refresh access token using values from config
            new_access_token = refresh_token(config['client_id'], config['client_secret'], config['refresh_token'], config['session_key'])
            if new_access_token:
                access_token = new_access_token
        except Exception as e:
            logging.error("Unable to refresh access token. Activities will not be queried from Strava API: " + str(e))

    # attempt to query new activities from Strava API and log results
    if get_strava_activities(config, access_token, prev_checkpoint):
        logging.info("Successfully retrieved activities from Strava.")
    else:
        logging.error("Unable to retrieve activities from Strava.")


# main constructor
if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == "--scheme":
            do_scheme()
    else:
        run()
